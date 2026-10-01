"""Tests for news.py (pre-game news feeds, test mode) and the builders' news_test steps.
Payloads are shaped like ESPN's, MLB statsapi's and Open-Meteo's responses.

Run:  python -m unittest test_news -v
"""
import datetime
import unittest

import news
import build as NFL
import build_nba as NBA


class FakeFeeds:
    """Swap news.get_json for canned payloads; counts requests per host."""
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []

    def __enter__(self):
        self._real, news.get_json = news.get_json, self
        news._WX.clear()
        news._WX_DOWN.clear()
        return self

    def __exit__(self, *a):
        news.get_json = self._real
        news._WX.clear()
        news._WX_DOWN.clear()

    def __call__(self, url):
        self.calls.append(url)
        for key, body in self.payloads.items():
            if key in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise RuntimeError(f"no fake for {url}")


def hours(start, n=48):
    return [(start + datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(n)]


class FeedTests(unittest.TestCase):
    def test_injuries_read_ids_from_links_and_status_fallback(self):
        body = {"injuries": [{"displayName": "Boston Celtics", "injuries": [
            {"status": "Out", "athlete": {"id": "123", "displayName": "A Player"}},
            {"type": {"description": "Day-To-Day"},
             "athlete": {"displayName": "B Player", "links": [{"href": "https://www.espn.com/nba/player/_/id/456/b-player"}]}}]}]}
        with FakeFeeds({"injuries": body}):
            got = news.espn_injuries("basketball/nba")
        self.assertEqual(got, [{"id": "123", "name": "A Player", "status": "Out"},
                               {"id": "456", "name": "B Player", "status": "Day-To-Day"}])
        self.assertTrue(news.is_out("Out"))
        self.assertFalse(news.is_out("Questionable"))

    def test_injuries_try_the_host_that_serves_ci_first(self):
        class Feeds(FakeFeeds):
            def __call__(self, url):
                self.calls.append(url)
                if "site.web.api" in url:
                    raise RuntimeError("HTTP Error 403: Forbidden")
                return {"injuries": []}
        with Feeds({}) as f:
            self.assertEqual(news.espn_injuries("basketball/nba"), [])
        self.assertEqual([u.split("/")[2] for u in f.calls], ["site.web.api.espn.com", "site.api.espn.com"])

    def test_an_unreachable_feed_records_nothing(self):
        with FakeFeeds({"injuries": RuntimeError("HTTP 403")}):
            self.assertIsNone(news.espn_injuries("football/nfl"))

    def test_mlb_lineups_map_team_codes_and_keep_order(self):
        body = {"dates": [{"games": [{"teams": {"away": {"team": {"abbreviation": "AZ"}}, "home": {"team": {"abbreviation": "CWS"}}},
                                      "lineups": {"awayPlayers": [{"fullName": "One Guy"}, {"fullName": "Two Guy"}],
                                                  "homePlayers": [{"fullName": "Three Guy"}]}}]}]}
        with FakeFeeds({"statsapi": body}):
            got = news.mlb_lineups(["2026-09-30"], lambda s: s.lower())
        self.assertEqual(got, {"2026-09-30": {"ARI": ["one guy", "two guy"], "CHW": ["three guy"]}})

    def test_forecast_reads_the_start_hour_once_per_place(self):
        t0 = datetime.datetime(2026, 10, 4, 12, tzinfo=datetime.timezone.utc)
        body = {"hourly": {"time": hours(t0), "temperature_2m": list(range(48)), "wind_speed_10m": [5.0] * 48,
                           "precipitation": [0.0] * 48}}
        with FakeFeeds({"open-meteo": body}) as f:
            self.assertEqual(news.forecast(41.862, -87.617, "2026-10-04T17:25Z"), [5, 5.0, 0.0])   # 17:00 hour
            self.assertEqual(news.forecast(41.862, -87.617, "2026-10-05T01:00Z"), [13, 5.0, 0.0])
            self.assertIsNone(news.forecast(41.862, -87.617, "2026-11-30T17:00Z"))                # beyond the forecast
            self.assertEqual(len(f.calls), 1)

    def test_weather_stops_after_the_first_failure(self):
        with FakeFeeds({"open-meteo": RuntimeError("timed out")}) as f:
            self.assertIsNone(news.forecast(41.9, -87.6, "2026-10-04T17:00Z"))
            self.assertIsNone(news.forecast(40.8, -74.1, "2026-10-04T17:00Z"))
            self.assertEqual(len(f.calls), 1)

    def test_wind_factor(self):
        self.assertEqual(news.wind_factor(8), 1.0)
        self.assertAlmostEqual(news.wind_factor(20), 0.9)


class NFLNewsTests(unittest.TestCase):
    def setUp(self):
        self.ko = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=30)
        et = self.ko.astimezone(NFL.ET_ZONE)
        self.sched = {"G1": {"id": "G1", "season": 2026, "week": 4, "date": et.date().isoformat(), "time": et.strftime("%H:%M"),
                             "away": "AAA", "home": "BBB", "final": False, "spread": None, "total": None,
                             "roof": "outdoors", "stadium": "Soldier Field"}}
        rows = []
        for i in range(12):
            r = [2026, i + 1, "BBB", "REG"] + [0] * 12 + [0, 0, None, None]
            r[12] = 5 if i % 2 else 4          # receptions
            rows.append(r)
        self.by_pid = {"p1": {"id": "p1", "n": "Test Player", "p": "WR", "t": "AAA", "g": rows}}
        vals = [NFL.stat_value("rec", r) for r in rows]
        self.mp = NFL.model_prob(vals, 4.5, "count", 1.0, NFL.CAL.get("rec"))

    def pick(self, **kw):
        p = {"src": "live", "gid": "G1", "pid": "p1", "player": "Test Player", "stat": "rec", "line": 4.5,
             "side": "over", "prob": round(self.mp["over"], 3), "adj": 1.0, "res": None, "mv": NFL.MODEL_V}
        p.update(kw)
        return p

    def run_news(self, picks, wind):
        body = {"hourly": {"time": hours(self.ko - datetime.timedelta(hours=5)), "temperature_2m": [40.0] * 48,
                           "wind_speed_10m": [wind] * 48, "precipitation": [0.0] * 48}}
        with FakeFeeds({"injuries": {"injuries": []}, "open-meteo": body}):
            NFL.news_test(picks, self.sched, self.by_pid)

    def test_wind_lowers_an_over(self):
        p = self.pick()
        self.run_news([p], 25.0)
        self.assertEqual(p["nw"]["wx"], [40.0, 25.0, 0.0])
        self.assertLess(p["nw"]["p2"], p["prob"])

    def test_calm_changes_nothing_and_old_models_get_no_p2(self):
        calm, old = self.pick(), self.pick(mv=None)
        self.run_news([calm, old], 6.0)
        self.assertAlmostEqual(calm["nw"]["p2"], calm["prob"], places=3)
        self.assertNotIn("p2", old["nw"])
        self.assertIn("wx", old["nw"])

    def test_a_started_game_is_left_alone(self):
        self.sched["G1"]["final"] = True
        p = self.pick()
        self.run_news([p], 25.0)
        self.assertNotIn("nw", p)


class NBANewsTests(unittest.TestCase):
    def test_regulars_and_missing_minutes(self):
        rows = []
        for i, d in enumerate(["2026-01-01", "2026-01-03", "2026-01-05", "2026-01-07", "2026-01-09"]):
            rows.append({"team": "BOS", "date": d, "pid": "star", "min": 36})
            rows.append({"team": "BOS", "date": d, "pid": "bench", "min": 12})
            rows.append({"team": "BOS", "date": d, "pid": "me", "min": 30})
            if i < 2:
                rows.append({"team": "BOS", "date": d, "pid": "gone", "min": 30})   # 2 of the last 5: not a regular
        usual = NBA.regular_minutes(rows)
        self.assertEqual(set(usual["BOS"]), {"star", "me"})
        g = [[2025, f"2026-01-0{i}", "NY", "REG", 10 + i % 3] + [0] * 15 for i in range(1, 10)]
        by_pid = {"me": {"id": "me", "n": "Me Player", "t": "BOS", "g": g},
                  "star": {"id": "star", "n": "Star Player", "t": "BOS", "g": g}}
        vals = [NBA.stat_get(r, "pts") for r in g]
        mp = NBA.model_prob(vals, 11.5, NBA.BW_FLOOR["pts"], 1.0, NBA.CAL.get("pts"))
        p = {"src": "live", "pid": "me", "team": "BOS", "stat": "pts", "line": 11.5, "side": "over",
             "prob": round(mp["over"], 3), "adj": 1.0, "res": None, "mv": NBA.MODEL_V, "start": "2099-01-01T00:00Z"}
        body = {"injuries": [{"injuries": [{"status": "Out", "athlete": {"id": "star", "displayName": "Star Player"}}]}]}
        with FakeFeeds({"injuries": body}):
            NBA.news_test([p], by_pid, rows)
        self.assertEqual(p["nw"]["om"], 36.0)
        self.assertGreater(p["nw"]["p2"], p["prob"])     # more minutes to go around: the over goes up


if __name__ == "__main__":
    unittest.main()

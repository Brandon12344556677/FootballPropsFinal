"""Tests for team_stats.py: GoatCounter row cleanup and the encryption the /team/ page decrypts."""
import json
import os
import shutil
import tempfile
import unittest

import team_stats


class Rows(unittest.TestCase):
    def test_sizes_named_from_id(self):
        out = team_stats.rows([{"id": "phone", "name": "", "count": 5}, {"id": "desktophd", "name": "", "count": 1}], "sizes")
        self.assertEqual([r["name"] for r in out], ["Phone", "Large computer screen"])

    def test_blank_referrer_is_unknown_and_keeps_scheme(self):
        out = team_stats.rows([{"name": "", "count": 60, "ref_scheme": "o"}], "toprefs")
        self.assertEqual(out, [{"name": "(unknown)", "n": 60, "kind": "o"}])

    def test_named_rows_pass_through(self):
        out = team_stats.rows([{"id": "US", "name": "United States", "count": 224}], "locations")
        self.assertEqual(out, [{"name": "United States", "n": 224}])


class TimeOnPage(unittest.TestCase):
    def test_ranges_in_order_with_zeros(self):
        events = [{"path": "time/1-3m", "count": 4, "event": True}, {"path": "/time/0-10s", "count": 9, "event": True},
                  {"path": "time/bogus", "count": 2, "event": True}, {"path": "other-event", "count": 1, "event": True}]
        out = team_stats.time_rows(events)
        self.assertEqual([r["name"] for r in out], team_stats.TIME_RANGES)
        self.assertEqual({r["name"]: r["n"] for r in out}["0-10s"], 9)
        self.assertEqual({r["name"]: r["n"] for r in out}["1-3m"], 4)
        self.assertEqual(sum(r["n"] for r in out), 13)

    def test_no_time_events_is_empty(self):
        self.assertEqual(team_stats.time_rows([]), [])

    def test_events_kept_out_of_visits(self):
        responses = {
            "/stats/total": {"total": 10, "total_events": 4,
                             "stats": [{"day": "2026-10-10", "daily": 10, "hourly": [0] * 23 + [10]}]},
            "/stats/hits": {"hits": [
                {"path": "/", "count": 6, "event": False, "stats": []},
                {"path": "time/1-3m", "count": 4, "event": True,
                 "stats": [{"day": "2026-10-10", "daily": 4, "hourly": [0] * 23 + [4]}]}]},
        }
        old = team_stats.get
        team_stats.get = lambda token, path, **q: responses.get(path, {"stats": []})
        try:
            r = team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 10, 23), 1)
        finally:
            team_stats.get = old
        self.assertEqual(r["total"], 6)
        self.assertEqual(r["daily"], [{"day": "2026-10-10", "n": 6}])
        self.assertEqual(r["hourly"][-1], 6)
        self.assertEqual([p["path"] for p in r["pages"]], ["/"])
        self.assertEqual({t["name"]: t["n"] for t in r["time"]}["1-3m"], 4)


class Clicks(unittest.TestCase):
    def test_click_events_parsed_and_sorted(self):
        events = [{"path": "click/kalshi-signup/nba", "count": 2, "event": True},
                  {"path": "/click/polymarket-signup/home", "count": 7, "event": True},
                  {"path": "time/1-3m", "count": 9, "event": True}]
        self.assertEqual(team_stats.click_rows(events),
                         [{"what": "polymarket-signup", "page": "home", "n": 7},
                          {"what": "kalshi-signup", "page": "nba", "n": 2}])

    def test_heatmap_hours_only_for_30_days_and_without_events(self):
        responses = {
            "/stats/total": {"total": 5, "total_events": 1,
                             "stats": [{"day": "2026-10-10", "daily": 5, "hourly": [0] * 20 + [5, 0, 0, 0]}]},
            "/stats/hits": {"hits": [{"path": "click/kalshi-market/nfl", "count": 1, "event": True,
                                      "stats": [{"day": "2026-10-10", "daily": 1, "hourly": [0] * 20 + [1, 0, 0, 0]}]}]},
        }
        old = team_stats.get
        team_stats.get = lambda token, path, **q: responses.get(path, {"stats": []})
        try:
            r30 = team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 10, 23), 30)
            r7 = team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 10, 23), 7)
        finally:
            team_stats.get = old
        self.assertEqual(r30["hours"], [{"day": "2026-10-10", "h": [0] * 20 + [4, 0, 0, 0]}])
        self.assertNotIn("hours", r7)
        self.assertEqual(r30["clicks"], [{"what": "kalshi-market", "page": "nfl", "n": 1}])


class Affiliates(unittest.TestCase):
    def test_ref_events_grouped_by_code(self):
        events = [{"path": "ref/sam/visit", "count": 9, "event": True},
                  {"path": "/ref/sam/new", "count": 5, "event": True,
                   "stats": [{"day": "2026-10-12", "daily": 2}, {"day": "2026-10-13", "daily": 3},
                             {"day": "2026-10-11", "daily": 0}]},
                  {"path": "ref/jo-2/new", "count": 7, "event": True, "stats": [{"day": "2026-10-13", "daily": 7}]},
                  {"path": "ref/x/new", "count": 4, "event": True},             # code too short
                  {"path": "ref/sam/clicked", "count": 4, "event": True},       # not a ref event
                  {"path": "click/kalshi-signup/nba", "count": 2, "event": True}]
        self.assertEqual(team_stats.ref_rows(events), [
            {"code": "jo-2", "new": 7, "visit": 0, "daily": [{"day": "2026-10-13", "new": 7}]},
            {"code": "sam", "new": 5, "visit": 9,
             "daily": [{"day": "2026-10-12", "new": 2}, {"day": "2026-10-13", "new": 3}]}])

    def test_time_on_site_from_stay_marks(self):
        # 10 timed visits: 4 left before 10s, 2 at 10-20s, 1 at 20s-1m, 2 at 1-3m, 1 stayed 30m+
        marks = {"0s": 10, "10s": 6, "20s": 4, "1m": 3, "3m": 1, "10m": 1, "30m": 1}
        events = [{"path": f"ref/sam/stay/{k}", "count": n, "event": True} for k, n in marks.items()]
        events += [{"path": "ref/sam/visit", "count": 11, "event": True},
                   {"path": "ref/sam/stay/2h", "count": 9, "event": True},       # not a mark
                   {"path": "ref/new-guy/stay/0s", "count": 2, "event": True}]   # timed, nothing else yet
        rows = {r["code"]: r for r in team_stats.ref_rows(events)}
        self.assertEqual(rows["sam"]["visit"], 11)
        self.assertEqual(rows["sam"]["stay"], {"n": 10, "avg": (4 * 5 + 2 * 15 + 40 + 2 * 120 + 1800) // 10,
                                               "marks": [10, 6, 4, 3, 1, 1, 1]})
        self.assertEqual(rows["new-guy"], {"code": "new-guy", "new": 0, "visit": 0, "daily": [],
                                           "stay": {"n": 2, "avg": 5, "marks": [2, 0, 0, 0, 0, 0, 0]}})

    def test_stay_marks_never_rise(self):
        # a later mark with more visits than an earlier one (old app.js without the 0s mark, blocked sends) is capped
        self.assertEqual(team_stats.stay_summary([3, 5, 0, 0, 0, 0, 0]), {"n": 3, "avg": 15, "marks": [3, 3, 0, 0, 0, 0, 0]})
        self.assertEqual(team_stats.stay_summary([0, 2, 0, 0, 0, 0, 0]), {"n": 0, "avg": None, "marks": [0, 0, 0, 0, 0, 0, 0]})

    def test_no_ref_events_is_empty(self):
        self.assertEqual(team_stats.ref_rows([{"path": "view/1", "count": 3, "event": True}]), [])


class LateEvening(unittest.TestCase):
    def test_tomorrow_from_goatcounter_is_dropped(self):
        # 11:45 PM in New York: "end" reaches past midnight, so GoatCounter returns tomorrow too
        responses = {"/stats/total": {"total": 26, "total_events": 0, "stats": [
            {"day": "2026-10-10", "daily": 26, "hourly": [0] * 21 + [20, 6, 0]},
            {"day": "2026-10-11", "daily": 0, "hourly": [0] * 24}]}}
        old = team_stats.get
        team_stats.get = lambda token, path, **q: responses.get(path, {"stats": [], "hits": []})
        try:
            ny = team_stats.ZoneInfo("America/New_York")
            r = team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 11, 3, 45), 1, ny)
        finally:
            team_stats.get = old
        self.assertEqual([d["day"] for d in r["daily"]], ["2026-10-10"])
        self.assertEqual(r["hourly"][21], 20)


class LocalDay(unittest.TestCase):
    def test_today_starts_at_local_midnight(self):
        seen = []
        old = team_stats.get
        team_stats.get = lambda token, path, **q: (seen.append((path, q)), {})[1]
        try:
            ny = team_stats.ZoneInfo("America/New_York")
            # 01:30 UTC on Oct 11 is still Oct 10 in New York (EDT, UTC-4)
            team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 11, 1, 30), 1, ny)
        finally:
            team_stats.get = old
        self.assertEqual(seen[0][0], "/stats/total")
        self.assertEqual(seen[0][1]["start"], "2026-10-10T04:00:00Z")
        self.assertEqual(seen[0][1]["end"], "2026-10-11T02:00:00Z")


@unittest.skipUnless(shutil.which("openssl"), "openssl not installed")
class Crypto(unittest.TestCase):
    def setUp(self):
        self.iter = team_stats.ITERATIONS
        team_stats.ITERATIONS = 1000  # fast; the format is the same
        self.dir = tempfile.mkdtemp()
        self.out = team_stats.OUT
        team_stats.OUT = os.path.join(self.dir, "stats.enc")

    def tearDown(self):
        team_stats.ITERATIONS = self.iter
        team_stats.OUT = self.out
        shutil.rmtree(self.dir)

    def test_round_trip_in_openssl_salted_format(self):
        blob = team_stats.encrypt('{"a":1}', "pw")
        import base64
        self.assertTrue(base64.b64decode(blob).startswith(b"Salted__"))  # the header the page reads
        self.assertEqual(team_stats.decrypt(blob, "pw"), '{"a":1}')

    def test_wrong_password_fails(self):
        blob = team_stats.encrypt('{"a":1}' * 20, "pw")
        with self.assertRaises(Exception):  # bad padding (openssl exits non-zero) or garbage that isn't JSON
            json.loads(team_stats.decrypt(blob, "nope"))

    def test_unchanged_ignores_timestamp(self):
        snap = {"generated_at": "2026-10-10T00:00:00Z", "d1": {"total": 3}}
        with open(team_stats.OUT, "w") as f:
            f.write(team_stats.encrypt(json.dumps(snap), "pw"))
        self.assertTrue(team_stats.unchanged(dict(snap, generated_at="2026-10-10T01:00:00Z"), "pw"))
        self.assertFalse(team_stats.unchanged(dict(snap, d1={"total": 4}), "pw"))
        self.assertFalse(team_stats.unchanged(snap, "other"))


class Skip(unittest.TestCase):
    def test_no_secrets_does_nothing(self):
        old = {k: os.environ.pop(k, None) for k in ("GOATCOUNTER_TOKEN", "TEAM_DASH_PASSWORD")}
        try:
            self.assertEqual(team_stats.main(), 0)
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()


class Spikes(unittest.TestCase):
    def test_spikes(self):
        import team_stats
        daily = [{"day": f"d{i}", "n": n} for i, n in enumerate([10] * 8 + [40, 5])]
        snap = {"d30": {"daily": daily},
                "d1": {"toprefs": [{"name": "snapchat.com", "n": 30}, {"name": "google", "n": 16}, {"name": "(unknown)", "n": 20}],
                       "pages": [{"path": "/nhl.html", "n": 9}]},
                "d7": {"toprefs": [{"name": "snapchat.com", "n": 35}, {"name": "google", "n": 140}, {"name": "(unknown)", "n": 21}],
                       "pages": [{"path": "/nhl.html", "n": 7}]}}
        out = team_stats.spikes(snap)
        self.assertEqual([s["what"] for s in out],
                         ["Visits from no referrer (direct, apps)", "Visits from snapchat.com", "Visits yesterday"])
        self.assertEqual((out[1]["today"], out[1]["usual"]), (30, 5.0))


class ViewsAndVisitors(unittest.TestCase):
    def test_view_events_give_page_views_and_unique_visitors(self):
        events = [{"path": "view/1", "count": 10, "event": True, "stats": [{"day": "2026-10-11", "daily": 4}, {"day": "2026-10-12", "daily": 6}]},
                  {"path": "view/2", "count": 6, "event": True, "stats": [{"day": "2026-10-12", "daily": 6}]},
                  {"path": "view/12", "count": 1, "event": True, "stats": [{"day": "2026-10-12", "daily": 1}]},
                  {"path": "time/1-3m", "count": 9, "event": True, "stats": [{"day": "2026-10-12", "daily": 9}]}]
        v = team_stats.view_stats(events)
        self.assertEqual((v["views"], v["visitors"]), (17, 10))
        self.assertEqual(v["daily"], [{"day": "2026-10-11", "views": 4, "visitors": 4},
                                      {"day": "2026-10-12", "views": 13, "visitors": 6}])
        self.assertEqual(team_stats.view_stats([]), {"views": 0, "visitors": 0, "daily": []})

    def test_hits_are_paged_past_100(self):
        calls = []

        def get(token, path, **q):
            calls.append(q.get("exclude_paths"))
            if q.get("exclude_paths"):
                return {"hits": [{"path_id": 3, "path": "view/9", "count": 1, "event": True}], "more": False}
            return {"hits": [{"path_id": 1, "path": "/"}, {"path_id": 2, "path": "/nhl.html"}], "more": True}
        old = team_stats.get
        team_stats.get = get
        try:
            hits = team_stats.all_hits("t", {"start": "a", "end": "b"})
        finally:
            team_stats.get = old
        self.assertEqual([h["path"] for h in hits], ["/", "/nhl.html", "view/9"])
        self.assertEqual(calls, [None, "1,2"])


class EmailStats(unittest.TestCase):
    def test_counts_only_and_none_without_access(self):
        import io, json as _json, urllib.error
        from unittest import mock
        counts = {"regular": 12, "unactivated": 3}

        def opener(req, timeout=30):
            kind = req.full_url.split("type=")[1]
            return io.BytesIO(_json.dumps({"count": counts[kind], "results": [{"email": "x@y.z"}]}).encode())
        with mock.patch.object(team_stats.urllib.request, "urlopen", side_effect=opener):
            self.assertEqual(team_stats.email_stats("k"), {"subscribers": 12, "pending": 3})
        def forbidden(req, timeout=30):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        with mock.patch.object(team_stats.urllib.request, "urlopen", side_effect=forbidden):
            self.assertIsNone(team_stats.email_stats("k"))
        self.assertIsNone(team_stats.email_stats(""))


class Insights(unittest.TestCase):
    def test_sport_visitor_and_click_dailies(self):
        hits = [{"path": "/nfl.html", "stats": [{"day": "2026-10-11", "daily": 5}, {"day": "2026-10-12", "daily": 2}]},
                {"path": "/games/nfl/buf-at-la-2026-10-12.html", "stats": [{"day": "2026-10-12", "daily": 1}]},
                {"path": "/players/nhl/connor-mcdavid.html", "stats": [{"day": "2026-10-12", "daily": 3}]},
                {"path": "/", "stats": [{"day": "2026-10-12", "daily": 9}]},
                {"path": "visitor/new", "event": True, "stats": [{"day": "2026-10-12", "daily": 4}]},
                {"path": "visitor/returning", "event": True, "stats": [{"day": "2026-10-12", "daily": 2}]},
                {"path": "days/2", "event": True, "stats": [{"day": "2026-10-12", "daily": 1}]},
                {"path": "days/10+", "event": True, "stats": [{"day": "2026-10-12", "daily": 1}]},
                {"path": "click/polymarket-signup-sheet/nhl", "event": True, "stats": [{"day": "2026-10-12", "daily": 1}]},
                {"path": "click/email-list/link", "event": True, "stats": [{"day": "2026-10-12", "daily": 3}]},
                {"path": "click/polymarket-market/nfl", "event": True, "stats": [{"day": "2026-10-12", "daily": 7}]}]
        self.assertEqual(team_stats.daily_by(hits, team_stats.sport_of),
                         [{"day": "2026-10-11", "nfl": 5}, {"day": "2026-10-12", "nfl": 3, "nhl": 3}])
        self.assertEqual(team_stats.daily_by(hits, team_stats.visitor_kind), [{"day": "2026-10-12", "new": 4, "returning": 2}])
        self.assertEqual(team_stats.daily_by(hits, team_stats.days_kind), [{"day": "2026-10-12", "2": 1, "10+": 1}])
        self.assertEqual(team_stats.daily_by(hits, team_stats.click_kind), [{"day": "2026-10-12", "signup": 1, "email": 3}])

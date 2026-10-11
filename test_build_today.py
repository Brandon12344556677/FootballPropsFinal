"""Tests for build_today.last_results: each sport's latest graded day for the results line."""
import unittest

import build_today

COLS = ["src", "res", "lists", "price", "start", "date"]


def doc(rows):
    return {"cols": COLS, "picks": [[r.get(c) for c in COLS] for r in rows]}


class LastResults(unittest.TestCase):
    def test_latest_day_with_top25_and_value(self):
        d = doc([
            {"src": "live", "res": "hit", "lists": "T", "start": "2026-10-09T23:00:00Z"},
            {"src": "live", "res": "hit", "lists": "T", "start": "2026-10-10T23:00:00Z"},
            {"src": "live", "res": "miss", "lists": "TV", "price": 0.5, "start": "2026-10-10T23:30:00Z"},
            {"src": "live", "res": "hit", "lists": "V", "price": 0.4, "start": "2026-10-11T01:00:00Z"},   # Oct 10 in ET
            {"src": "backtest", "res": "hit", "lists": "T", "start": "2026-10-10T23:00:00Z"},
            {"src": "live", "res": "push", "lists": "T", "start": "2026-10-10T23:00:00Z"},
        ])
        r = build_today.last_results("nhl", d, "2026-10-11")
        self.assertEqual(r["day"], "2026-10-10")
        self.assertEqual(r["T"], {"n": 2, "hit": 1})
        self.assertEqual(r["V"]["n"], 2)
        self.assertEqual(r["V"]["hit"], 1)
        self.assertAlmostEqual(r["V"]["units"], 0.5)   # -1 + (1/0.4 - 1)

    def test_nfl_uses_date_and_cents(self):
        d = doc([{"src": "live", "res": "hit", "lists": "V", "price": 50, "date": "2026-10-05"}])
        r = build_today.last_results("nfl", d, "2026-10-11")
        self.assertEqual(r["day"], "2026-10-05")
        self.assertAlmostEqual(r["V"]["units"], 1.0)
        self.assertNotIn("T", r)

    def test_too_old_or_future_is_ignored(self):
        d = doc([{"src": "live", "res": "hit", "lists": "T", "date": "2026-09-20"},
                 {"src": "live", "res": "hit", "lists": "T", "date": "2026-10-12"}])
        self.assertIsNone(build_today.last_results("nfl", d, "2026-10-11"))


class Calibration(unittest.TestCase):
    def test_buckets_from_live_graded_picks(self):
        cols = ["src", "res", "prob"]
        d = {"cols": cols, "picks": [["live", "hit", 0.72], ["live", "miss", 0.78], ["live", "hit", 0.95],
                                     ["backtest", "hit", 0.75], ["live", None, 0.75], ["live", "push", 0.75],
                                     ["live", "hit", 0.30], ["live", "hit", 1.0]]}
        out = build_today.calibration([("nhl", d)])
        self.assertEqual([(b["lo"], b["n"]) for b in out], [(70, 2), (90, 2)])
        self.assertEqual(out[0]["hit"], 0.5)
        self.assertEqual(out[0]["said"], 0.75)
        self.assertEqual(out[1]["hit"], 1.0)        # a 100% pick lands in the 90-100 bucket


class SearchRows(unittest.TestCase):
    def test_this_or_last_season_only(self):
        db = {"season": 2026, "players": [
            {"id": 1, "n": "Now Player", "t": "NE", "p": "WR", "g": [[2026, 1]]},
            {"id": 2, "n": "Last Year", "t": "LV", "p": "RB", "g": [[2025, 3]]},
            {"id": 3, "n": "Long Gone", "t": "GB", "p": "QB", "g": [[2023, 1]]},
            {"id": 4, "n": "No Games", "t": "GB", "p": "QB", "g": []}]}
        self.assertEqual(build_today.search_rows("nfl", db),
                         [["nfl", "1", "Now Player", "NE", "WR"], ["nfl", "2", "Last Year", "LV", "RB"]])


class WriteRecent(unittest.TestCase):
    def test_keeps_pending_and_recent_results_only(self):
        import json, os, tempfile
        d = doc([
            {"src": "live", "res": None, "date": "2026-09-01"},     # pending, however old
            {"src": "live", "res": "hit", "date": "2026-10-10"},    # recent result
            {"src": "live", "res": "dnp", "date": "2026-10-10"},    # didn't play: not needed on first load
            {"src": "live", "res": "miss", "date": "2026-10-01"},   # too old
        ])
        tmp = tempfile.mkdtemp()
        path, n = build_today.write_recent(os.path.join(tmp, "nhl_picks.json"), d, "2026-10-11")
        self.assertTrue(path.endswith("nhl_picks_recent.json"))
        self.assertEqual(n, 2)
        with open(path, encoding="utf-8") as f:
            out = json.load(f)
        self.assertEqual(out["cols"], COLS)
        self.assertEqual([r[COLS.index("res")] for r in out["picks"]], [None, "hit"])
        self.assertEqual(out["recentFrom"], "2026-10-09")


if __name__ == "__main__":
    unittest.main()


class StreaksAndMoves(unittest.TestCase):
    def cand(self, pid, side, line, l10, price, prob=0.8, px0=None, sport="nfl"):
        return {"sport": sport, "pid": pid, "player": pid, "team": "A", "opp": "B", "stat": "s", "statText": "S",
                "line": line, "side": side, "prob": prob, "price": price, "start": "2026-10-12T17:00:00Z",
                "l10": l10, "px0": px0}

    def test_streak_counts_back_from_latest_game_and_skips_cheap_payouts(self):
        c = [self.cand("a", "over", 4.5, [1, 6, 7, 8, 9, 10], 0.7),        # 5 straight
             self.cand("b", "over", 4.5, [6, 6, 6, 6, 6, 6, 6], 0.9),      # 7 straight but pays too little
             self.cand("c", "under", 4.5, [5, 3, 3, 3, 3], 0.6)]           # 4 straight: too short
        out = build_today.streaks(c)
        self.assertEqual([(r["pid"], r["streak"]) for r in out], [("a", 5)])

    def test_moves_need_three_cents_toward_the_pick(self):
        c = [self.cand("a", "over", 1.5, [], 0.60, px0=0.50), self.cand("b", "over", 1.5, [], 0.52, px0=0.50),
             self.cand("c", "over", 1.5, [], 0.75, px0=0.70)]   # +5c: listed after the +10c move
        self.assertEqual([r["pid"] for r in build_today.moves(c)], ["a", "c"])


class Agents(unittest.TestCase):
    """Fast price moves, news flags and the promo-day count (build_today)."""
    NOW = __import__("datetime").datetime(2026, 10, 11, 18, 0, tzinfo=__import__("datetime").timezone.utc)

    def cand(self, pid, price, sport="nhl", value=False, lists="", flag=None, start="2026-10-11T23:00:00Z"):
        return {"sport": sport, "pid": pid, "player": pid, "team": "A", "opp": "B", "stat": "s", "statText": "S",
                "line": 1.5, "side": "under", "prob": 0.8, "price": price, "start": start, "value": value,
                "lists": lists, "flag": flag}

    def test_fast_moves_compare_with_the_price_about_an_hour_ago(self):
        a, b, c = self.cand("a", 0.70), self.cand("b", 0.55), self.cand("c", 0.80)
        hist = {"runs": [["2026-10-11T16:30:00Z", {build_today.ckey(a): 0.10}],      # too old: dropped
                         ["2026-10-11T17:00:00Z", {build_today.ckey(a): 0.55, build_today.ckey(b): 0.60,
                                                   build_today.ckey(c): 0.95}],
                         ["2026-10-11T17:40:00Z", {build_today.ckey(a): 0.69}]]}       # too recent to compare with
        out, keep = build_today.fast_moves([a, b, c], hist, self.NOW)
        self.assertEqual([(r["pid"], r["was"]) for r in out], [("a", 0.55), ("c", 0.95)])   # b moved only 5c
        self.assertEqual([r[0] for r in keep["runs"]], ["2026-10-11T17:00:00Z", "2026-10-11T17:40:00Z",
                                                         "2026-10-11T18:00:00Z"])

    def test_news_flags_list_flagged_picks_only(self):
        out = build_today.news_flags([self.cand("a", 0.6, lists="V", flag="Questionable"), self.cand("b", 0.6, lists="T")])
        self.assertEqual([(r["pid"], r["flag"], r["lists"]) for r in out], [("a", "Questionable", "V")])

    def test_featured_is_listed_or_in_the_feed(self):
        a, b, c = self.cand("a", 0.6, lists="T"), self.cand("b", 0.6), self.cand("c", 0.6)
        self.assertEqual([x["pid"] for x in build_today.featured([a, b, c], [dict(c, kind="safe")])], ["a", "c"])

    def test_promo_day_against_a_usual_day(self):
        cols = ["src", "lists", "start", "date"]
        doc = {"cols": cols, "picks": [["live", "V", "2026-10-09T23:00:00Z", None], ["live", "TV", "2026-10-09T23:30:00Z", None],
                                       ["live", "V", "2026-10-10T23:00:00Z", None], ["live", "T", "2026-10-10T23:00:00Z", None],
                                       ["live", "V", "2026-10-11T23:00:00Z", None]]}
        cands = [self.cand("a", 0.5, value=True), self.cand("b", 0.5, value=True, sport="nfl"),
                 self.cand("c", 0.5, value=True, start="2026-10-12T23:00:00Z"), self.cand("d", 0.5)]
        out = build_today.promo_day(cands, [("nhl", doc)], "2026-10-11")
        self.assertEqual((out["n"], out["by"], out["avg"], out["days"], out["rank"]), (2, {"nhl": 1, "nfl": 1}, 1.5, 2, 0.5))

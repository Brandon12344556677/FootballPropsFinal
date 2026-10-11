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

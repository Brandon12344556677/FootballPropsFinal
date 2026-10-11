"""Tests for edge_report.py: which picks count, and the numbers per strategy."""
import unittest

import edge_report as E

COLS = ["src", "res", "price", "px0", "start", "date", "side", "stat", "line", "lists"]


def doc(rows):
    return {"cols": COLS, "picks": [[r.get(c) for c in COLS] for r in rows]}


class Graded(unittest.TestCase):
    def test_only_live_results_with_believable_prices(self):
        rows = E.graded("nhl", doc([
            {"src": "live", "res": "hit", "price": 0.6, "px0": 0.55, "start": "2026-10-08T23:00:00Z"},
            {"src": "live", "res": "hit", "price": 0.02, "start": "2026-10-08T23:00:00Z"},              # too cheap to be real
            {"src": "live", "res": "hit", "price": 0.15, "px0": 0.6, "start": "2026-10-08T23:00:00Z"},  # 45c collapse
            {"src": "live", "res": None, "price": 0.6, "start": "2026-10-08T23:00:00Z"},
            {"src": "bt", "res": "hit", "price": 0.6, "start": "2026-10-08T23:00:00Z"},
            {"src": "live", "res": "push", "price": 0.6, "start": "2026-10-08T23:00:00Z"}]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["day"], "2026-10-08")
        nfl = E.graded("nfl", doc([{"src": "live", "res": "miss", "price": 55, "date": "2026-10-05"}]))
        self.assertEqual((nfl[0]["pr"], nfl[0]["day"]), (0.55, "2026-10-05"))


class Summary(unittest.TestCase):
    def rows(self, wins, losses, pr=0.5, sport="mlb", side="under", day="2026-10-0{}"):
        out = []
        for i in range(wins + losses):
            out.append({"sport": sport, "day": day.format(i % 9 + 1), "pr": pr, "win": i < wins, "side": side,
                        "stat": "tb", "line": 1.5, "lists": ""})
        return out

    def test_roi_units_and_verdicts(self):
        import random
        s = E.summary(self.rows(70, 30), "2026-10-10", random.Random(1))
        self.assertEqual((s["n"], s["hit"], s["units"], s["roi"]), (100, 0.7, 40.0, 0.4))
        self.assertEqual(s["verdict"], "Edge holding")
        self.assertEqual(E.summary(self.rows(30, 70), "2026-10-10", random.Random(1))["verdict"], "Losing")
        self.assertIsNone(E.summary([], "2026-10-10", random.Random(1)))

    def test_strategies_pick_their_rows(self):
        out = {s["key"]: s for s in E.build(self.rows(6, 4) + self.rows(3, 7, side="over", pr=0.6), "2026-10-10")}
        self.assertEqual(out["mlb-unders-mid"]["n"], 10)
        self.assertEqual(out["mlb-tb-under"]["n"], 10)
        self.assertEqual(out["mlb-overs"]["n"], 10)
        self.assertEqual(out["unders"]["n"], 10)
        self.assertNotIn("nhl-top", out)


if __name__ == "__main__":
    unittest.main()

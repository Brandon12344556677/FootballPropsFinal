"""The NBA over/under calibration (build_nba.py fit_side_cal / apply_side_cal): overs the model rates
too high get a cautious shift down, fitted from graded picks, and pending picks are re-scored with it."""
import math
import random
import unittest

import build_nba as N


def graded(n, stat, side, prob, hit_rate, seed=1, sb=None):
    rng = random.Random(seed)
    return [{"src": "live", "stat": stat, "side": side, "prob": prob, "mv": N.MODEL_V, "sb": sb,
             "res": "hit" if rng.random() < hit_rate else "miss"} for _ in range(n)]


class SideCal(unittest.TestCase):
    def test_too_few_graded_picks_no_shift(self):
        self.assertEqual(N.fit_side_cal(graded(100, "ast", "over", 0.66, 0.5)), {})

    def test_overs_rated_high_get_a_cautious_shift_down(self):
        picks = graded(600, "ast", "over", 0.66, 0.49) + graded(600, "pts", "under", 0.69, 0.80, seed=2)
        cal = N.fit_side_cal(picks)
        full = math.log(0.49 / 0.51) - math.log(0.66 / 0.34)            # the whole gap on assist overs
        self.assertLess(cal["ast"], 0)
        self.assertGreater(cal["ast"], full)                              # only part of it (cautious)
        self.assertGreaterEqual(cal["ast"], -N.SIDE_CAL_MAX)
        self.assertLess(cal["pts"], 0)        # unders hitting more than rated is the same direction: overs too high
        self.assertIn("*", cal)

    def test_fit_reads_the_raw_chance(self):
        # picks already shifted by sb: the fit undoes it, so the shift doesn't feed on itself
        raw = graded(800, "reb", "over", 0.66, 0.55)
        f = lambda x, d: round(1 / (1 + math.exp(-(math.log(x / (1 - x)) + d))), 3)
        shifted = [dict(p, prob=f(0.66, -0.2), sb=-0.2) for p in raw]
        self.assertAlmostEqual(N.fit_side_cal(raw)["reb"], N.fit_side_cal(shifted)["reb"], delta=0.02)

    def test_pending_picks_rescored_side_kept(self):
        over = {"src": "live", "stat": "ast", "side": "over", "prob": 0.66, "lo": 0.55, "hi": 0.75, "mv": N.MODEL_V, "res": None}
        under = {"src": "live", "stat": "ast", "side": "under", "prob": 0.60, "lo": 0.50, "hi": 0.70, "mv": N.MODEL_V, "res": None}
        locked = dict(over, lk="2026-10-23T23:00Z")
        done = dict(over, res="hit")
        with unittest.mock.patch.object(N, "pick_locked", lambda p: bool(p.get("lk"))):
            n = N.apply_side_cal([over, under, locked, done], {"ast": -0.3})
            self.assertEqual(n, 2)
            self.assertLess(over["prob"], 0.66)
            self.assertGreater(under["prob"], 0.60)                         # the under gets more likely
            self.assertEqual((over["side"], under["side"], over["sb"]), ("over", "under", -0.3))
            self.assertTrue(over["lo"] < over["prob"] < over["hi"] and under["lo"] < under["prob"] < under["hi"])
            self.assertEqual((locked["prob"], done["prob"]), (0.66, 0.66))
            p1 = over["prob"]
            self.assertEqual(N.apply_side_cal([over], {"ast": -0.3}), 0)   # same shift: nothing to do
            N.apply_side_cal([over], {"ast": -0.1})                         # a new fit replaces the old shift
            self.assertGreater(over["prob"], p1)
            N.apply_side_cal([over], {})                                    # no shift any more: back to the raw chance
            self.assertAlmostEqual(over["prob"], 0.66, delta=0.002)
            self.assertIsNone(over["sb"])


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()

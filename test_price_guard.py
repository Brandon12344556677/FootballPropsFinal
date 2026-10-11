"""Tests for depth.guard: a sudden price jump waits for a second run; a price under 5c is never taken."""
import unittest

import depth


def pick(pp, price=None, vn="P", pj=None):
    p = {"pp": pp, "pd": 100.0, "kp": None, "kd": None, "price": price, "vn": vn if price is not None else None,
         "th": None}
    if pj is not None:
        p["pj"] = pj
    return p


def run(p):
    """One builder run: refresh, choose (twice, as depth.verify does), then save (drops _ keys)."""
    depth.choose(p)
    depth.choose(p)
    return {k: v for k, v in p.items() if not k.startswith("_")}


class Guard(unittest.TestCase):
    def test_small_moves_go_through(self):
        p = run(pick(0.62, price=0.52))
        self.assertEqual(p["price"], 0.62)
        self.assertNotIn("pj", p)

    def test_a_spike_is_held_then_confirmed_by_the_next_run(self):
        p = run(pick(0.10, price=0.52))
        self.assertEqual((p["price"], p["pj"]), (0.52, 0.10))      # held, even though choose() ran twice
        p["pp"] = 0.11
        p = run(p)
        self.assertEqual(p["price"], 0.11)                          # seen again next run: real
        self.assertNotIn("pj", p)

    def test_a_spike_that_goes_away_never_lands(self):
        p = run(pick(0.10, price=0.52))
        p["pp"] = 0.53
        p = run(p)
        self.assertEqual(p["price"], 0.53)
        self.assertNotIn("pj", p)

    def test_under_five_cents_is_never_taken(self):
        self.assertEqual(run(pick(0.02, price=0.07))["price"], 0.07)   # held at the last real price
        self.assertIsNone(run(pick(0.03))["price"])                    # a first price that low: no price

    def test_nfl_cents(self):
        p = run(pick(20, price=63))
        self.assertEqual((p["price"], p["pj"]), (63, 20))
        self.assertEqual(run(pick(58, price=63))["price"], 58)
        self.assertEqual(run(pick(3, price=40))["price"], 40)


if __name__ == "__main__":
    unittest.main()

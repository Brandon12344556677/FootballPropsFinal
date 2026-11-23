"""NBA Value is overs only, 30-60c, 20+ effective games (since Nov 23, 2026); the record counts the current rule."""
import itertools
import unittest

import build_nba as B
import build_today as T
import edge_report as E


def pick(side="over", price=0.45, prob=0.65, neff=25.0, lists="V", res="hit"):
    return {"src": "live", "side": side, "price": price, "px0": price, "prob": prob, "neff": neff, "lists": lists, "res": res,
            "pid": "1", "stat": "pts", "line": 19.5, "gid": "g", "date": "2026-11-20"}


class Rule(unittest.TestCase):
    def test_price_band_and_edge(self):
        self.assertTrue(B.value_qualifies(0.65, 0.45))
        self.assertTrue(B.value_qualifies(0.45, 0.30))
        self.assertFalse(B.value_qualifies(0.80, 0.60))       # 60c and up: out
        self.assertFalse(B.value_qualifies(0.40, 0.29))       # under 30c: out
        self.assertFalse(B.value_qualifies(0.55, 0.45))       # only 10 points over

    def test_recorded_pick_fits_only_as_an_over_with_enough_games(self):
        self.assertTrue(B.value_fits(pick()))
        self.assertFalse(B.value_fits(pick(side="under")))
        self.assertFalse(B.value_fits(pick(neff=12)))
        self.assertFalse(B.value_fits(pick(price=0.62)))
        self.assertFalse(B.value_fits(pick(price=None)))

    def test_every_board_helper_agrees_with_the_builder(self):
        for side, price, neff in itertools.product(("over", "under"), (None, 0.29, 0.30, 0.45, 0.599, 0.60, 0.8), (6, 19.9, 20, 40)):
            p = pick(side=side, price=price, neff=neff)
            want = B.value_fits(p)
            self.assertEqual(T.value_fits("nba", p), want, (side, price, neff))
            row = {"lists": "V", "side": side, "pr": price if price is not None else 0.0, "neff": neff}
            nba_value = next(t for k, _, _, t in E.STRATEGIES if k == "nba-value")
            self.assertEqual(bool(nba_value(row)), want and price is not None, (side, price, neff))

    def test_record_counts_the_current_rule_and_keeps_the_rest_apart(self):
        rec = B.live_record([pick(price=0.5, res="hit"), pick(side="under", price=0.5, res="miss"),
                             pick(neff=8, price=0.4, res="miss"), pick(lists="T", price=0.9, res="hit")])
        self.assertEqual((rec["V"]["n"], rec["V"]["hit"], rec["V"]["units"]), (1, 1, 1.0))
        self.assertEqual((rec["Vpre"]["n"], rec["Vpre"]["units"]), (2, -2.0))
        self.assertEqual(rec["T"]["n"], 1)

    def test_other_boards_unchanged(self):
        self.assertTrue(T.value_fits("nhl", pick(side="under", price=0.9)))
        self.assertFalse(T.value_fits("mlb", pick(side="over")))
        self.assertTrue(T.value_fits("mlb", pick(side="under")))


if __name__ == "__main__":
    unittest.main()

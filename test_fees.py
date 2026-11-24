"""fees.py: units and return after the exchange's taker fee, with a +/- range."""
import unittest

import fees


class TestFees(unittest.TestCase):
    def test_fee_per_unit(self):
        # Kalshi 0.07 x p x (1-p) per contract; 1/p contracts per unit -> 0.07 x (1-p)
        self.assertAlmostEqual(fees.fee(0.5, "K"), 0.035)
        self.assertAlmostEqual(fees.fee(0.5, "P"), 0.025)
        self.assertAlmostEqual(fees.fee(0.5, None), 0.035)    # unknown venue: the higher fee

    def test_net(self):
        self.assertAlmostEqual(fees.net(0.5, True, "K"), 1 - 0.035)
        self.assertAlmostEqual(fees.net(0.5, False, "K"), -1.035)
        self.assertAlmostEqual(fees.net(0.96, True, "P"), 1 / 0.96 - 1 - 0.05 * 0.04)

    def test_summary(self):
        s = fees.summary([(0.5, True, "K"), (0.5, False, "K")])
        self.assertAlmostEqual(s["net"], -0.07)
        self.assertAlmostEqual(s["roiNet"], -0.035)
        self.assertIsNone(s["pm"])          # under MIN_RANGE bets
        self.assertTrue(s["early"])
        self.assertAlmostEqual(s["avgPx"], 0.5)

    def test_range(self):
        bets = [(0.5, i % 2 == 0, "P") for i in range(100)]
        s = fees.summary(bets)
        self.assertIsNotNone(s["pm"])
        self.assertTrue(0.15 < s["pm"] < 0.25)   # ~1.96 x 1.0 / sqrt(100)
        self.assertTrue(s["early"])            # -2.5% inside a +/-20% range

    def test_empty(self):
        self.assertIsNone(fees.summary([])["net"])


if __name__ == "__main__":
    unittest.main()

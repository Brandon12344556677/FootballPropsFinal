"""Tests for build_today.spark / with_spark: the price-since-listed line on the home page's pick cards."""
import datetime
import unittest

import build_today as T

NOW = datetime.datetime(2026, 11, 17, 18, 0, tzinfo=datetime.timezone.utc)
PICK = {"sport": "nba", "pid": "1", "stat": "pts", "line": 9.5, "side": "under", "price": 0.32, "px0": 0.30}


def at(minutes):
    return NOW + datetime.timedelta(minutes=minutes)


class Spark(unittest.TestCase):
    def test_starts_from_the_recorded_price(self):
        sp = T.spark([PICK], {}, NOW)
        self.assertEqual([v for _, v in sp[T.ckey(PICK)]], [30, 32])

    def test_adds_a_point_on_a_change_or_every_half_hour(self):
        h = {"spark": T.spark([PICK], {}, NOW)}
        same = T.spark([PICK], h, at(10))
        self.assertEqual(len(same[T.ckey(PICK)]), 2)              # same price 10 minutes later: nothing new
        moved = T.spark([dict(PICK, price=0.35)], h, at(10))
        self.assertEqual([v for _, v in moved[T.ckey(PICK)]], [30, 32, 35])
        later = T.spark([PICK], h, at(T.SPARK_GAP))
        self.assertEqual(len(later[T.ckey(PICK)]), 3)

    def test_capped_and_dropped_when_no_longer_featured(self):
        h = {"spark": {T.ckey(PICK): [[i, 30 + i % 3] for i in range(40)], "nba|2|reb|5.5|over": [[1, 50]]}}
        sp = T.spark([dict(PICK, price=0.9)], h, NOW)
        self.assertEqual(len(sp[T.ckey(PICK)]), T.SPARK_N)
        self.assertEqual(sp[T.ckey(PICK)][-1][1], 90)
        self.assertNotIn("nba|2|reb|5.5|over", sp)

    def test_home_picks_get_the_line_once_it_has_three_points(self):
        sp = {T.ckey(PICK): [[1, 30], [2, 32], [3, 35]]}
        picks = T.with_spark([dict(PICK), dict(PICK, pid="9")], sp)
        self.assertEqual(picks[0]["sp"], [30, 32, 35])
        self.assertNotIn("sp", picks[1])
        self.assertNotIn("sp", T.with_spark([dict(PICK)], {T.ckey(PICK): [[1, 30], [2, 32]]})[0])


if __name__ == "__main__":
    unittest.main()

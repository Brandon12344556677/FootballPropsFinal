"""Game times and "today" use real US Eastern time (daylight saving included), not a fixed UTC-4."""
import datetime
import unittest

import build_mlb
import build_nba
import build_nhl


class TestEastern(unittest.TestCase):
    def test_clock_winter_and_summer(self):
        for B in (build_nba, build_nhl, build_mlb):
            winter = B.parse_utc("2026-11-25T01:00Z").astimezone(B.ET)   # EST, UTC-5
            summer = B.parse_utc("2026-07-01T23:00Z").astimezone(B.ET)   # EDT, UTC-4
            self.assertEqual(winter.strftime("%H:%M"), "20:00")
            self.assertEqual(winter.date().isoformat(), "2026-11-24")
            self.assertEqual(summer.strftime("%H:%M"), "19:00")

    def test_today_is_eastern(self):
        for B in (build_nba, build_nhl, build_mlb):
            self.assertEqual(B.ET_TODAY, datetime.datetime.now(B.ET).date().isoformat())

    def test_mlb_pick_date(self):
        # 11:30 PM Eastern on Nov 24 is 04:30 UTC on Nov 25: still the 24th's game
        self.assertEqual(build_mlb.pick_et_date({"start": "2026-11-25T04:30Z"}), "2026-11-24")
        self.assertEqual(build_mlb.pick_et_date({"start": "2026-07-02T03:30Z"}), "2026-07-01")


if __name__ == "__main__":
    unittest.main()

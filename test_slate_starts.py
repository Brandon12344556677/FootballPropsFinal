"""Tests for the NHL/NBA slate: today's picks get their game's start time even in the morning, when
ESPN's default scoreboard still shows last night's games (seen Oct 15, 2026)."""
import unittest
from unittest import mock

import build_nhl as N


def ev(eid, away, home, start, state="pre"):
    return {"id": eid, "date": start, "competitions": [{
        "status": {"type": {"state": state, "completed": state == "post"}},
        "competitors": [{"homeAway": "away", "team": {"abbreviation": away}},
                        {"homeAway": "home", "team": {"abbreviation": home}}]}]}


LAST_NIGHT = {"events": [ev("1", "MTL", "WSH", "2026-10-14T23:30Z", "post")]}
TODAY = {"events": [ev("2", "BUF", "TOR", "2026-10-15T23:00Z")]}
TOMORROW = {"events": [ev("3", "PIT", "COL", "2026-10-17T01:00Z")]}


def fake_get(url):
    if url.endswith("?dates=20261015"):
        return TODAY
    if url.endswith("?dates=20261016"):
        return TOMORROW
    return LAST_NIGHT          # the default scoreboard hasn't rolled over yet


class MorningSlate(unittest.TestCase):
    def setUp(self):
        N.SB_GAMES.clear()
        N.STARTED.clear()

    def run_slate(self):
        with mock.patch.object(N, "get_json", side_effect=fake_get), mock.patch.object(N, "ET_TODAY", "2026-10-15"):
            return N.fetch_slate()

    def test_today_from_the_dated_scoreboard(self):
        games = self.run_slate()
        self.assertEqual([(g["away"], g["home"]) for g in games], [("BUF", "TOR")])   # not tomorrow's game

    def test_picks_today_and_tomorrow_get_start_times(self):
        self.run_slate()
        picks = [{"gid": "2026-10-15-BUF-TOR", "res": None}, {"gid": "2026-10-16-PIT-COL", "res": None},
                 {"gid": "2026-10-15-BUF-TOR", "res": "hit"}]
        N.stamp_starts(picks)
        self.assertEqual(picks[0]["start"], "2026-10-15T23:00Z")
        self.assertEqual(picks[1]["start"], "2026-10-17T01:00Z")
        self.assertNotIn("start", picks[2])        # graded picks are left alone


if __name__ == "__main__":
    unittest.main()

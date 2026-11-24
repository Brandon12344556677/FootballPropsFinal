"""All-Star weekend and other exhibitions are kept out of the NBA game store (build_nba)."""
import unittest

import build_nba as N


def row(team, opp):
    return {"team": team, "opp": opp, "date": "2026-02-15", "gid": "1"}


class TestExhibitions(unittest.TestCase):
    def test_thirty_teams(self):
        self.assertEqual(len(N.ESPN_NBA_TEAMS), 30)

    def test_nba_game(self):
        self.assertTrue(N.nba_game("BOS", "NY"))
        self.assertTrue(N.nba_game("UTAH", "GS"))
        self.assertFalse(N.nba_game("STARS", "STRIPES"))
        self.assertFalse(N.nba_game("WORLD", "BOS"))
        self.assertFalse(N.nba_game("BOS", None))

    def test_drop_exhibitions(self):
        store = {"rows": [row("DEN", "STARS"), row("STRIPES", "WORLD"), row("DEN", "LAL"), row("SA", "OKC")]}
        self.assertEqual(N.drop_exhibitions(store), 2)
        self.assertEqual([(r["team"], r["opp"]) for r in store["rows"]], [("DEN", "LAL"), ("SA", "OKC")])

    def test_drop_exhibitions_empty(self):
        store = {}
        self.assertEqual(N.drop_exhibitions(store), 0)
        self.assertEqual(store["rows"], [])


if __name__ == "__main__":
    unittest.main()

"""Tests for build_games.py: game ids, the board's tags, the per-team table, page names."""
import datetime
import unittest

import build_games as G

UTC = datetime.timezone.utc


class Teams(unittest.TestCase):
    def test_nfl_id_and_schedule(self):
        self.assertEqual(G.teams_of("nfl", "2026_05_LV_NE", {}), ("LV", "NE"))
        db = {"week": {"games": [{"id": "2026_05_LV_NE", "away": "LV", "home": "NE"}]}}
        self.assertEqual(G.teams_of("nfl", "2026_05_LV_NE", db), ("LV", "NE"))

    def test_other_sports_date_away_home(self):
        self.assertEqual(G.teams_of("nhl", "2026-10-11-SEA-WSH", {}), ("SEA", "WSH"))
        self.assertEqual(G.teams_of("mlb", "bad-id", {}), (None, None))


class Tags(unittest.TestCase):
    def test_board_lists_win_and_unlisted_is_never_value(self):
        self.assertEqual(G.board_tag("V", 0.6, 0.4), ("Value", "value"))
        self.assertEqual(G.board_tag("T", 0.95, 0.9), ("Top 25", "t25"))
        self.assertEqual(G.board_tag("", 0.7, 0.4)[1], "fair")     # the price rule says value, the board didn't list it
        self.assertEqual(G.board_tag("", 0.5, None)[1], "none")


def prop(pid, team, stat, side, prob, cls="fair", edge=None):
    return {"pid": pid, "player": pid, "team": team, "stat": stat, "statText": stat, "line": 1.5, "side": side,
            "prob": prob, "price": None, "edge": edge, "verdict": "", "cls": cls}


class ByTeam(unittest.TestCase):
    def test_one_line_per_stat_side_value_first(self):
        props = [prop("a", "LV", "rec", "under", 0.9), prop("a", "LV", "rec", "under", 0.55),
                 prop("a", "LV", "yds", "over", 0.6), prop("b", "LV", "rec", "over", 0.7, cls="value", edge=0.2),
                 prop("c", "NE", "rec", "over", 0.7)]
        rows = G.by_team(props, "LV")
        self.assertEqual([lst[0]["pid"] for lst in rows], ["b", "a"])          # the Value player first
        self.assertEqual(sorted(c["prob"] for c in rows[1]), [0.55, 0.6])      # rec under kept closest to 50%


class Names(unittest.TestCase):
    def test_slug_and_time(self):
        start = datetime.datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
        g = {"away": "LV", "home": "NE", "start": start}
        self.assertEqual(G.page_slug(g), "lv-at-ne-2026-10-11")
        self.assertEqual(G.when(start), "Sun, Oct 11, 1:00 PM ET")
        self.assertEqual(G.when(start, timed=False), "Sun, Oct 11, time TBA")


class GameProps(unittest.TestCase):
    def test_upcoming_only_with_date_fallback(self):
        now = datetime.datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
        cols = ["src", "gid", "pid", "player", "team", "stat", "line", "side", "prob", "price", "lists", "res", "start"]
        rows = [["live", "2026-10-11-SEA-WSH", "1", "A", "WSH", "g", 0.5, "under", 0.8, 0.7, "", None, None],          # no start: date fallback
                ["live", "2026-10-10-SEA-WSH", "2", "B", "WSH", "g", 0.5, "under", 0.8, 0.7, "", None, "2026-10-10T23:00Z"],  # started
                ["live", "2026-10-11-SEA-WSH", "3", "C", "SEA", "g", 0.5, "under", 0.8, 0.7, "", "hit", None]]          # graded
        games = G.game_props("nhl", {}, {"cols": cols, "picks": rows}, {"g": "Goals"}, now)
        self.assertEqual(list(games), ["2026-10-11-SEA-WSH"])
        g = games["2026-10-11-SEA-WSH"]
        self.assertFalse(g["timed"])
        self.assertEqual([c["pid"] for c in g["props"]], ["1"])


if __name__ == "__main__":
    unittest.main()

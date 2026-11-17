"""slim.py: the slim player data baked into the NHL/NBA/MLB pages."""
import copy
import datetime
import json
import os
import re
import unittest

import slim

TODAY = datetime.date(2026, 11, 17)


def _db():
    return {"gen": "2026-11-17", "sport": "nhl", "season": 2026, "week": {"games": []},
            "defense": {"BOS": {}}, "record": {"T": {"n": 3, "hit": 2}},
            "players": [
                {"id": "1", "n": "Has Pick", "p": "C", "t": "BOS", "g": [[2026, "2026-11-10"], [2026, "2026-11-12"]]},
                {"id": "2", "n": "No Pick", "p": "D", "t": "NYR", "g": [[2026, "2026-11-10"], [2026, "2026-11-11"], [2026, "2026-11-13"]]},
                {"id": 3, "n": "Number Id", "p": "G", "t": "TOR", "g": [[2026, "2026-11-10"]]},
                {"id": "4", "n": "No Games", "p": "LW", "t": "BOS", "g": []},
                {"id": "5", "n": "Graded Only", "p": "RW", "t": "MTL", "g": [[2026, "2026-11-10"]]},
                {"id": "6", "n": "Stale Pending", "p": "RW", "t": "MTL", "g": [[2026, "2026-11-01"]]},
            ]}


def _picks():
    return [
        {"pid": "1", "date": "2026-11-17", "res": None, "lists": "V"},               # today, pending, Value
        {"pid": 3, "date": "2026-11-18", "res": None, "lk": "x", "lists": "T"},     # tomorrow, locked: still on the boards
        {"pid": "2", "date": "2026-11-17", "res": None, "lists": ""},                # a board pick on no list
        {"pid": "2", "date": "2026-11-17", "res": None},
        {"pid": "5", "date": "2026-11-16", "res": "hit", "lists": "T"},              # graded
        {"pid": "6", "date": "2026-11-01", "res": None, "lists": "V"},               # an ungraded leftover
        {"pid": None, "date": "2026-11-17", "res": None, "lists": "V"},
    ]


class KeepIds(unittest.TestCase):
    def test_pending_picks_keep_their_players(self):
        self.assertEqual(slim.keep_ids(_picks(), TODAY), {"1", "3"})

    def test_yesterday_still_counts(self):
        self.assertEqual(slim.keep_ids([{"pid": "9", "date": "2026-11-15", "res": None, "lists": "T"}], TODAY), {"9"})
        self.assertEqual(slim.keep_ids([{"pid": "9", "date": "2026-11-14", "res": None, "lists": "T"}], TODAY), set())

    def test_no_date_counts(self):
        self.assertEqual(slim.keep_ids([{"pid": "9", "res": None, "lists": "V"}], TODAY), {"9"})

    def test_nothing(self):
        self.assertEqual(slim.keep_ids([], TODAY), set())
        self.assertEqual(slim.keep_ids(None, TODAY), set())


class SlimDb(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        self.before = copy.deepcopy(self.db)
        self.out = slim.slim_db(self.db, slim.keep_ids(_picks(), TODAY), "nhl.json")
        self.by = {str(p["id"]): p for p in self.out["players"]}

    def test_kept_players_are_unchanged(self):
        self.assertEqual(self.by["1"], self.before["players"][0])
        self.assertEqual(self.by["3"], self.before["players"][2])
        self.assertNotIn("lazy", self.by["1"])

    def test_other_players_are_lazy(self):
        for pid, n in (("2", 3), ("5", 1), ("6", 1)):
            p = self.by[pid]
            self.assertEqual(p["g"], [])
            self.assertEqual(p["lazy"], 1)
            self.assertEqual(p["gn"], n)
            self.assertEqual(set(p), {"id", "n", "p", "t", "g", "lazy", "gn"})
        self.assertEqual(self.by["2"]["n"], "No Pick")
        self.assertEqual(self.by["2"]["t"], "NYR")
        self.assertEqual(self.by["2"]["p"], "D")

    def test_players_without_games_are_not_flagged(self):
        self.assertEqual(self.by["4"], self.before["players"][3])

    def test_every_player_and_order_kept(self):
        self.assertEqual([p["id"] for p in self.out["players"]], [p["id"] for p in self.before["players"]])

    def test_top_level(self):
        self.assertEqual(self.out["full"], "nhl.json")
        self.assertIs(self.out["slim"], True)
        for k in self.before:
            if k != "players":
                self.assertEqual(self.out[k], self.before[k])

    def test_full_db_untouched(self):
        self.assertEqual(self.db, self.before)
        self.assertNotIn("full", self.db)
        self.assertNotIn("slim", self.db)


class PagePayload(unittest.TestCase):
    def test_json(self):
        db = _db()
        before = copy.deepcopy(db)
        d = json.loads(slim.page_payload(db, _picks(), "nhl.json", TODAY))
        self.assertTrue(d["slim"])
        self.assertEqual(sum(1 for p in d["players"] if p.get("lazy")), 3)
        self.assertEqual(db, before)

    def test_falls_back_to_full(self):
        db = {"players": [{"id": "1", "n": "x", "p": "C", "t": "BOS", "g": 5}]}   # bad shape: len() fails
        d = json.loads(slim.page_payload(db, [], "nhl.json", TODAY))
        self.assertEqual(d, db)


class Templates(unittest.TestCase):
    """Each board template waits on ensureFull() wherever it reads a lazy player's logs."""
    def test_gates(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for sport in ("nhl", "nba", "mlb"):
            with open(os.path.join(here, f"{sport}_template.html"), encoding="utf-8") as f:
                s = f.read()
            with self.subTest(sport=sport):
                self.assertIn("function ensureFull()", s)
                self.assertIn("fetch('./'+DB.full, {cache:'no-cache'})", s)
                self.assertIn("if(p.lazy){", s)                              # render()
                self.assertIn("if(!p || !st || p.lazy) return null;", s)      # betResult: never void a bet on a lazy player
                self.assertIn("function buildLeaderboard(){\n  if(!FULL_OK)", s)
                self.assertNotIn("cache:'no-store'", s)
                self.assertIsNone(re.search(r"NAME_INDEX=DB\.players\.filter\(p=>p\.g", s))   # lazy players stay searchable
                with open(os.path.join(here, f"build_{sport}.py"), encoding="utf-8") as f:
                    builder = f.read()
                self.assertIn("slim.page_payload(db, picks, DATA_FILE, TODAY)", builder)


if __name__ == "__main__":
    unittest.main()

"""Tests for botd.py (the home page's Bet of the Day).

Run:  python -m unittest test_botd -v
"""
import datetime
import unittest
from zoneinfo import ZoneInfo

import botd

ET = ZoneInfo("America/New_York")


def at(h, m=0, day=1):
    """A UTC datetime for h:m ET on 2026-10-<day>."""
    return datetime.datetime(2026, 10, day, h, m, tzinfo=ET).astimezone(datetime.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def cand(pid, prob, price, start=None, sport="nhl", **kw):
    c = {"sport": sport, "pid": pid, "player": f"P{pid}", "team": "AAA", "opp": "BBB", "gid": f"g{pid}",
         "stat": "pts", "statText": "Points", "line": 1.5, "side": "under", "prob": prob, "price": price,
         "start": iso(start or at(19)), "l10": [], "neff": 12.0, "flag": None}
    c.update(kw)
    return c


def picks_doc(rows):
    cols = ["src", "gid", "date", "pid", "stat", "line", "side", "prob", "price", "res", "actual"]
    return {"cols": cols, "picks": [[r.get(k) for k in cols] for r in rows]}


class ChooseTests(unittest.TestCase):
    def test_lock_wants_both_chances_high(self):
        cs = [cand(1, 0.99, 0.90), cand(2, 0.94, 0.95), cand(3, 0.99, 0.97), cand(4, 0.88, 0.95), cand(5, 0.99, 0.85)]
        # 1: min .90; 2: min .94 -> best; 3: price above 96c; 4: model under 90%; 5: price under 90c
        self.assertEqual(botd.choose(cs, "lock", at(11))["pid"], 2)

    def test_value_shot_window(self):
        cs = [cand(1, 0.72, 0.45), cand(2, 0.79, 0.48), cand(3, 0.85, 0.40), cand(4, 0.75, 0.55), cand(5, 0.78, 0.25)]
        self.assertEqual(botd.choose(cs, "value", at(11))["pid"], 2)   # 3: model too high; 4, 5: price out

    def test_filters(self):
        now = at(11)
        self.assertIsNone(botd.choose([cand(1, 0.95, 0.92, flag="Questionable")], "lock", now))
        self.assertIsNone(botd.choose([cand(1, 0.95, 0.92, neff=4.0)], "lock", now))
        self.assertIsNone(botd.choose([cand(1, 0.95, 0.92, start=at(11, 30))], "lock", now))      # starts in 30 min
        self.assertIsNone(botd.choose([cand(1, 0.95, 0.92, start=at(19, day=2))], "lock", now))   # tomorrow
        self.assertIsNone(botd.choose([cand(1, 0.95, 0.92)], "lock", now, taken={("nhl", "1")}))
        late = at(23, 30) + datetime.timedelta(minutes=10)    # 11:40 PM ET is still Oct 1 in ET
        self.assertIsNotNone(botd.choose([cand(1, 0.95, 0.92, start=late)], "lock", now))


class NewsFlagTests(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(botd.news_flag("nba", {"st": "Day-To-Day"}), "Day-To-Day")
        self.assertEqual(botd.news_flag("mlb", {"lu": 0}), "not in the posted lineup")
        self.assertIsNone(botd.news_flag("mlb", {"lu": 3}))
        self.assertIsNone(botd.news_flag("nhl", None))
        wr = {"inj": ["", "Hamstring", "LP", 4]}
        self.assertEqual(botd.news_flag("nfl", {}, wr, 4), "practice: LP")
        self.assertIsNone(botd.news_flag("nfl", {}, wr, 5))                        # last week's report
        self.assertEqual(botd.news_flag("nfl", {}, {"inj": ["Doubtful", "Knee", "DNP", 4]}, 4), "Doubtful")
        self.assertEqual(botd.news_flag("nfl", {}, {"st": "RES"}, 4), "roster status RES")
        self.assertIsNone(botd.news_flag("nfl", {}, {"inj": ["", "", "FP", 4]}, 4))


class UpdateTests(unittest.TestCase):
    def test_posts_at_11_never_swaps_and_closes(self):
        doc = botd.update({}, [cand(1, 0.95, 0.92)], [], at(10, 55))
        self.assertEqual(doc["days"], [])                                        # before 11 AM ET
        doc = botd.update(doc, [cand(1, 0.95, 0.92)], [], at(11, 5))
        self.assertEqual(doc["days"][0]["lock"]["pid"], 1)
        self.assertIsNone(doc["days"][0]["value"])
        better = [cand(2, 0.97, 0.95), cand(1, 0.95, 0.90), cand(3, 0.75, 0.45)]
        doc = botd.update(doc, better, [], at(14))
        self.assertEqual(doc["days"][0]["lock"]["pid"], 1)                       # locked: never swapped
        self.assertEqual(doc["days"][0]["lock"]["price"], 0.92)                  # at the price it posted at
        self.assertEqual(doc["days"][0]["value"]["pid"], 3)                      # an empty slot still fills
        self.assertFalse(doc["days"][0]["closed"])

    def test_empty_slot_closes_at_7_30(self):
        doc = botd.update({}, [], [], at(19, 35))
        self.assertTrue(doc["days"][0]["closed"])
        doc = botd.update(doc, [cand(1, 0.95, 0.92, start=at(22))], [], at(20))
        self.assertIsNone(doc["days"][0]["lock"])                               # no late picks once closed

    def test_two_different_players(self):
        cs = [cand(1, 0.95, 0.92), cand(1, 0.75, 0.45, stat="g")]
        doc = botd.update({}, cs, [], at(11))
        self.assertEqual(doc["days"][0]["lock"]["pid"], 1)
        self.assertIsNone(doc["days"][0]["value"])


class GradeTests(unittest.TestCase):
    def test_grading_and_record(self):
        doc = botd.update({}, [cand(1, 0.95, 0.90), cand(2, 0.75, 0.40, side="over", line=0.5)], [], at(11))
        rows = [{"src": "live", "gid": "g1", "date": "2026-10-01", "pid": 1, "stat": "pts", "line": 1.5, "side": "under", "res": "hit", "actual": 1},
                {"src": "live", "gid": "g2-other-date", "date": "2026-10-02", "pid": 2, "stat": "pts", "line": 0.5, "side": "over", "res": "miss", "actual": 0}]
        doc = botd.update(doc, [], [("nhl", picks_doc(rows))], at(9, day=2))
        d = doc["days"][0]
        self.assertTrue(d["closed"])
        self.assertEqual((d["lock"]["res"], d["lock"]["actual"]), ("hit", 1))
        self.assertEqual(d["value"]["res"], "miss")                              # matched a day either side
        self.assertEqual(doc["record"]["lock"], {"n": 1, "hit": 1, "miss": 0, "push": 0, "void": 0, "units": 0.11, "last": ["hit"]})
        self.assertEqual(doc["record"]["value"]["units"], -1.0)

    def test_dnp_and_stale_are_voids(self):
        doc = botd.update({}, [cand(1, 0.95, 0.90)], [], at(11))
        rows = [{"src": "live", "gid": "g1", "date": "2026-10-01", "pid": 1, "stat": "pts", "line": 1.5, "side": "under", "res": "dnp"}]
        doc = botd.update(doc, [], [("nhl", picks_doc(rows))], at(9, day=2))
        self.assertEqual(doc["days"][0]["lock"]["res"], "void")
        self.assertEqual(doc["record"]["lock"]["n"], 0)
        doc = botd.update({}, [cand(1, 0.95, 0.90)], [], at(11))
        doc = botd.update(doc, [], [], at(12, day=4))
        self.assertIsNone(doc["days"][0]["lock"]["res"])                         # 3 days: still waiting
        doc = botd.update(doc, [], [], at(12, day=7))
        self.assertEqual(doc["days"][0]["lock"]["res"], "void")

    def test_history_base_rate(self):
        rows = [{"src": "live", "pid": 1, "stat": "pts", "line": 1.5, "side": "under", "prob": 0.93, "price": 0.92, "res": "hit"},
                {"src": "live", "pid": 2, "stat": "pts", "line": 1.5, "side": "under", "prob": 0.93, "price": 0.85, "res": "hit"},
                {"src": "bt", "pid": 3, "stat": "pts", "line": 1.5, "side": "under", "prob": 0.93, "price": 0.92, "res": "miss"}]
        nfl = [{"src": "live", "pid": 4, "stat": "rec", "line": 4.5, "side": "over", "prob": 0.74, "price": 45, "res": "miss"}]
        h = botd.history([("nhl", picks_doc(rows)), ("nfl", picks_doc(nfl))])
        self.assertEqual(h, {"lock": {"n": 1, "hit": 1}, "value": {"n": 1, "hit": 0}})   # NFL prices are cents


if __name__ == "__main__":
    unittest.main()

"""Tests for props that wait on injury news (holds.py and each builder's injury_holds).

Run:  python -m unittest test_holds -v
"""
import unittest
from unittest import mock

import holds
import build_mlb
import build_nba
import build_nhl

FUTURE = "2099-01-01T00:00Z"


def pick(pid, player, pos, team, stat="pts", **kw):
    p = {"pid": pid, "player": player, "pos": pos, "team": team, "stat": stat, "res": None, "start": FUTURE,
         "date": "2099-01-01", "gid": "g1", "prob": 0.95, "price": 0.40, "neff": 9, "lists": "", "th": None}
    p.update(kw)
    return p


class Status(unittest.TestCase):
    def test_words(self):
        for text, want in (("Questionable", "unsure"), ("Doubtful", "unsure"), ("Day-To-Day", "unsure"),
                           ("Out", "out"), ("Injured Reserve", "out"), ("60-Day-IL", "out"), ("10-Day-IL", "out"),
                           ("suspension", "out"), ("paternity", "out"), ("Active", None), ("", None), (None, None)):
            self.assertEqual(holds.status(text), want, text)

    def test_label(self):
        self.assertEqual(holds.label("Day-To-Day"), "day-to-day")
        self.assertEqual(holds.label("Injured Reserve"), "out")


class Apply(unittest.TestCase):
    people = {"star": ("Star Guard", "BOS", "G"), "g2": ("Other Guard", "BOS", "PG"), "f1": ("A Forward", "BOS", "F"),
              "bench": ("Bench Guard", "BOS", "G"), "opp": ("Rival Guard", "NY", "G")}
    groups = staticmethod(lambda pos: {c for c in "GFC" if c in pos})
    role = staticmethod(lambda pid: pid != "bench")
    is_open = staticmethod(lambda p: True)

    def picks(self):
        return [pick("star", "Star Guard", "G", "BOS"), pick("g2", "Other Guard", "PG", "BOS"),
                pick("f1", "A Forward", "F", "BOS"), pick("opp", "Rival Guard", "G", "NY")]

    def test_day_to_day_regular_holds_his_group(self):
        ps = self.picks()
        n = holds.apply(ps, {"star": "Day-To-Day"}, self.people, self.groups, self.role, self.is_open)
        self.assertEqual(n, 2)
        self.assertEqual([p["hd"] for p in ps], ["Star Guard (day-to-day)", "Star Guard (day-to-day)", None, None])

    def test_no_real_role_holds_only_himself(self):
        ps = self.picks() + [pick("bench", "Bench Guard", "G", "BOS")]
        holds.apply(ps, {"bench": "Day-To-Day"}, self.people, self.groups, self.role, self.is_open)
        self.assertEqual([p["hd"] for p in ps], [None, None, None, None, "Bench Guard (day-to-day)"])

    def test_out_holds_only_himself(self):
        ps = self.picks()
        holds.apply(ps, {"star": "Out"}, self.people, self.groups, self.role, self.is_open)
        self.assertEqual([p["hd"] for p in ps], ["Star Guard (out)", None, None, None])

    def test_settled_news_lifts_it(self):
        ps = self.picks()
        holds.apply(ps, {"star": "Day-To-Day"}, self.people, self.groups, self.role, self.is_open,
                    settled=lambda pid, p: "in" if pid == "star" else None)
        self.assertEqual([p["hd"] for p in ps], [None, None, None, None])

    def test_locked_picks_keep_what_they_had(self):
        ps = self.picks()
        ps[1]["hd"] = "earlier"
        holds.apply(ps, {}, self.people, self.groups, self.role, lambda p: p["pid"] != "g2")
        self.assertEqual(ps[1]["hd"], "earlier")
        self.assertIsNone(ps[0]["hd"])

    def test_match_by_id_then_unique_name(self):
        rep = holds.match([{"id": "star", "name": "x", "status": "Out"}, {"id": "999", "name": "A Forward", "status": "Day-To-Day"}],
                          self.people, str.lower)
        self.assertEqual(rep, {"star": "Out", "f1": "Day-To-Day"})


def rows(pid, team, n, **stat):
    return [dict({"pid": pid, "team": team, "date": f"2099-0{1 + i // 9}-{10 + i % 9}"}, **stat) for i in range(n)]


class Builders(unittest.TestCase):
    def test_nba(self):
        by_pid = {"a": {"n": "Star Guard", "t": "BOS", "p": "G"}, "b": {"n": "Other Guard", "t": "BOS", "p": "G"},
                  "c": {"n": "Big Man", "t": "BOS", "p": "C"}}
        box = rows("a", "BOS", 5, min=34) + rows("b", "BOS", 5, min=25) + rows("c", "BOS", 5, min=28)
        ps = [pick("b", "Other Guard", "G", "BOS"), pick("c", "Big Man", "C", "BOS")]
        with mock.patch.object(build_nba.news, "espn_injuries", return_value=[{"id": "a", "name": "Star Guard", "status": "Day-To-Day"}]):
            build_nba.injury_holds(ps, by_pid, box)
        self.assertEqual([p["hd"] for p in ps], ["Star Guard (day-to-day)", None])
        build_nba.assign_lists(ps)
        self.assertEqual([p["lists"] for p in ps], ["", "TV"])

    def test_nhl_goalie(self):
        by_pid = {"g1": {"n": "Starter", "t": "BOS", "p": "G"}, "g2": {"n": "Backup", "t": "BOS", "p": "G"},
                  "f": {"n": "Winger", "t": "BOS", "p": "LW"}}
        box = rows("g1", "BOS", 5, started=1, toi=60) + rows("g2", "BOS", 2, started=0, toi=20) + rows("f", "BOS", 5, toi=17)
        ps = [pick("g2", "Backup", "G", "BOS", stat="sv"), pick("f", "Winger", "LW", "BOS", stat="sog")]
        with mock.patch.object(build_nhl.news, "espn_injuries", return_value=[{"id": "g1", "name": "Starter", "status": "Day-To-Day"}]):
            build_nhl.injury_holds(ps, by_pid, box)
        self.assertEqual([p["hd"] for p in ps], ["Starter (day-to-day)", None])
        build_nhl.assign_lists(ps)
        self.assertEqual([p["lists"] for p in ps], ["", "TV"])

    def test_feed_down_keeps_last_holds(self):
        ps = [pick("b", "Other Guard", "G", "BOS", hd="Star Guard (day-to-day)")]
        with mock.patch.object(build_nba.news, "espn_injuries", return_value=None):
            build_nba.injury_holds(ps, {}, [])
        self.assertEqual(ps[0]["hd"], "Star Guard (day-to-day)")

    def mlb(self, lineup):
        by_pid = {"h1": {"n": "Regular Hitter", "t": "NYY", "p": "RF"}, "h2": {"n": "Other Hitter", "t": "NYY", "p": "1B"},
                  "sp": {"n": "Ace Pitcher", "t": "NYY", "p": "SP"}}
        box = rows("h1", "NYY", 5, bat=2) + rows("h2", "NYY", 5, bat=2) + rows("sp", "NYY", 2, bat=0, pit=1)
        ps = [pick("h2", "Other Hitter", "1B", "NYY", stat="h"), pick("sp", "Ace Pitcher", "SP", "NYY", stat="k")]
        lu = {"2099-01-01": {"NYY": lineup}} if lineup is not None else {}
        with mock.patch.object(build_mlb.news, "espn_injuries", return_value=[{"id": "h1", "name": "Regular Hitter", "status": "Day-To-Day"}]), \
                mock.patch.object(build_mlb.news, "mlb_lineups", return_value=lu):
            build_mlb.injury_holds(ps, by_pid, box)
        return ps

    def test_mlb_waits_for_the_lineup(self):
        ps = self.mlb(None)
        self.assertEqual([p["hd"] for p in ps], ["Regular Hitter (day-to-day)", None])   # a pitcher isn't in the lineup group

    def test_mlb_lineup_settles_it(self):
        ps = self.mlb(["regular hitter", "other hitter"])
        self.assertEqual([p["hd"] for p in ps], [None, None])
        ps = self.mlb(["regular hitter"])                      # posted without him: he isn't playing
        self.assertEqual([p["hd"] for p in ps], ["Other Hitter (not in the lineup)", None])


if __name__ == "__main__":
    unittest.main()

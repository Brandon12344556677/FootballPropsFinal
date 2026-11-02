"""Tests for build_tennis.py: the scoreline model, ESPN parsing, grading and the list rules."""
import datetime
import unittest

import build_tennis as T


def comp(pid, order, sets, winner, tb=None):
    ls = [{"value": float(g)} for g in sets]
    return {"id": pid, "type": "athlete", "order": order, "winner": winner, "linescores": ls,
            "athlete": {"displayName": f"Player {pid}"}}


def board(group, comps, status="STATUS_FINAL", state="post", major=False, name="Some Open", date="2026-03-02T10:00Z"):
    return {"events": [{"id": "9", "name": name, "date": date, "major": major, "groupings": [
        {"grouping": {"displayName": group}, "competitions": [
            {"id": "111", "date": date, "status": {"type": {"name": status, "state": state}},
             "round": {"displayName": "Round 1"}, "competitors": comps}]}]}]}


class ModelTest(unittest.TestCase):
    def test_even_match_is_a_coin_flip(self):
        pm = T.price_match(0.5, "atp", "hard", 3)
        self.assertAlmostEqual(pm["win"], 0.5, places=3)
        self.assertAlmostEqual(sum(pm["games"].values()), 1.0, places=6)
        self.assertAlmostEqual(sum(pm["spread"].values()), 1.0, places=6)

    def test_chain_reproduces_the_rating_chance(self):
        for p in (0.2, 0.65, 0.9):
            self.assertAlmostEqual(T.price_match(p, "wta", "clay", 3)["win"], p, delta=0.005)

    def test_best_of_five_stretches_the_favorite(self):
        self.assertGreater(T.price_match(0.65, "atp", "hard", 5)["win"], 0.66)

    def test_set_outcomes_agree_with_the_match(self):
        pm = T.price_match(0.7, "atp", "clay", 3)
        self.assertAlmostEqual(sum(pm["exact"].values()), 1.0, places=6)
        self.assertAlmostEqual(sum(q for (a, b), q in pm["exact"].items() if a > b), pm["win"], places=4)
        # set 3 is played only in a 2-1 match, and someone wins it then
        played3 = pm["exact"][(2, 1)] + pm["exact"][(1, 2)]
        self.assertAlmostEqual(pm["set"][2] + T.set_lost(pm, 3, 3), played3, places=6)
        self.assertAlmostEqual(pm["set"][0] + T.set_lost(pm, 1, 3), 1.0, places=6)

    def test_over_chance_and_cover(self):
        pm = T.price_match(0.6, "wta", "hard", 3)
        self.assertGreater(T.over_chance(pm["games"], 15.5), T.over_chance(pm["games"], 25.5))
        self.assertAlmostEqual(T.cover_chance(pm["spread"], 0.5) + T.cover_chance({-d: q for d, q in pm["spread"].items()}, -0.5), 1.0, places=6)

    def test_surface(self):
        self.assertEqual(T.surface("Roland Garros", "2026-05-24"), "clay")
        self.assertEqual(T.surface("Wimbledon", "2026-06-29"), "grass")
        self.assertEqual(T.surface("Porsche Tennis Grand Prix", "2026-04-13"), "clay")
        self.assertEqual(T.surface("Boss Open", "2026-06-08"), "grass")
        self.assertEqual(T.surface("Rolex Paris Masters", "2026-10-31"), "hard")


class ParseTest(unittest.TestCase):
    def test_final_and_combined_event_tour(self):
        doc = board("Women's Singles", [comp("1", 1, [6, 6], True), comp("2", 2, [3, 4], False)], major=True)
        rows, names, up, _ = T.parse_scoreboard(doc, "atp")       # read from the ATP feed, but a women's draw
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r[1], r[4], r[6], r[7], r[8], r[9], r[10]), ("wta", 3, "1", "2", 1, [[6, 3], [6, 4]], "F"))
        self.assertEqual(names["2"], "Player 2")

    def test_mens_slam_is_best_of_five(self):
        doc = board("Men's Singles", [comp("1", 1, [6, 6, 6], True), comp("2", 2, [3, 4, 2], False)], major=True)
        self.assertEqual(T.parse_scoreboard(doc, "atp")[0][0][4], 5)

    def test_retirement_walkover_and_doubles(self):
        ret = board("Men's Singles", [comp("1", 1, [6, 2], True), comp("2", 2, [3, 1], False)], status="STATUS_RETIRED")
        self.assertEqual(T.parse_scoreboard(ret, "atp")[0][0][10], "R")
        wo = board("Men's Singles", [comp("1", 1, [], True), comp("2", 2, [], False)])
        self.assertEqual(T.parse_scoreboard(wo, "atp")[0], [])
        self.assertEqual(T.parse_scoreboard(wo, "atp")[3], ["111"])            # gone: its picks void at once
        dbl = board("Men's Doubles", [comp("1", 1, [6, 6], True), comp("2", 2, [3, 4], False)])
        self.assertEqual(T.parse_scoreboard(dbl, "atp")[0], [])

    def test_upcoming(self):
        doc = board("Men's Singles", [comp("1", 1, [], False), comp("2", 2, [], False)], status="STATUS_SCHEDULED", state="pre")
        rows, _, up, _ = T.parse_scoreboard(doc, "atp")
        self.assertEqual(rows, [])
        self.assertEqual((up[0]["mid"], up[0]["p1"], up[0]["p2"], up[0]["tv"]), ("111", "1", "2", True))
        doc["events"][0]["groupings"][0]["competitions"][0]["timeValid"] = False
        self.assertFalse(T.parse_scoreboard(doc, "atp")[2][0]["tv"])           # ESPN's placeholder time
        doc["events"][0]["name"] = "Next Gen ATP Finals"
        self.assertEqual(T.parse_scoreboard(doc, "atp")[2], [])                # first-to-4 sets: never priced

    def test_kalshi_tickers(self):
        m = T.KX_EVENT.match("KXATPSETWINNER-26NOV03RUUJOD-2")
        self.assertEqual(m.groups(), ("26NOV03", "RUUJOD", "2"))
        self.assertEqual(T.KX_EVENT.match("KXATPMATCH-26NOV03SHENOR").group(3), None)
        self.assertEqual(T.KX_EXACT.match("Casper Ruud wins 2-1").groups(), ("Casper Ruud", "2", "1"))
        self.assertEqual(T.KX_SPREAD.match("Ben Shelton -6.5 games").groups(), ("Ben Shelton", "6.5"))
        self.assertTrue(T.same_player("Botic van de Zandschulp", "Botic Van De Zandschulp"))
        self.assertTrue(T.same_player("Alex de Minaur", "Alexander de Minaur"))


def row(sets, win=1, status="F", mid="111"):
    return ["2026-03-02", "atp", "9", "hard", 3, "Round 1", "1", "2", win, sets, status, mid, "2026-03-02T10:00Z"]


def pick(**kw):
    p = {"mid": "111", "pid": "1", "date": "2026-03-02", "stat": "ml", "line": 0.0, "side": "over", "res": None}
    p.update(kw)
    return p


class GradeTest(unittest.TestCase):
    def setUp(self):
        self.by = {"111": row([[6, 3], [4, 6], [7, 6]])}      # player 1 wins 2-1, 32 games, +2 games

    def g(self, **kw):
        p = pick(**kw)
        self.assertTrue(T.grade(p, self.by, "2026-03-03"))
        return p

    def test_match_winner(self):
        self.assertEqual(self.g()["res"], "hit")
        self.assertEqual(self.g(pid="2")["res"], "miss")
        self.assertEqual(self.g(pid="2")["score"], "3-6 6-4 6-7")

    def test_games_and_spread(self):
        self.assertEqual(self.g(stat="games", line=31.5, side="over")["res"], "hit")
        self.assertEqual(self.g(stat="games", line=31.5, side="under")["res"], "miss")
        self.assertEqual(self.g(stat="spread", line=-1.5)["res"], "hit")
        self.assertEqual(self.g(stat="spread", line=-2.5)["res"], "miss")
        self.assertEqual(self.g(stat="spread", pid="2", line=2.5)["res"], "hit")

    def test_sets_and_exact(self):
        self.assertEqual(self.g(stat="set", line=1.0)["res"], "hit")
        self.assertEqual(self.g(stat="set", line=2.0)["res"], "miss")
        self.assertEqual(self.g(stat="set", line=2.0, pid="2")["res"], "hit")
        self.assertEqual(self.g(stat="exact", line=2.1)["res"], "hit")
        self.assertEqual(self.g(stat="exact", line=2.0)["res"], "miss")
        self.by["111"] = row([[6, 3], [6, 4]])
        self.assertEqual(self.g(stat="set", line=3.0)["res"], "miss")       # never played: not won
        self.assertEqual(self.g(stat="exact", line=2.0)["res"], "hit")

    def test_retirement_settles_only_the_winner(self):
        self.by["111"] = row([[6, 3], [2, 1]], status="R")
        self.assertEqual(self.g()["res"], "hit")
        for st in ("games", "spread", "set", "exact"):
            self.assertEqual(self.g(stat=st, line=1.0)["res"], "dnp")

    def test_unplayed_match_voids_after_three_days(self):
        p = pick(mid="999")
        self.assertFalse(T.grade(p, self.by, "2026-03-05"))
        self.assertTrue(T.grade(p, self.by, "2026-03-06"))
        self.assertEqual(p["res"], "dnp")

    def test_walkover_and_36_hours(self):
        p = pick(mid="999")
        self.assertTrue(T.grade(p, self.by, "2026-03-02", gone={"999"}))
        self.assertEqual(p["res"], "dnp")
        utc = datetime.timezone.utc
        p = pick(mid="999", start="2026-03-02T10:00Z")
        self.assertFalse(T.grade(p, self.by, "2026-03-03", now=datetime.datetime(2026, 3, 3, 21, 0, tzinfo=utc)))
        self.assertTrue(T.grade(p, self.by, "2026-03-03", now=datetime.datetime(2026, 3, 3, 22, 1, tzinfo=utc)))
        self.assertEqual(p["res"], "dnp")


class ListTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 3, 2, 12, 0, tzinfo=datetime.timezone.utc)

    def p(self, **kw):
        base = {"mid": "1", "pid": "a", "stat": "ml", "line": 0.0, "side": "over", "res": None, "start": "2026-03-02T18:00Z",
                "prob": 0.6, "price": 0.5, "th": None, "lists": "", "tour": "atp", "n": 40, "on": 40}
        base.update(kw)
        return base

    def test_value_rules(self):
        ok = self.p()
        rules = [self.p(price=0.25, prob=0.4),         # under 30c
                 self.p(price=0.85, prob=0.95),        # over 80c
                 self.p(price=0.5, prob=0.55),         # edge under 8
                 self.p(price=0.4, prob=0.65),         # edge over 20
                 self.p(stat="games", line=20.5),      # not a match winner
                 self.p(th=1),                         # thin
                 self.p(tour="wta"),                   # WTA: lost money against Kalshi prices
                 self.p(on=29)]                        # a player with under 30 matches
        T.assign_lists([ok] + rules, self.NOW)
        self.assertEqual(ok["lists"], "V")
        self.assertTrue(all("V" not in r["lists"] for r in rules))

    def test_one_side_per_market(self):
        a, b = self.p(pid="a", prob=0.62), self.p(pid="b", prob=0.60, price=0.48)
        T.assign_lists([a, b], self.NOW)
        self.assertEqual((a["lists"], b["lists"]), ("V", ""))

    def test_top25_takes_any_market_and_counts_locked(self):
        held = [self.p(mid=str(i), lists="T", lk="2026-03-02T11:50Z", prob=0.95, price=0.93) for i in range(24)]
        new = [self.p(mid="x", stat="set", line=1.0, prob=0.93, price=0.9), self.p(mid="y", prob=0.91, price=0.9)]
        T.assign_lists(held + new, self.NOW)
        self.assertEqual([p["lists"] for p in new], ["T", ""])      # one place left: the higher chance
        self.assertTrue(all(p["lists"] == "T" for p in held))       # locked picks keep theirs
        thin = self.p(mid="z", prob=0.95, price=0.9, th=1)
        T.assign_lists([thin], self.NOW)
        self.assertEqual(thin["lists"], "")


class UpdateTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 3, 2, 12, 0, tzinfo=datetime.timezone.utc)

    def match(self, with_pm=True):
        m = {"mid": "7", "tour": "atp", "event": "Open", "round": "R1", "surface": "hard", "bo": 3, "p1": "a", "p2": "b",
             "names": {"a": "Al A", "b": "Bo B"}, "elo": {"a": 1700.0, "b": 1600.0}, "n": {"a": 50, "b": 50}, "start": "2026-03-02T18:00Z",
             "locked": False, "_price": T.price_match(0.64, "atp", "hard", 3), "_kx": None}
        if with_pm:
            m["_pm"] = {"slug": "s", "long": "Al A", "short": "Bo B",
                        "bk": {"ask": 0.50, "bid": 0.48, "over": 500.0, "under": 500.0}}
        return m

    def test_a_vanished_market_loses_its_price_and_list(self):
        picks = []
        T.update_picks(picks, [self.match()], None, None, [], {}, {}, self.NOW)
        al = next(p for p in picks if p["pid"] == "a" and p["stat"] == "ml")
        self.assertEqual((al["price"], al["lists"]), (0.5, "V"))
        T.update_picks(picks, [self.match(with_pm=False)], None, None, [], {}, {}, self.NOW)
        self.assertEqual((al["price"], al["pp"], al["lists"]), (None, None, ""))

    def test_an_earlier_start_locks_existing_picks(self):
        picks = []
        T.update_picks(picks, [self.match()], None, None, [], {}, {}, self.NOW)
        m = self.match()
        m["locked"] = True
        T.update_picks(picks, [m], None, None, [], {}, {}, self.NOW)
        self.assertTrue(all(p.get("lk") for p in picks))
        held = self.match()
        held["hold"] = True               # incomplete history: nothing is recorded, refreshed or locked
        fresh = []
        T.update_picks(fresh, [held], None, None, [], {}, {}, self.NOW)
        self.assertEqual(fresh, [])


class PrivateRuleTest(unittest.TestCase):
    def test_rules_with_no_sport_skip_tennis(self):
        import edge_report
        row = {"sport": "tennis", "day": "2026-11-03", "pr": 0.5, "win": True, "side": "over", "stat": "ml",
               "line": 0.0, "lists": "V", "p0": 0.5, "prob": 0.6, "pos": None}
        self.assertFalse(edge_report.rule_test({})(row))
        self.assertTrue(edge_report.rule_test({"sport": "tennis"})(row))
        self.assertTrue(edge_report.rule_test({})(dict(row, sport="nhl")))


if __name__ == "__main__":
    unittest.main()

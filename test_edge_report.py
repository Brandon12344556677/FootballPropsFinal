"""Tests for edge_report.py: which picks count, and the numbers per strategy."""
import unittest

import edge_report as E

COLS = ["src", "res", "price", "px0", "start", "date", "side", "stat", "line", "lists", "vn", "th"]


def doc(rows):
    return {"cols": COLS, "picks": [[r.get(c) for c in COLS] for r in rows]}


class Graded(unittest.TestCase):
    def test_only_live_results_with_believable_prices(self):
        rows = E.graded("nhl", doc([
            {"src": "live", "res": "hit", "price": 0.6, "px0": 0.55, "start": "2026-10-08T23:00:00Z"},
            {"src": "live", "res": "hit", "price": 0.02, "start": "2026-10-08T23:00:00Z"},              # too cheap to be real
            {"src": "live", "res": "hit", "price": 0.15, "px0": 0.6, "start": "2026-10-08T23:00:00Z"},  # 45c collapse
            {"src": "live", "res": None, "price": 0.6, "start": "2026-10-08T23:00:00Z"},
            {"src": "bt", "res": "hit", "price": 0.6, "start": "2026-10-08T23:00:00Z"},
            {"src": "live", "res": "push", "price": 0.6, "start": "2026-10-08T23:00:00Z"}]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["day"], "2026-10-08")
        # an Oct 7 Top 25 / Value pick the $25 depth rule never checked stays out, as on the NHL/MLB boards
        unchecked = {"src": "live", "res": "hit", "price": 0.6, "start": "2026-10-07T23:00:00Z", "date": "2026-10-07", "lists": "V"}
        self.assertEqual(E.graded("nhl", doc([unchecked])), [])
        self.assertEqual(len(E.graded("nhl", doc([dict(unchecked, vn="P")]))), 1)   # its depth was checked
        nfl = E.graded("nfl", doc([{"src": "live", "res": "miss", "price": 55, "date": "2026-10-05"}]))
        self.assertEqual((nfl[0]["pr"], nfl[0]["day"]), (0.55, "2026-10-05"))


class Summary(unittest.TestCase):
    def rows(self, wins, losses, pr=0.5, sport="mlb", side="under", day="2026-10-0{}"):
        out = []
        for i in range(wins + losses):
            out.append({"sport": sport, "day": day.format(i % 9 + 1), "pr": pr, "win": i < wins, "side": side,
                        "stat": "tb", "line": 1.5, "lists": ""})
        return out

    def test_roi_units_and_verdicts(self):
        import random
        s = E.summary(self.rows(70, 30), "2026-10-10", random.Random(1))
        self.assertEqual((s["n"], s["hit"], s["units"], s["roi"]), (100, 0.7, 40.0, 0.4))
        self.assertEqual(s["verdict"], "Edge holding")
        self.assertEqual(E.summary(self.rows(30, 70), "2026-10-10", random.Random(1))["verdict"], "Losing")
        self.assertIsNone(E.summary([], "2026-10-10", random.Random(1)))

    def test_nhl_preseason_left_out(self):
        rows = self.rows(5, 5, sport="nhl", day="2026-10-0{}")      # days Oct 1-9: preseason until Oct 7
        out = {s["key"]: s for s in E.build(rows, "2026-10-10")}
        self.assertEqual(out["all-nhl"]["n"], sum(1 for p in rows if p["day"] >= E.NHL_REGULAR))
        self.assertNotIn("nhl-value-reg", out)

    def test_nba_rows_wait_for_the_season(self):
        out = {s["key"]: s for s in E.build(self.rows(3, 3), "2026-10-10")}
        self.assertEqual((out["nba-value"]["n"], out["nba-value"]["verdict"]), (0, "Waiting for games"))
        self.assertIn("all-nba", out)
        self.assertNotIn("nhl-top", out)          # other sports without picks still don't show

    def test_strategies_pick_their_rows(self):
        out = {s["key"]: s for s in E.build(self.rows(6, 4) + self.rows(3, 7, side="over", pr=0.6), "2026-10-10")}
        self.assertNotIn("mlb-overs", out)
        self.assertNotIn("nhl-top", out)
        self.assertNotIn("unders", out)          # private rules aren't in the code any more

    def test_private_rules_from_the_encrypted_document(self):
        doc = {"items": [{"key": "a", "label": "MLB unders 50-65c", "sport": "mlb", "side": "under", "pmin": 0.5, "pmax": 0.65},
                         {"key": "b", "label": "MLB total bases under 1.5", "sport": "mlb", "side": "under", "stat": "tb", "line": 1.5}]}
        strategies = E.STRATEGIES + E.private_strategies(doc)
        out = {s["key"]: s for s in E.build(self.rows(6, 4) + self.rows(3, 7, side="over", pr=0.6), "2026-10-10", strategies=strategies)}
        self.assertEqual((out["private-a"]["n"], out["private-b"]["n"], out["private-all"]["n"]), (10, 10, 10))   # every private row is "private-..."
        self.assertEqual(E.private_strategies({"items": []}), [])

    def test_previous_day_numbers_leave_out_the_latest_day(self):
        rows = self.rows(4, 4, day="2026-10-0{}")          # days Oct 1-8
        rows += [{"sport": "mlb", "day": "2026-10-09", "pr": 0.5, "win": True, "side": "under",
                  "stat": "tb", "line": 1.5, "lists": ""} for _ in range(2)]   # two wins on the latest day
        s = {x["key"]: x for x in E.build(rows, "2026-10-10")}["all-mlb"]
        self.assertEqual(s["prev_day"], "2026-10-09")
        self.assertEqual((s["prev"]["n"], s["n"]), (8, 10))
        self.assertLess(s["prev"]["roi"], s["roi"])         # the two wins pushed the return up


class PickOfTheDay(unittest.TestCase):
    def test_value_shot_and_safe_pick_rows(self):
        pick = lambda res, price: {"res": res, "price": price, "side": "under", "stat": "tb", "line": 1.5}
        doc = {"days": [{"date": "2026-10-14", "lock": pick("hit", 0.95), "value": None},
                        {"date": "2026-10-15", "lock": pick("miss", 0.94), "value": pick("hit", 0.40)},
                        {"date": "2026-10-16", "lock": pick(None, 0.96), "value": pick("void", 0.45)}]}
        rows = E.botd_rows(doc)
        self.assertEqual(len(rows), 3)                       # ungraded and void picks stay out
        out = {s["key"]: s for s in E.build(rows, "2026-10-17")}
        v = out["botd-value"]
        self.assertEqual((v["n"], v["units"]), (1, 1.5))     # a 40c win pays 1.5 units
        self.assertEqual(out["botd-lock"]["n"], 2)
        self.assertNotIn("all-mlb", out)                     # they don't count twice in the sport rows
        empty = {s["key"]: s for s in E.build([], "2026-10-17")}
        self.assertEqual(empty["botd-value"]["verdict"], "Waiting for games")
        self.assertEqual(E.botd_rows(None), [])


class PrivateRuleFilterTest(unittest.TestCase):
    def pick(self, **kw):
        p = {"sport": "nhl", "side": "under", "stat": "a", "line": 0.5, "pr": 0.60, "lists": "V", "p0": 0.61, "prob": 0.75, "pos": "D"}
        p.update(kw)
        return p

    def test_list_edge_positions_and_price_drop(self):
        t = E.rule_test({"sport": "nhl", "side": "under", "stat": "a", "list": "V", "drop": 3,
                                   "emin": 10, "emax": 30, "xpos": "C, "})
        self.assertTrue(t(self.pick()))
        self.assertFalse(t(self.pick(lists="T")))              # not a Value spot
        self.assertFalse(t(self.pick(pos="C")))                # centers left out
        self.assertFalse(t(self.pick(prob=0.66)))              # model only 6 points over the price
        self.assertFalse(t(self.pick(prob=0.95)))              # 35 points: over emax
        self.assertFalse(t(self.pick(p0=0.64)))                # the price fell 4c from its first price
        self.assertFalse(t(self.pick(pr=0.44, p0=0.47)))       # exactly 3c (0.44 - 0.47 is -2.999... in floats)
        self.assertTrue(t(self.pick(p0=0.62)))                 # 2c: kept
        self.assertTrue(t(self.pick(p0=None)))                 # no first price recorded: kept
        dated = E.rule_test({"sport": "nhl", "since": "2026-10-20"})
        self.assertEqual(dated.since, "2026-10-20")
        self.assertTrue(dated.past(self.pick(day="2026-10-19")))   # the copy without the start day
        self.assertFalse(dated(self.pick(day="2026-10-19")))   # before the rule was added: not counted
        self.assertTrue(dated(self.pick(day="2026-10-20")))
        priv = E.private_strategies({"items": [{"key": "nhl-assist-unders", "label": "Old rule", "sport": "nhl"},
                                               {"key": "private-new", "label": "New rule", "sport": "nhl", "stat": "zz", "since": "2026-10-20"}]})
        self.assertEqual([k for k, _, _, _ in priv], ["private-all", "private-nhl-assist-unders", "private-new"])
        rows = [{"sport": "nhl", "day": "2026-10-18", "pr": 0.5, "win": True, "side": "under", "stat": "zz", "line": 0.5, "lists": ""}]
        out = E.build(rows, "2026-10-20", strategies=priv, waiting={k for k, _, _, _ in priv})
        E.mark_private(out, priv, rows, "2026-10-20")
        new = {s["key"]: s for s in out}["private-new"]
        self.assertEqual((new["n"], new["verdict"], new["since"], new["past"]["n"]), (0, "Waiting for games", "2026-10-20", 1))
        self.assertTrue(all(s.get("private") for s in out))
        self.assertTrue(E.rule_test({"sport": "nhl"})(self.pick(prob=None, p0=None, pos=None, lists="")))


if __name__ == "__main__":
    unittest.main()

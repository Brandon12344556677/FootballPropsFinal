import datetime
import unittest

import edge_report
import tpod

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 20, 16, 0, tzinfo=UTC)          # 12:00 PM ET
TONIGHT = "2026-10-20T23:00:00Z"


def cand(pid, gid, prob, price, sport="nhl", stat="a", side="under", **kw):
    c = {"sport": sport, "pid": pid, "player": "Player " + pid, "team": "AAA", "opp": "BBB", "gid": gid, "stat": stat,
         "statText": "Assists", "line": 0.5, "side": side, "prob": prob, "lo": prob - 0.07, "hi": prob + 0.06,
         "price": price, "vn": "P", "start": TONIGHT, "l10": [0, 0, 1, 0, 0, 0, 0, 1, 0, 0], "lists": "V",
         "neff": 40, "px0": price, "flag": None, "lk": None, "pos": "D", "pp": price, "pd": 200.0}
    c.update(kw)
    return c


def methods(*rules):
    """rank_methods' shape without graded picks: (label, sport, test, record), in the order given."""
    return [(r["label"], r.get("sport"), edge_report.rule_test(r), {"n": 100, "hit": 0.7, "roi": 0.1, "lo": 0.02, "hi": 0.2})
            for r in rules]


NHL_A = {"label": "NHL assist unders", "sport": "nhl", "side": "under", "stat": "a"}
ANY_V = {"label": "Value spots", "list": "V"}


class TpodTest(unittest.TestCase):
    def setUp(self):   # these cases are dated Oct 20, before the real series start
        self._start, tpod.SERIES_START = tpod.SERIES_START, "2000-01-01"

    def tearDown(self):
        tpod.SERIES_START = self._start

    def test_eligible_needs_payout_confidence_and_a_clean_price(self):
        self.assertTrue(tpod.eligible(cand("1", "g1", 0.72, 0.55), NOW))
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.97, 0.90), NOW))               # a "lock": pays too little
        self.assertTrue(tpod.eligible(cand("1", "g1", 0.84, 0.74), NOW))                # 74c: allowed (1.35x)
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.90, 0.78), NOW))               # 78c: over the cap
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.58, 0.45), NOW))               # model under 60%
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.63, 0.60), NOW))               # only 3 points over the price
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.72, 0.55, px0=0.58), NOW))     # price dropped 3c
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.72, 0.55, flag="Questionable"), NOW))
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.72, 0.55, start="2026-10-20T16:30:00Z"), NOW))   # 30 min away
        self.assertFalse(tpod.eligible(cand("1", "g1", 0.72, 0.55, start="2026-10-21T23:00:00Z"), NOW))   # tomorrow

    def test_three_picks_ranked_by_method_with_variety(self):
        cands = [cand(str(i), "g" + str(i), 0.75, 0.55) for i in range(5)] + \
                [cand("n1", "gn", 0.70, 0.52, sport="nba", stat="reb", side="over", statText="Rebounds")]
        state = {"days": []}
        self.assertTrue(tpod.update(state, cands, [], methods(NHL_A, ANY_V), NOW))
        picks = state["days"][0]["picks"]
        self.assertEqual(len(picks), 3)
        kinds = [tpod.kind(p) for p in picks]
        self.assertEqual(kinds.count(("nhl", "a", "under")), 2)                         # at most two of one kind
        self.assertIn(("nba", "reb", "over"), kinds)
        self.assertEqual(len({p["gid"] for p in picks}), 3)
        self.assertEqual(picks[0]["method"], "NHL assist unders")                        # the better-ranked method first
        self.assertTrue(any("cashed in 8 of Player 0's last 10" in w for w in picks[0]["why"]))
        self.assertNotIn("NHL assist unders", state["days"][0]["script"])               # the method never in the script

    def test_frozen_once_made_and_graded(self):
        state = {"days": []}
        tpod.update(state, [cand("1", "g1", 0.75, 0.55)], [], methods(NHL_A), NOW)
        later = NOW + datetime.timedelta(hours=1)
        tpod.update(state, [cand("2", "g2", 0.90, 0.60), cand("1", "g1", 0.75, 0.40)], [], methods(NHL_A), later)
        picks = state["days"][0]["picks"]
        self.assertEqual(picks[0]["price"], 0.55)                                        # the first pick never changes
        self.assertEqual([p["pid"] for p in picks], ["1", "2"])                         # later runs fill the rest
        cols = ["src", "gid", "pid", "stat", "line", "side", "res", "actual", "date"]
        docs = [("nhl", {"cols": cols, "picks": [["live", "g1", "1", "a", 0.5, "under", "hit", 0, "2026-10-20"],
                                                  ["live", "g2", "2", "a", 0.5, "under", "miss", 1, "2026-10-20"]]})]
        tpod.update(state, [], docs, methods(NHL_A), NOW + datetime.timedelta(days=1))
        self.assertEqual(tpod.record(state["days"]), {"n": 2, "hit": 1, "miss": 1, "units": round(1 / 0.55 - 1 - 1, 2)})

    def test_series_starts_on_day_one(self):
        tpod.SERIES_START = "2026-10-21"
        state = {"days": [{"date": "2026-10-20", "picks": [dict(cand("x", "gx", 0.7, 0.5), res="miss")]}]}
        now = datetime.datetime(2026, 10, 21, 16, 0, tzinfo=UTC)
        self.assertTrue(tpod.update(state, [cand("1", "g1", 0.75, 0.55, start="2026-10-21T23:00:00Z")], [], methods(NHL_A), now))
        self.assertEqual([d["date"] for d in state["days"]], ["2026-10-21"])          # the dry-run day is gone
        self.assertTrue(state["days"][0]["script"].startswith("This is day 1 of"))
        self.assertNotIn("went", state["days"][0]["script"])
        self.assertEqual(tpod.record(state["days"])["n"], 0)

    def test_methods_judged_by_sport(self):
        rows = lambda sport, n, win: [["live", f"{sport}{i}", str(i), "a", 0.5, "under", "hit" if i < win else "miss", 0, "2026-10-1%d" % (i % 9), 0.55, None]
                                      for i in range(n)]
        cols = ["src", "gid", "pid", "stat", "line", "side", "res", "actual", "date", "price", "lists"]
        docs = [("nhl", {"cols": cols, "picks": rows("nhl", 60, 45)}), ("nba", {"cols": cols, "picks": rows("nba", 40, 10)}),
                ("mlb", {"cols": cols, "picks": rows("mlb", 10, 9)})]
        ranked = tpod.rank_methods(edge_report.private_strategies({"items": [{"label": "Any assist unders", "side": "under", "stat": "a"}]}),
                                   docs, "2026-10-21")
        self.assertEqual([m[1] for m in ranked if m[3]["tier"] == 0], ["nhl"])   # NBA loses money; MLB has too few picks
        self.assertEqual(ranked[0][1], "nhl")                                      # proven pairs first, then the fill-ins
        state = {"days": [{"date": "2026-10-20", "v": 1, "picks": [cand("old", "go", 0.75, 0.55, sport="nba")]}]}
        cands = [cand("1", "g1", 0.75, 0.55), cand("2", "g2", 0.75, 0.55, sport="nba")]
        tpod.update(state, cands, [], ranked, NOW)                # today's old-rule picks, nothing started: remade
        picks = state["days"][0]["picks"]
        self.assertEqual([(p["pid"], p["sport"], p["tier"]) for p in picks], [("1", "nhl", 0), ("2", "nba", 1)])   # proven, then a fill-in
        self.assertIn("which in the NHL has hit 75%", " ".join(picks[0]["why"]))
        self.assertIn("Fill-in: fits Any assist unders, which isn't proven in the NBA yet", " ".join(picks[1]["why"]))
        self.assertNotIn("Fill-in", state["days"][0]["script"])
        started = {"days": [{"date": "2026-10-20", "v": 1, "picks": [dict(cand("old", "go", 0.75, 0.55, start="2026-10-20T15:00:00Z"),
                                                                              spoken="Player old, no assists")]}]}
        tpod.update(started, cands, [], ranked, NOW)              # a game already started: kept as it was
        self.assertEqual(started["days"][0]["picks"][0]["pid"], "old")

    def test_always_three_picks_on_a_thin_night(self):
        # one proven pick; the rest: no method fits, and one only passes the relaxed bar
        cands = [cand("1", "g1", 0.75, 0.55), cand("2", "g2", 0.66, 0.60, sport="nba", stat="reb"),
                 cand("3", "g3", 0.58, 0.55, sport="nba", stat="pts", lists="")]
        state = {"days": []}
        tpod.update(state, cands, [], methods(NHL_A), NOW)
        picks = state["days"][0]["picks"]
        self.assertEqual([(p["pid"], p["tier"], p["relaxed"]) for p in picks], [("1", 0, False), ("2", 2, False), ("3", 2, True)])
        self.assertIn("Thin night", " ".join(picks[2]["why"]))

    def test_combo_stats_read_out(self):
        self.assertEqual(tpod.say_line(cand("1", "g", 0.7, 0.5, line=34.5, side="over", statText="Pts+Reb+Ast")),
                         "over 34.5 points, rebounds and assists")

    def test_fun_parlay_about_3x(self):
        cands = [cand("1", "g1", 0.80, 0.58), cand("2", "g2", 0.80, 0.58), cand("3", "g3", 0.70, 0.62)]
        par = tpod.choose_parlay(cands, methods(NHL_A), NOW, avoid=set())
        self.assertTrue(tpod.PARLAY_PAYS[0] <= 1 / par["price"] <= tpod.PARLAY_PAYS[1])
        self.assertEqual(len({leg["gid"] for leg in par["legs"]}), len(par["legs"]))
        self.assertIsNone(tpod.choose_parlay(cands, methods(NHL_A), NOW, avoid={"1", "2", "3"}))
        par["legs"][0]["res"], par["legs"][1]["res"] = "hit", "void"
        par["legs"] = par["legs"][:2]
        tpod.grade_parlay(par, {}, NOW)
        self.assertEqual(par["res"], "hit")                                               # a void leg drops out
        self.assertAlmostEqual(par["units"], round(1 / par["legs"][0]["price"] - 1, 3))

    def test_polymarket_money_needed(self):
        state = {"days": []}
        cands = [cand("1", "g1", 0.80, 0.55, pd=3.0),                      # the best, but only $3 on Polymarket
                 cand("2", "g2", 0.75, 0.45, pp=0.55, vn="K"),             # cheaper on Kalshi: taken at Polymarket's price
                 cand("3", "g3", 0.75, 0.50, pp=None, vn="K")]             # not on Polymarket at all
        tpod.update(state, cands, [], methods(NHL_A), NOW)
        picks = state["days"][0]["picks"]
        self.assertEqual([(p["pid"], p["price"], p["vn"]) for p in picks], [("2", 0.55, "P")])

    def test_script_and_caption(self):
        day = {"picks": [tpod.choose([cand("1", "g1", 0.75, 0.55)], methods(NHL_A), NOW, set())]}
        text, cap = tpod.script(day, {"n": 10, "hit": 6, "miss": 4, "units": 1.5}, "2026-10-20", day_no=4)
        self.assertTrue(text.startswith("This is day 4 of giving you guys my top pick for the day."))
        day["parlay"] = tpod.choose_parlay([cand("2", "g2", 0.80, 0.58), cand("3", "g3", 0.80, 0.58)], methods(NHL_A), NOW, set())
        text, cap = tpod.script(day, {"n": 0}, "2026-10-20")
        self.assertIn("for the day, plus one more of a reach parlay.", text)
        self.assertIn("Now the reach parlay. It's 2 legs paying about", text)
        self.assertIn("Day 1: my top pick + a reach parlay", cap)
        self.assertIn("Player 1, no assists, paying about 1.8 times your money", text)
        yday = {"date": "2026-10-19", "picks": [dict(cand("a", "ga", 0.7, 0.5), res="hit"), dict(cand("b", "gb", 0.7, 0.5), res="hit"),
                                                dict(cand("c", "gc", 0.7, 0.5), res="miss")],
                "parlay": {"res": "miss", "units": -1.0, "legs": []}}
        last = tpod.last_day([yday])
        self.assertEqual(last, ("2026-10-19", 2, 3, 1.0, 0, 1))                         # picks +1 +1 -1; the parlay apart
        text, cap = tpod.script({"picks": day["picks"]}, {"n": 10, "hit": 6, "miss": 4, "units": 4.3}, "2026-10-20",
                                {"n": 3, "hit": 1, "miss": 2, "units": 1.0}, day_no=5, last=("2026-10-19", 2, 3, 1.5, 0, 1))
        self.assertIn("for the day. Yesterday we went 2 for 3 on picks, which is +1.5 units, bringing the series total to "
                      "+4.3 units. And 0 for 1 on the parlay.", text)                  # the series is the picks only
        self.assertIn("Yesterday: picks 2/3 (+1.5 units) | parlay 0/1 | Series: +4.3 units", cap)
        text, _ = tpod.script({"picks": day["picks"]}, {"n": 2, "hit": 0, "miss": 2, "units": -2.0}, "2026-10-20",
                              last=("2026-10-17", 0, 2, -2.0, 0, 0))
        self.assertIn("On Saturday we went 0 for 2 on picks, which is -2 units, bringing the series total to -2 units. First", text)
        self.assertEqual(tpod.last_day([{"date": "2026-10-19", "picks": [], "parlay": {"res": "hit", "units": 2.0}}]),
                         ("2026-10-19", 0, 0, 0, 1, 1))
        self.assertNotIn("we went", tpod.script({"picks": day["picks"]}, {"n": 0}, "2026-10-20")[0])   # day 1: nothing yet
        self.assertTrue(tpod.script({"picks": []}, {"n": 0}, "2026-10-20")[0].startswith("No picks from me today"))
        self.assertIn("18+", cap)


if __name__ == "__main__":
    unittest.main()

import datetime
import unittest

import edge_report
import parlay

COLS = ["src", "gid", "pid", "player", "team", "opp", "stat", "line", "side", "prob", "price", "neff", "start", "res", "lk", "th", "hd", "vn",
        "pp", "pd"]
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 16, 16, 0, tzinfo=UTC)          # 12:00 PM ET


def pick(pid, gid, prob, price, start="2026-10-17T00:00Z", **kw):
    p = dict(src="live", gid=gid, pid=pid, player="P" + pid, team="A", opp="B", stat="g", line=0.5, side="under",
             prob=prob, price=price, neff=20, start=start, res=None, lk=None, th=None, hd=None, vn="P", pp=price, pd=100)
    p.update(kw)
    return [p[c] for c in COLS]


def doc(*rows):
    return {"cols": COLS, "picks": list(rows)}


class ParlayTest(unittest.TestCase):
    def docs(self, *rows):
        return [("nhl", doc(*rows))]

    def test_picks_the_best_price_in_each_band(self):
        d = self.docs(pick("A", "g1", 0.80, 0.60), pick("B", "g2", 0.75, 0.55), pick("C", "g3", 0.70, 0.55),
                      pick("D", "g1", 0.85, 0.78))
        legs = parlay.candidates(d, NOW)
        got = {b: sorted(l["pid"] for l in parlay.choose(legs, band)["legs"]) for b, band in enumerate(parlay.BANDS)}
        # 3-3.5x: B+C (52.5% at 30.25c, 3.31x); A+B would be 3.03x but 60% (too sure)
        # 3.5-4x: A+B+D (51% at 25.7c, 3.89x) beats A+C+D (47.6% at the same price)
        # 4-4.5x: B+C+D (44.6% at 23.6c, 4.24x)
        self.assertEqual(got, {0: ["B", "C"], 1: ["A", "B", "D"], 2: ["B", "C", "D"]})

    def test_payout_bands(self):
        d = self.docs(pick("1", "g1", 0.75, 0.60), pick("2", "g2", 0.70, 0.60))   # 52.5% but 36c: pays only 2.8x
        self.assertIsNone(parlay.choose(parlay.candidates(d, NOW)))
        d = self.docs(pick("1", "g1", 0.75, 0.60), pick("2", "g2", 0.70, 0.555))  # 33.3c: exactly 3x is fine
        self.assertIsNotNone(parlay.choose(parlay.candidates(d, NOW)))
        d = self.docs(pick("1", "g1", 0.70, 0.45), pick("2", "g2", 0.70, 0.45))   # 20.25c: 4.94x, over every band
        self.assertEqual([parlay.choose(parlay.candidates(d, NOW), b) for b in parlay.BANDS], [None] * 3)

    def test_skips_legs_that_cant_go_in(self):
        d = self.docs(pick("1", "g1", 0.8, 0.6, lk="x"), pick("2", "g1", 0.8, 0.6, th=1), pick("3", "g1", 0.8, 0.6, hd=1),
                      pick("4", "g1", 0.8, 0.6, neff=3), pick("5", "g1", 0.62, 0.6),         # under 3 points of edge
                      pick("6", "g1", 0.8, 0.6, start="2026-10-16T16:30Z"),               # starts in 30 minutes
                      pick("7", "g1", 0.8, 0.6, start="2026-10-18T00:00Z"),               # tomorrow (ET)
                      pick("8", "g1", 0.8, None))
        self.assertEqual(parlay.candidates(d, NOW), [])

    def test_only_nhl_legs(self):
        d = [(s, doc(pick(s + "1", s + "g1", 0.8, 0.6), pick(s + "2", s + "g2", 0.75, 0.6)))
             for s in ("nfl", "nba", "mlb", "nhl")]
        self.assertEqual({l["sport"] for l in parlay.candidates(d, NOW)}, {"nhl"})
        state = {"days": []}
        parlay.step(state, [s for s in d if s[0] != "nhl"], NOW)
        self.assertEqual([e for e in state["days"] if e.get("legs")], [])   # no hockey: no parlay

    def test_remakes_todays_parlays_that_break_the_rules_before_their_games(self):
        leg = lambda s, pid, start, venue="Polymarket": {"key": [s, "g", pid], "sport": s, "pid": pid, "gid": "g" + pid,
                                                         "start": start, "prob": 0.7, "price": 0.55, "player": "P" + pid,
                                                         "venue": venue}
        ok = dict(model=0.40, price=0.30, band=0)                                                 # 3.33x
        later, started = "2026-10-17T00:00Z", "2026-10-16T15:00Z"
        state = {"days": [
            {"date": "2026-10-15", "n": 1, "res": None, "legs": [leg("nfl", "y", started)]},             # yesterday: kept
            dict(ok, date="2026-10-16", n=1, res=None, legs=[leg("nfl", "c", started), leg("nhl", "d", later)]), # started
            dict(ok, date="2026-10-16", n=1, res=None, legs=[leg("nfl", "a", later), leg("nhl", "b", later)]),   # NFL
            dict(ok, date="2026-10-16", n=3, res=None, legs=[leg("nhl", "e", later), leg("nhl", "f", later, "Kalshi")]),
            dict(model=0.40, price=0.27, band=2, date="2026-10-16", n=3, res=None,                         # 3.7x: not 4-4.5x
                 legs=[leg("nhl", "g", later)]),
            {"date": "2026-10-16", "n": 2, "res": None, "model": 0.4, "price": 0.27,                       # made before bands
             "legs": [leg("nhl", "k", later)]},
            dict(model=0.40, price=0.27, band=1, date="2026-10-16", n=2, res=None,                         # fits 3.5-4x
                 legs=[leg("nhl", "h", later), leg("nhl", "i", later)])]}
        rows = [pick("1", "h1", 0.70, 0.48), pick("2", "h2", 0.70, 0.49)]                             # 23.5c: 4.25x
        self.assertTrue(parlay.step(state, self.docs(*rows), NOW))
        today = [e for e in state["days"] if e["date"] == "2026-10-16"]
        self.assertEqual([[l["pid"] for l in e["legs"]] for e in today][:2], [["c", "d"], ["h", "i"]])   # kept
        self.assertEqual([(e["n"], e["band"]) for e in today], [(1, 0), (2, 1), (3, 2)])
        self.assertEqual(sorted(l["pid"] for l in today[2]["legs"]), ["1", "2"])                       # the remake
        self.assertTrue(parlay.meets_rules(today[2]))
        self.assertEqual(state["days"][0]["date"], "2026-10-15")

    def test_polymarket_price_only(self):
        d = self.docs(pick("1", "g1", 0.80, 0.60, pp=None, vn="K"),          # Kalshi only: out
                      pick("2", "g2", 0.80, 0.60, pd=10),                      # under $25 on Polymarket: out
                      pick("3", "g3", 0.80, 0.50, pp=0.62, vn="K"),          # Kalshi cheaper: priced at Polymarket's 62c
                      pick("4", "g4", 0.75, 0.60))
        legs = parlay.candidates(d, NOW)
        self.assertEqual(sorted(l["pid"] for l in legs), ["3", "4"])
        self.assertEqual({l["pid"]: l["price"] for l in legs}["3"], 0.62)
        self.assertEqual({l["venue"] for l in legs}, {"Polymarket"})

    def test_nba_track_uses_nba_legs_only(self):
        d = [(s, doc(pick(s + "1", s + "g1", 0.70, 0.55), pick(s + "2", s + "g2", 0.70, 0.55)))
             for s in ("nhl", "nba")]
        self.assertEqual({l["sport"] for l in parlay.candidates(d, NOW, sports={"nba"})}, {"nba"})
        state = {"days": []}
        parlay.step(state, d, NOW, sports={"nba"})
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([{l["sport"] for l in e["legs"]} for e in made], [{"nba"}])
        self.assertTrue(parlay.meets_rules(made[0], {"nba"}))
        self.assertFalse(parlay.meets_rules(made[0]))                  # not an NHL-track parlay
        self.assertEqual([t[0] for t in parlay.TRACKS], ["nhl", "nba", "nfl"])
        self.assertEqual(len({t[2] for t in parlay.TRACKS}), 3)        # each track has its own file

    def test_nfl_track_takes_kickoffs_from_the_schedule(self):
        rows = [pick("1", "n1", 0.70, 0.55, start=None), pick("2", "n2", 0.70, 0.55, start=None)]   # NFL picks carry no start
        kick = {"n1": datetime.datetime(2026, 10, 17, 0, 0, tzinfo=UTC), "n2": datetime.datetime(2026, 10, 17, 0, 0, tzinfo=UTC)}
        state = {"days": []}
        parlay.step(state, [("nfl", doc(*rows))], NOW, kick, sports={"nfl"})
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([{l["sport"] for l in e["legs"]} for e in made], [{"nfl"}])
        self.assertTrue(all(l["start"] for l in made[0]["legs"]))
        self.assertTrue(parlay.meets_rules(made[0], {"nfl"}))

    def test_at_most_two_legs_per_game_and_one_per_player(self):
        d = self.docs(pick("1", "g1", 0.8, 0.6), pick("2", "g1", 0.8, 0.6), pick("3", "g1", 0.8, 0.6))
        self.assertIsNone(parlay.choose(parlay.candidates(d, NOW)))   # 3 legs from one game: no
        d = self.docs(pick("1", "g1", 0.7, 0.6), pick("1", "g2", 0.7, 0.6, stat="a"))
        self.assertIsNone(parlay.choose(parlay.candidates(d, NOW)))   # the same player twice: no

    def test_made_once_from_11_and_frozen(self):
        rows = [pick("1", "g1", 0.80, 0.60), pick("2", "g2", 0.65, 0.55)]
        state = {"days": []}
        self.assertFalse(parlay.step(state, self.docs(*rows), datetime.datetime(2026, 10, 16, 14, 0, tzinfo=UTC)))  # 10 AM ET
        self.assertTrue(parlay.step(state, self.docs(*rows), NOW))
        first = [l["pid"] for l in state["days"][0]["legs"]]
        better = rows + [pick("3", "g3", 0.70, 0.40)]
        parlay.step(state, self.docs(*better), NOW + datetime.timedelta(minutes=10))
        self.assertEqual([l["pid"] for l in state["days"][0]["legs"]], first)   # the first one never changes
        self.assertEqual(len(state["days"]), 1)                                  # nobody left for a second

    def test_one_per_band_with_no_shared_players(self):
        rows = [pick("1", "g1", 0.70, 0.55), pick("2", "g2", 0.70, 0.55),       # 30.25c: 3.31x
                pick("3", "g3", 0.70, 0.50), pick("4", "g4", 0.70, 0.53),       # 26.5c: 3.77x
                pick("5", "g5", 0.70, 0.48), pick("6", "g6", 0.70, 0.49)]       # 23.5c: 4.25x
        state = {"days": []}
        parlay.step(state, self.docs(*rows), NOW)
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([(e["n"], e["band"]) for e in made], [(1, 0), (2, 1), (3, 2)])
        for e in made:
            self.assertTrue(parlay.in_band(e["price"], parlay.BANDS[e["band"]]))
        pids = [l["pid"] for e in made for l in e["legs"]]
        self.assertEqual(len(pids), len(set(pids)))                            # no player (so no prop) twice
        self.assertFalse(parlay.step(state, self.docs(*rows), NOW + datetime.timedelta(minutes=10)))   # full: nothing more

    def test_later_runs_fill_the_rest(self):
        state = {"days": []}
        parlay.step(state, self.docs(pick("1", "g1", 0.7, 0.55), pick("2", "g2", 0.7, 0.55)), NOW)
        self.assertEqual([e["n"] for e in state["days"]], [1])                 # only a 3-3.5x so far
        more = [pick("1", "g1", 0.7, 0.55), pick("2", "g2", 0.7, 0.55), pick("3", "g3", 0.7, 0.50), pick("4", "g4", 0.7, 0.53)]
        parlay.step(state, self.docs(*more), NOW + datetime.timedelta(hours=2))
        self.assertEqual([e["n"] for e in state["days"]], [1, 2])              # 3.5-4x filled; 4-4.5x still open

    def test_no_parlay_after_730(self):
        state = {"days": []}
        late = datetime.datetime(2026, 10, 16, 23, 40, tzinfo=UTC)   # 7:40 PM ET
        self.assertTrue(parlay.step(state, self.docs(), late))
        self.assertTrue(state["days"][0]["closed"])

    def graded(self, *res):
        state = {"days": []}
        parlay.step(state, self.docs(*[pick(str(i), "g" + str(i), 0.7, 0.55) for i in range(2)]), NOW)
        e = state["days"][0]
        done = [pick(str(i), "g" + str(i), 0.7, 0.55, res=r) for i, r in enumerate(res)]
        parlay.grade(e, self.docs(*done), "2026-10-17")
        return e

    def test_grading(self):
        e = self.graded("hit", "hit")
        self.assertEqual((e["res"], e["units"]), ("hit", round(1 / 0.3025 - 1, 3)))
        self.assertEqual(self.graded("hit", "miss")["res"], "miss")
        e = self.graded("hit", "dnp")                       # a DNP drops the leg: pays on the other one
        self.assertEqual((e["res"], e["units"]), ("hit", round(1 / 0.55 - 1, 3)))
        self.assertEqual(self.graded("push", "dnp")["res"], "void")
        self.assertIsNone(self.graded("hit", None)["res"])   # still waiting on a leg

    def test_edge_tracker_row(self):
        state = {"days": [{"date": "2026-10-14", "res": "hit", "price": 0.25, "paid": 0.25, "units": 3.0, "model": 0.5},
                          {"date": "2026-10-15", "res": "miss", "price": 0.25, "units": -1.0, "model": 0.5},
                          {"date": "2026-10-16", "closed": True}]}
        rows = edge_report.parlay_rows(state)
        out = {s["key"]: s for s in edge_report.build(rows, "2026-10-16")}
        self.assertEqual((out["parlays"]["n"], out["parlays"]["units"]), (2, 2.0))
        self.assertNotIn("all-nhl", out)                     # parlays never count as sport picks
        self.assertEqual(edge_report.build([], "2026-10-16")[-1]["verdict"], "Waiting for games")
        nba = edge_report.parlay_rows({"days": state["days"][:1]}, "parlay-nba")   # the NBA track: its own row
        out = {s["key"]: s for s in edge_report.build(rows + nba, "2026-10-16")}
        self.assertEqual((out["parlays"]["n"], out["parlays-nba"]["n"]), (2, 1))
        nfl = edge_report.parlay_rows({"days": state["days"][1:2]}, "parlay-nfl")
        out = {s["key"]: s for s in edge_report.build(rows + nba + nfl, "2026-10-16")}
        self.assertEqual((out["parlays"]["n"], out["parlays-nba"]["n"], out["parlays-nfl"]["n"]), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()

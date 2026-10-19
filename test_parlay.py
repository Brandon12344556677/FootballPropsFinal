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

    def test_picks_about_a_coin_flip_with_the_best_price(self):
        d = self.docs(pick("1", "g1", 0.80, 0.60), pick("2", "g2", 0.75, 0.60), pick("3", "g1", 0.80, 0.78),
                      pick("4", "g3", 0.70, 0.66))
        c = parlay.choose(parlay.candidates(d, NOW))
        self.assertTrue(0.45 <= c["model"] <= 0.55)
        self.assertEqual(sorted(l["pid"] for l in c["legs"]), ["2", "4"])   # the only pair in range (0.525 vs 0.396)

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

    def test_remakes_todays_non_nhl_parlays_before_their_games(self):
        leg = lambda s, pid, start: {"key": [s, "g", pid], "sport": s, "pid": pid, "gid": "g" + pid, "start": start,
                                     "prob": 0.7, "price": 0.55, "player": "P" + pid}
        later, started = "2026-10-17T00:00Z", "2026-10-16T15:00Z"
        state = {"days": [
            {"date": "2026-10-15", "n": 1, "res": None, "legs": [leg("nfl", "y", started)]},             # yesterday: kept
            {"date": "2026-10-16", "n": 1, "res": None, "legs": [leg("nfl", "a", later), leg("nhl", "b", later)]},
            {"date": "2026-10-16", "n": 2, "res": None, "legs": [leg("nfl", "c", started), leg("nhl", "d", later)]},
            {"date": "2026-10-16", "n": 3, "res": None, "legs": [leg("nhl", "e", later), leg("nhl", "f", later)]}]}
        rows = [pick(str(i), "h" + str(i), 0.70, 0.55) for i in range(4)]
        self.assertTrue(parlay.step(state, self.docs(*rows), NOW))
        today = [e for e in state["days"] if e["date"] == "2026-10-16"]
        self.assertEqual([e["n"] for e in today], [1, 2, 3])
        self.assertEqual([[l["pid"] for l in e["legs"]] for e in today][:2], [["c", "d"], ["e", "f"]])   # started: kept
        self.assertEqual({l["sport"] for l in today[2]["legs"]}, {"nhl"})                                   # the remake
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

    def test_three_a_day_with_no_shared_players(self):
        rows = [pick(str(i), "g" + str(i), 0.70, 0.55) for i in range(8)]
        state = {"days": []}
        parlay.step(state, self.docs(*rows), NOW)
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([e["n"] for e in made], [1, 2, 3])
        pids = [l["pid"] for e in made for l in e["legs"]]
        self.assertEqual(len(pids), len(set(pids)))
        self.assertFalse(parlay.step(state, self.docs(*rows), NOW + datetime.timedelta(minutes=10)))   # full: nothing more

    def test_later_runs_fill_the_rest(self):
        state = {"days": []}
        parlay.step(state, self.docs(pick("1", "g1", 0.7, 0.55), pick("2", "g2", 0.7, 0.55)), NOW)
        self.assertEqual(len(state["days"]), 1)
        more = [pick(str(i), "g" + str(i), 0.7, 0.55) for i in range(1, 5)]
        parlay.step(state, self.docs(*more), NOW + datetime.timedelta(hours=2))
        self.assertEqual([e["n"] for e in state["days"]], [1, 2])

    def test_no_parlay_after_730(self):
        state = {"days": []}
        late = datetime.datetime(2026, 10, 16, 23, 40, tzinfo=UTC)   # 7:40 PM ET
        self.assertTrue(parlay.step(state, self.docs(), late))
        self.assertTrue(state["days"][0]["closed"])

    def graded(self, *res):
        state = {"days": []}
        parlay.step(state, self.docs(*[pick(str(i), "g" + str(i), 0.7, 0.6) for i in range(2)]), NOW)
        e = state["days"][0]
        done = [pick(str(i), "g" + str(i), 0.7, 0.6, res=r) for i, r in enumerate(res)]
        parlay.grade(e, self.docs(*done), "2026-10-17")
        return e

    def test_grading(self):
        e = self.graded("hit", "hit")
        self.assertEqual((e["res"], e["units"]), ("hit", round(1 / 0.36 - 1, 3)))
        self.assertEqual(self.graded("hit", "miss")["res"], "miss")
        e = self.graded("hit", "dnp")                       # a DNP drops the leg: pays on the other one
        self.assertEqual((e["res"], e["units"]), ("hit", round(1 / 0.6 - 1, 3)))
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


if __name__ == "__main__":
    unittest.main()

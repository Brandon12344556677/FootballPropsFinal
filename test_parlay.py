import datetime
import json
import unittest

import combos
import edge_report
import parlay

combos._cache.update(nhl=set(), nba=set(), nfl=set(), mlb=set())   # no network in tests: every prop type parlays

COLS = ["src", "gid", "pid", "player", "team", "opp", "stat", "line", "side", "prob", "price", "neff", "start", "res", "lk", "th", "hd", "vn",
        "pp", "pd"]
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 16, 16, 0, tzinfo=UTC)          # 12:00 PM ET
# Parlay of the Day as it runs, with its series started before these tests' dates (Parlay Payday's
# own day 1 is tested in test_parlay_payday_*)
POTD = dict(parlay.POTD_RULES, series_start="2026-10-01")


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

    def test_only_props_polymarket_lets_you_parlay(self):
        combos._cache["nhl"] = {"a"}                  # NHL assists: comboEnabled off on Polymarket US
        try:
            d = self.docs(pick("1", "g1", 0.7, 0.55, stat="a"), pick("2", "g2", 0.7, 0.55), pick("3", "g3", 0.7, 0.55, stat="pts"))
            self.assertEqual(sorted(l["pid"] for l in parlay.candidates(d, NOW)), ["2", "3"])
            leg = lambda pid, stat: {"key": ["nhl", "g", pid], "sport": "nhl", "pid": pid, "gid": "g" + pid, "stat": stat,
                                     "start": "2026-10-17T00:00Z", "prob": 0.7, "price": 0.55, "player": "P" + pid, "venue": "Polymarket"}
            made = dict(model=0.40, price=0.30, band=0, date="2026-10-16", n=1, res=None, legs=[leg("a", "a"), leg("b", "g")])
            self.assertFalse(parlay.meets_rules(made))   # today's with an assists leg: remade before its games
            self.assertTrue(parlay.meets_rules(dict(made, legs=[leg("b", "g"), leg("c", "pts")])))
        finally:
            combos._cache["nhl"] = set()

    def test_combo_flags_by_type(self):
        mk = lambda smt, ok, closed=False: {"sportsMarketType": smt, "comboEnabled": ok, "closed": closed}
        markets = [mk("hockey_player_assists", False), mk("hockey_player_assists", False), mk("hockey_player_goals", True),
                   mk("hockey_player_points", True), mk("hockey_player_points", False), mk("hockey_team_moneyline", False),
                   mk("hockey_player_shots_on_goal", True, closed=True)]
        self.assertEqual(combos.blocked_types(markets, "nhl"), {"a"})   # points: one market allows it, so the type does

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
        self.assertEqual([t[0] for t in parlay.TRACKS], ["nhl", "nba", "nfl", "potd"])
        self.assertEqual(len({t[2] for t in parlay.TRACKS}), 4)        # each track has its own file

    def test_nfl_track_takes_kickoffs_from_the_schedule(self):
        rows = [pick("1", "n1", 0.70, 0.55, start=None), pick("2", "n2", 0.70, 0.55, start=None)]   # NFL picks carry no start
        kick = {"n1": datetime.datetime(2026, 10, 17, 0, 0, tzinfo=UTC), "n2": datetime.datetime(2026, 10, 17, 0, 0, tzinfo=UTC)}
        state = {"days": []}
        parlay.step(state, [("nfl", doc(*rows))], NOW, kick, sports={"nfl"})
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([{l["sport"] for l in e["legs"]} for e in made], [{"nfl"}])
        self.assertTrue(all(l["start"] for l in made[0]["legs"]))
        self.assertTrue(parlay.meets_rules(made[0], {"nfl"}))

    def potd(self, docs, now=NOW, state=None):
        state = state if state is not None else {"days": []}
        parlay.step(state, docs, now, sports=parlay.ALL_SPORTS, rules=POTD)
        return state, [e for e in state["days"] if e.get("legs")]

    def test_parlay_of_the_day_pays_3x_and_over_half(self):
        R = POTD
        # 56.25% by the model at 30.25c (3.31x): made
        self.assertIsNotNone(parlay.choose(parlay.candidates(self.docs(pick("1", "g1", 0.75, 0.55), pick("2", "g2", 0.75, 0.55)), NOW, rules=R), R["bands"][0], R))
        # exactly 50% is not over 50%
        self.assertIsNone(parlay.choose(parlay.candidates(self.docs(pick("1", "g1", 0.8, 0.55), pick("2", "g2", 0.625, 0.55)), NOW, rules=R), R["bands"][0], R))
        # 56.25% but 36c: pays only 2.78x
        self.assertIsNone(parlay.choose(parlay.candidates(self.docs(pick("1", "g1", 0.75, 0.60), pick("2", "g2", 0.75, 0.60)), NOW, rules=R), R["bands"][0], R))
        # no top on the payout: 19.8c pays 5.05x, still fine (the model bands stop at 4.5x)
        got = parlay.choose(parlay.candidates(self.docs(pick("1", "g1", 0.75, 0.45), pick("2", "g2", 0.75, 0.44)), NOW, rules=R), R["bands"][0], R)
        self.assertGreater(1 / got["price"], 5)

    def test_parlay_of_the_day_skips_nhl_assist_unders_and_takes_sellable_nba_unders(self):
        d = [("nba", doc(pick("u", "b1", 0.8, 0.5), pick("o", "b2", 0.8, 0.5, side="over", stat="pts"),
                         pick("un", "b3", 0.8, 0.5, pp=None),          # no Polymarket price (the side can't be bought)
                         pick("ut", "b4", 0.8, 0.5, pd=10),            # under $25 offered there
                         pick("uh", "b5", 0.8, 0.5, th=1))),           # thin
             ("nhl", doc(pick("a", "h1", 0.8, 0.5, stat="a"), pick("ao", "h2", 0.8, 0.5, stat="a", side="over"),
                         pick("g", "h3", 0.8, 0.5)))]
        legs = parlay.candidates(d, NOW, sports=parlay.ALL_SPORTS, rules=POTD)
        # NBA unders are back (Oct 28) when Polymarket sells them with $25+; combos.py still drops assists when Polymarket does
        self.assertEqual(sorted(l["pid"] for l in legs), ["ao", "g", "o", "u"])
        self.assertEqual(len(parlay.candidates(d, NOW, sports={"nba", "nhl"})), 5)   # the model tracks keep their own rules
        leg = lambda s, pid, side, stat="g": {"key": [s, "g", pid], "sport": s, "pid": pid, "gid": "g" + pid, "stat": stat, "side": side,
                                               "start": "2026-10-17T00:00Z", "prob": 0.75, "price": 0.55, "player": "P" + pid, "venue": "Polymarket"}
        made = dict(model=0.5625, price=0.3025, band=0, date="2026-10-16", n=1, res=None, legs=[leg("nba", "x", "over", "pts"), leg("nhl", "y", "under")])
        self.assertTrue(parlay.meets_rules(made, parlay.ALL_SPORTS, POTD))
        self.assertTrue(parlay.meets_rules(dict(made, legs=[leg("nba", "x", "under", "pts"), leg("nhl", "y", "under")]), parlay.ALL_SPORTS, POTD))
        self.assertFalse(parlay.meets_rules(dict(made, legs=[leg("nba", "x", "over", "pts"), leg("nhl", "y", "under", "a")]), parlay.ALL_SPORTS, POTD))
        self.assertFalse(parlay.meets_rules(dict(made, model=0.5), parlay.ALL_SPORTS, POTD))

    def test_parlay_of_the_day_one_a_day_from_any_sport_frozen_and_graded(self):
        rows = {"nhl": [pick("1", "h1", 0.75, 0.55), pick("3", "h3", 0.80, 0.50)],
                "nba": [pick("2", "b2", 0.75, 0.55, side="over", stat="pts"), pick("4", "b4", 0.80, 0.50, side="over", stat="reb")]}
        d = [(s, doc(*r)) for s, r in rows.items()]
        state, made = self.potd(d, datetime.datetime(2026, 10, 16, 14, 0, tzinfo=UTC))   # 10 AM ET: not yet
        self.assertEqual(made, [])
        state, made = self.potd(d)
        self.assertEqual([(e["n"], e["band"]) for e in made], [(1, 0)])                # one a day
        self.assertGreater(made[0]["model"], 0.5)
        self.assertGreaterEqual(1 / made[0]["price"], 3)
        first = [l["key"] for l in made[0]["legs"]]
        more = d + [("mlb", doc(pick("9", "m9", 0.9, 0.5), pick("8", "m8", 0.9, 0.5)))]
        _, made = self.potd(more, NOW + datetime.timedelta(hours=1), state)
        self.assertEqual([[l["key"] for l in e["legs"]] for e in made], [first])     # frozen: no second, no swap
        res = {"1": "hit", "2": "hit", "3": "hit", "4": "miss"}
        graded = [(s, doc(*[r[:13] + [res[r[2]]] + r[14:] for r in rs])) for s, rs in rows.items()]
        parlay.grade(made[0], graded, "2026-10-17")
        self.assertIn(made[0]["res"], ("hit", "miss"))
        self.assertEqual(made[0]["res"], "miss" if any(res[l["pid"]] == "miss" for l in made[0]["legs"]) else "hit")

    def test_parlay_of_the_day_never_shares_a_player_with_3_picks(self):
        rows = [pick("1", "h1", 0.75, 0.55), pick("2", "h2", 0.75, 0.55), pick("3", "h3", 0.75, 0.55)]
        state = {"days": []}
        parlay.step(state, self.docs(*rows), NOW, sports=parlay.ALL_SPORTS, rules=POTD, avoid={("nhl", "1")})
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual(len(made), 1)
        self.assertNotIn("1", [l["pid"] for l in made[0]["legs"]])                      # 3 Picks of the Day has player 1
        # a 3 Picks pick turns up later with one of its players (say, a locked day put back): remade before its games
        taken = made[0]["legs"][0]["pid"]
        parlay.step(state, self.docs(*rows), NOW + datetime.timedelta(minutes=10), sports=parlay.ALL_SPORTS,
                    rules=POTD, avoid={("nhl", taken)})
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual(len(made), 1)
        self.assertNotIn(taken, [l["pid"] for l in made[0]["legs"]])

    def test_parlay_of_the_day_lock_keeps_it_as_locked(self):
        rows = [pick("1", "h1", 0.75, 0.55), pick("2", "h2", 0.75, 0.55), pick("3", "h3", 0.75, 0.55)]
        state, made = self.potd(self.docs(*rows))
        held = json.loads(json.dumps(made[0]))
        locks = {"2026-10-16": {"date": "2026-10-16", "at": "2026-10-16T16:00:00Z", "parlay": held}}
        later = NOW + datetime.timedelta(minutes=10)
        taken = held["legs"][0]["pid"]
        parlay.step(state, self.docs(*rows), later, sports=parlay.ALL_SPORTS, rules=POTD,
                    avoid={("nhl", taken)}, locks=locks)                                # would be remade unlocked
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([[l["key"] for l in e["legs"]] for e in made], [[l["key"] for l in held["legs"]]])
        self.assertEqual(made[0]["locked"], "2026-10-16T16:00:00Z")
        state["days"] = [e for e in state["days"] if e["date"] != "2026-10-16"]          # remade or lost after locking
        parlay.step(state, self.docs(*rows), later, sports=parlay.ALL_SPORTS, rules=POTD, locks=locks)
        made = [e for e in state["days"] if e.get("legs")]
        self.assertEqual([[l["key"] for l in e["legs"]] for e in made], [[l["key"] for l in held["legs"]]])   # put back
        self.assertEqual((made[0]["res"], made[0]["locked"]), (None, "2026-10-16T16:00:00Z"))
        parlay.step(state, self.docs(*rows), datetime.datetime(2026, 10, 16, 23, 40, tzinfo=UTC), sports=parlay.ALL_SPORTS,
                    rules=POTD, locks=locks)
        self.assertFalse(any(e.get("closed") for e in state["days"]))                    # never closed
        parlay.step(state, self.docs(*rows), later, sports=parlay.ALL_SPORTS, rules=POTD,
                    avoid={("nhl", taken)}, locks={})                                   # unlocked: back to the rules
        made = [e for e in state["days"] if e.get("legs")]
        self.assertNotIn("locked", made[0])
        self.assertNotIn(taken, [l["pid"] for l in made[0]["legs"]])

    def test_parlay_of_the_day_lock_never_swaps_a_started_parlay(self):
        rows = [pick("1", "h1", 0.75, 0.55), pick("2", "h2", 0.75, 0.55), pick("3", "h3", 0.75, 0.55)]
        state, made = self.potd(self.docs(*rows))
        other = json.loads(json.dumps(made[0]))
        other["legs"][0]["key"] = ["nhl", "x", "other"]
        locks = {"2026-10-16": {"date": "2026-10-16", "at": "2026-10-16T16:00:00Z", "parlay": other}}
        started = datetime.datetime(2026, 10, 17, 1, 0, tzinfo=UTC)                     # its games are on
        parlay.step(state, self.docs(*rows), started, sports=parlay.ALL_SPORTS, rules=POTD, locks=locks)
        self.assertEqual([[l["key"] for l in e["legs"]] for e in state["days"] if e.get("legs")], [[l["key"] for l in made[0]["legs"]]])

    def test_unreadable_parlay_locks_never_remake(self):
        rows = [pick("1", "h1", 0.75, 0.55), pick("2", "h2", 0.75, 0.55), pick("3", "h3", 0.75, 0.55)]
        state, made = self.potd(self.docs(*rows))
        first = [l["key"] for l in made[0]["legs"]]
        parlay.step(state, self.docs(*rows), NOW + datetime.timedelta(minutes=10), sports=parlay.ALL_SPORTS,
                    rules=POTD, avoid={("nhl", made[0]["legs"][0]["pid"])}, locks=None)
        self.assertEqual([[l["key"] for l in e["legs"]] for e in state["days"] if e.get("legs")], [first])   # might be locked: kept

    def test_tpod_players_read_from_its_file(self):
        import os, tempfile, json, team_stats
        doc = {"days": [{"date": "2026-10-15", "picks": [{"sport": "nhl", "pid": "old"}]},
                        {"date": "2026-10-16", "picks": [{"sport": "nba", "pid": "9"}, {"sport": "nhl", "pid": "8"}]}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tpod.enc")
            with open(path, "w", encoding="ascii") as f:
                f.write(team_stats.encrypt(json.dumps(doc), "pw"))
            self.assertEqual(parlay.tpod_players("pw", "2026-10-16", path), {("nba", "9"), ("nhl", "8")})
            self.assertEqual(parlay.tpod_players("pw", "2026-10-16", os.path.join(d, "none.enc")), set())

    def test_parlay_payday_starts_at_day_1_on_oct_28(self):
        self.assertEqual(parlay.PAYDAY_START, "2026-10-28")
        now = datetime.datetime(2026, 10, 28, 16, 0, tzinfo=UTC)                        # 12:00 PM ET, Oct 28
        old = {"date": "2026-10-27", "n": 1, "band": 0, "model": 0.52, "price": 0.27, "res": "hit", "units": 2.7,
               "legs": [{"sport": "nhl", "pid": "z", "key": ["nhl"], "player": "Old", "side": "over", "line": 0.5, "stat": "g"}]}
        state = {"days": [old]}
        rows = [pick("1", "h1", 0.75, 0.55, start="2026-10-29T00:00Z"), pick("2", "h2", 0.75, 0.55, start="2026-10-29T00:00Z")]
        self.assertTrue(parlay.step(state, self.docs(*rows), now, sports=parlay.ALL_SPORTS, rules=parlay.POTD_RULES))
        self.assertEqual([e["date"] for e in state["days"]], ["2026-10-28"])            # Oct 27 dropped: the series starts over
        e = state["days"][0]
        self.assertTrue(e["script"].startswith("This is day 1 of Parlay Payday"))
        self.assertNotIn("Yesterday", e["script"])
        self.assertIn("Leg one: NHL, P1, no goals.", e["script"])
        self.assertIn("Eighteen and over only", e["script"])
        self.assertTrue(e["caption"].startswith("Parlay Payday, day 1 (Oct 28): 2-leg parlay paying 3.31x"))
        self.assertIn("1) P1 under 0.5 goals", e["caption"])
        self.assertIn("#ParlayPayday", e["caption"])
        self.assertFalse(parlay.step(state, self.docs(*rows), now + datetime.timedelta(minutes=10),
                                     sports=parlay.ALL_SPORTS, rules=parlay.POTD_RULES))  # nothing new: no rewrite

    def test_parlay_payday_script_reads_the_last_result_and_series_total(self):
        leg = lambda pid, side, line, stat, sport="nba": {"sport": sport, "pid": pid, "player": "P" + pid, "side": side, "line": line, "stat": stat}
        past = [{"date": "2026-10-28", "legs": [leg("a", "over", 0.5, "g")], "res": "hit", "units": 2.5, "price": 0.286},
                {"date": "2026-10-29", "legs": [leg("b", "over", 0.5, "g")], "res": "miss", "units": -1.0, "price": 0.3},
                {"date": "2026-10-30", "closed": True}]
        today = {"date": "2026-10-31", "model": 0.534, "price": 0.25,
                 "legs": [leg("1", "over", 24.5, "pts"), leg("2", "under", 8.5, "reb"), leg("3", "over", 0.5, "sog", "nhl")]}
        script, caption = parlay.payday_script(today, past, "2026-10-31")
        self.assertTrue(script.startswith("This is day 3 of Parlay Payday"))           # days with a parlay: the 28th, 29th, today
        self.assertIn("Thursday's parlay missed, that's -1 unit, bringing the series total to +1.5 units.", script)
        self.assertIn("3 legs and pays about 4.0 times your money", script)
        self.assertIn("Leg one: NBA, P1, at least 25 points.", script)
        self.assertIn("Leg two: NBA, P2, 8 or fewer rebounds.", script)
        self.assertIn("Leg three: NHL, P3, at least one shot on goal.", script)
        self.assertIn("53 percent", script)
        self.assertIn("Thursday: missed (-1 unit) | Series: +1.5 units", caption)
        script, caption = parlay.payday_script({"date": "2026-10-31", "closed": True}, past, "2026-10-31")
        self.assertTrue(script.startswith("No Parlay Payday today"))
        self.assertIn("18+", caption)

    def test_parlay_of_the_day_closes_at_730(self):
        state, _ = self.potd([("nhl", doc())], datetime.datetime(2026, 10, 16, 23, 40, tzinfo=UTC))
        self.assertTrue(state["days"][0]["closed"])

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
        potd = edge_report.parlay_rows({"days": state["days"][:2]}, "parlay-potd")   # Parlay of the Day: its own row
        out = {s["key"]: s for s in edge_report.build(rows + potd, "2026-10-16")}
        self.assertEqual((out["parlays"]["n"], out["parlay-potd"]["n"], out["parlay-potd"]["units"]), (2, 2, 2.0))
        self.assertEqual(edge_report.build([], "2026-10-16")[[s["key"] for s in edge_report.build([], "2026-10-16")].index("parlay-potd")]["verdict"],
                         "Waiting for games")


if __name__ == "__main__":
    unittest.main()

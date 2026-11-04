"""Tests for arbs.py: the Polymarket US / Kalshi arbitrage finder (no network)."""
import datetime
import json
import os
import shutil
import tempfile
import unittest

import arbs

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 4, 22, 0, tzinfo=UTC)
key = lambda s: s.lower().replace(".", "").strip()


def kal(player="Jalen Brunson", sk="pts", line=24.5, date="2026-11-04", over=0.55, under=0.50, tradeable=True):
    return {"player": player, "sk": sk, "line": line, "date": date, "over": over, "under": under,
            "tradeable": tradeable, "ticker": f"KX-{player}-{line}-{date}", "od": 50.0, "ud": 50.0}


def quote(player="Jalen Brunson", sk="pts", line=24.5, dates=("2026-11-04",), over=0.45, under=0.58):
    return {"player": player, "sk": sk, "line": line, "dates": list(dates), "over": over, "under": under, "slug": "pm-slug"}


def pm_book(offers, bids):
    """Polymarket US marketData: offers/bids as [(px, qty)] of Yes."""
    return {"offers": [{"px": {"value": str(p)}, "qty": str(q)} for p, q in offers],
            "bids": [{"px": {"value": str(p)}, "qty": str(q)} for p, q in bids]}


def k_book(yes_bids, no_bids):
    return {"orderbook_fp": {"yes_dollars": [[str(p), str(q)] for p, q in yes_bids],
                             "no_dollars": [[str(p), str(q)] for p, q in no_bids]}}


class Fees(unittest.TestCase):
    def test_fee_formula(self):
        self.assertAlmostEqual(arbs.fee("K", 0.5), 0.0175)
        self.assertAlmostEqual(arbs.fee("P", 0.5, 100), 1.25)     # $1.25 per 100 contracts at 50c
        self.assertAlmostEqual(arbs.fee("K", 0.9), 0.07 * 0.9 * 0.1)

    def test_order_fee_rounds_up_to_the_cent(self):
        self.assertEqual(arbs.order_fee("K", [(0.5, 1)]), 0.02)    # 1.75c -> 2c
        self.assertEqual(arbs.order_fee("K", [(0.5, 100)]), 1.75)
        self.assertEqual(arbs.order_fee("P", [(0.5, 40), (0.6, 10)]), 0.62)   # 0.50 + 0.12 = 0.62 exactly

    def test_return_is_on_the_money_staked(self):
        self.assertAlmostEqual(arbs.ret(0.98), 1 / 0.98 - 1)
        self.assertLess(arbs.ret(1.0), arbs.MIN_RET)


class Pairing(unittest.TestCase):
    def test_same_player_stat_line_and_date_only(self):
        mk = [kal(), kal(line=25.5), kal(date="2026-11-05"), kal(player="Josh Hart")]
        prs = arbs.pair([quote()], mk, key)
        self.assertEqual(len(prs), 1)
        p = prs[0]
        self.assertEqual((p["line"], p["date"]), (24.5, "2026-11-04"))
        self.assertEqual(p["P"], {"over": 0.45, "under": 0.58, "slug": "pm-slug"})
        self.assertEqual(p["K"]["over"], 0.55)
        self.assertEqual(p["K"]["under"], 0.50)

    def test_no_match_on_another_line_or_day(self):
        self.assertEqual(arbs.pair([quote(line=23.5)], [kal()], key), [])
        self.assertEqual(arbs.pair([quote(dates=("2026-11-05",))], [kal()], key), [])   # a back-to-back's other game
        self.assertEqual(arbs.pair([quote(dates=())], [kal()], key), [])

    def test_untradeable_kalshi_has_no_price(self):
        p = arbs.pair([quote()], [kal(tradeable=False)], key)[0]
        self.assertIsNone(p["K"]["over"])
        self.assertEqual(arbs.combos(p), [])

    def test_combos_cheapest_side_first(self):
        p = arbs.pair([quote()], [kal()], key)[0]
        cs = arbs.combos(p)
        self.assertEqual((cs[0]["over"], cs[0]["under"]), ("P", "K"))    # 45c over + 50c under
        self.assertAlmostEqual(cs[0]["cost"], round(0.45 + 0.50 + 0.05 * 0.45 * 0.55 + 0.0175, 4))
        self.assertEqual((cs[1]["over"], cs[1]["under"]), ("K", "P"))    # 55c + 58c: no arb
        self.assertGreater(cs[1]["cost"], 1)

    def test_candidates_split_under_a_dollar(self):
        prs = arbs.pair([quote(), quote(player="Josh Hart", over=0.52)], [kal(), kal(player="Josh Hart")], key)
        cands, near = arbs.candidates(prs)
        self.assertEqual([c["player"] for c in cands], ["Jalen Brunson"])
        self.assertEqual([c["player"] for c in near], ["Josh Hart"])
        self.assertEqual(cands[0]["ticker"], "KX-Jalen Brunson-24.5-2026-11-04")

    def test_from_games_skips_the_global_book(self):
        games = [{"date": "2026-11-04", "markets": [
            {"pm": {"player": "A", "statText": "Points", "line": 9.5, "over": 0.4, "under": 0.6, "us": "s1"}},
            {"pm": {"player": "B", "statText": "Points", "line": 9.5, "over": 0.4, "under": 0.6}},          # global book
            {"pm": {"player": "C", "sk": "h", "line": 0.5, "over": 0.4, "under": 0.6, "us": "s2"}}]}]
        qs = arbs.from_games(games, lambda t: "pts" if t == "Points" else None)
        self.assertEqual([(q["player"], q["sk"], q["dates"]) for q in qs], [("A", "pts", ["2026-11-04"]), ("C", "h", ["2026-11-04"])])

    def test_from_pmus_cents_to_fractions(self):
        qs = arbs.from_pmus({("joe", "rec_yds", 49.5): {"over": 47, "under": None, "slug": "s", "who": "Joe", "dates": ["2026-11-08"]},
                             ("amy", "rec", 3.5): {"over": 40, "under": 60, "slug": None}})
        self.assertEqual(qs, [{"player": "Joe", "sk": "rec_yds", "line": 49.5, "dates": ["2026-11-08"],
                               "over": 0.47, "under": None, "slug": "s"}])


class Note(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_writes_the_pairs_and_load_notes_reads_them_back(self):
        n = arbs.note("nba", [quote()], [kal()], key, now=NOW, folder=self.dir)
        self.assertEqual(n, 1)
        notes = arbs.load_notes(NOW + datetime.timedelta(minutes=5), folder=self.dir)
        self.assertEqual(notes["nba"]["n"], 1)
        self.assertEqual(len(notes["nba"]["cands"]), 1)
        self.assertEqual(arbs.load_notes(NOW + datetime.timedelta(minutes=arbs.FRESH_MIN + 1), folder=self.dir), {})

    def test_never_raises(self):
        self.assertEqual(arbs.note("nba", [quote()], None, key, folder=self.dir), 0)       # Kalshi unreachable
        self.assertEqual(arbs.note("nba", [{"dates": ["2026-11-04"]}], [kal()], key, folder=self.dir), 0)   # no player
        self.assertFalse(os.path.exists(os.path.join(self.dir, "nba.json")))


class Books(unittest.TestCase):
    def test_levels(self):
        pm = arbs.pm_levels(pm_book([(0.46, 10), (0.45, 100)], [(0.40, 50)]))
        self.assertEqual(pm["over"], [(0.45, 100.0), (0.46, 10.0)])
        self.assertAlmostEqual(pm["under"][0][0], 0.60)
        k = arbs.kalshi_levels(k_book(yes_bids=[(0.50, 80)], no_bids=[(0.45, 30)]))
        self.assertAlmostEqual(k["over"][0][0], 0.55)     # buy Yes at 1 - No bid
        self.assertAlmostEqual(k["under"][0][0], 0.50)    # buy No at 1 - Yes bid

    def test_fill_stops_when_the_next_pair_is_under_one_percent(self):
        over = [(0.45, 100.0), (0.47, 500.0)]              # 47c + 50c + fees ~ $1.00: not worth it
        under = [(0.50, 300.0)]
        r = arbs.fill(over, "P", under, "K")
        self.assertEqual(r["n"], 100)
        self.assertEqual((r["usd_o"], r["usd_u"]), (45.0, 50.0))
        self.assertEqual(r["fees"], arbs.order_fee("P", [(0.45, 100)]) + arbs.order_fee("K", [(0.50, 100)]))
        self.assertAlmostEqual(r["profit"], round(100 - r["cost"], 2))
        self.assertGreaterEqual(r["ret"], arbs.MIN_RET)

    def test_fill_none_without_an_arb(self):
        self.assertIsNone(arbs.fill([(0.50, 100.0)], "P", [(0.50, 100.0)], "K"))
        self.assertIsNone(arbs.fill([], "P", [(0.40, 100.0)], "K"))

    def cand(self):
        return {"sport": "nba", "player": "Jalen Brunson", "sk": "pts", "line": 24.5, "date": "2026-11-04",
                "over": "P", "under": "K", "slug": "pm-slug", "ticker": "KX", "cost": 0.98}

    def test_judge_real_thin_and_gone(self):
        deep = {"P": {"over": [(0.45, 100.0)], "under": []}, "K": {"over": [], "under": [(0.50, 100.0)]}}
        a, why = arbs.judge(self.cand(), deep)
        self.assertIsNone(why)
        self.assertEqual((a["po"], a["pu"], a["over"], a["under"]), (0.45, 0.50, "P", "K"))
        thin = {"P": {"over": [(0.45, 20.0)], "under": []}, "K": {"over": [], "under": [(0.50, 100.0)]}}   # $9 on the over
        self.assertEqual(arbs.judge(self.cand(), thin), (None, "thin"))
        sliver = {"P": {"over": [(0.11, 55.0)], "under": []}, "K": {"over": [], "under": [(0.86, 0.28), (0.94, 100.0)]}}
        self.assertEqual(arbs.judge(self.cand(), sliver), (None, "thin"))    # live Nov 4: 24c of an 86c under, then 94c
        gone = {"P": {"over": [(0.49, 100.0)], "under": []}, "K": {"over": [], "under": [(0.50, 100.0)]}}
        self.assertEqual(arbs.judge(self.cand(), gone), (None, "gone"))

    def test_check_marks_unreadable_books(self):
        def reader(c):
            if c["player"] == "X":
                raise OSError("403")
            return {"P": {"over": [(0.45, 100.0)], "under": []}, "K": {"over": [], "under": [(0.50, 100.0)]}}
        found, misses = arbs.check([self.cand(), {**self.cand(), "player": "X"}], reader=reader, workers=1)
        self.assertEqual([a["player"] for a in found], ["Jalen Brunson"])
        self.assertEqual([(m["player"], m["why"]) for m in misses], [("X", "unread")])


class State(unittest.TestCase):
    def arb(self, ret=0.02, profit=2.0):
        return {"sport": "nba", "player": "Jalen Brunson", "sk": "pts", "line": 24.5, "date": "2026-11-04",
                "over": "P", "under": "K", "ret": ret, "profit": profit, "cost": 95.0}

    def test_log_tracks_first_last_and_best(self):
        st = {}
        notes = {"nba": {"n": 40, "cands": [{}], "near": [{"player": "Y", "cost": 1.01}]}}
        self.assertTrue(arbs.step(st, notes, [self.arb()], [], NOW))
        later = NOW + datetime.timedelta(minutes=10)
        self.assertTrue(arbs.step(st, notes, [self.arb(ret=0.03, profit=1.0)], [], later))
        self.assertEqual(len(st["log"]), 1)
        e = st["log"][0]
        self.assertEqual((e["first"], e["last"], e["runs"], e["best"], e["profit"]),
                         ("2026-11-04T22:00:00Z", "2026-11-04T22:10:00Z", 2, 0.03, 2.0))
        self.assertEqual(st["scan"], {"nba": {"n": 40, "cands": 1}})
        self.assertEqual(st["near"][0]["why"], "quote")

    def test_no_change_and_old_entries_dropped(self):
        st = {"gen": "x"}
        arbs.step(st, {}, [], [], NOW)
        self.assertFalse(arbs.step(st, {}, [], [], NOW + datetime.timedelta(minutes=10)))
        st["log"] = [{"id": "old", "last": "2026-09-01T00:00:00Z", "first": "2026-09-01T00:00:00Z"}]
        self.assertTrue(arbs.step(st, {}, [], [], NOW))
        self.assertEqual(st["log"], [])

    def test_state_round_trips_as_json(self):
        st = {}
        arbs.step(st, {}, [self.arb()], [], NOW)
        self.assertEqual(json.loads(json.dumps(st))["now"][0]["player"], "Jalen Brunson")


if __name__ == "__main__":
    unittest.main()

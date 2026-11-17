import datetime
import unittest

import edge_report
import roi4

UTC = datetime.timezone.utc


def pick(**kw):
    p = {"src": "live", "gid": "G1", "pid": "P1", "player": "A Player", "stat": "rec", "line": 4.5, "side": "over",
         "prob": 0.70, "price": 0.55, "px0": 0.55, "lists": "", "vn": "P", "th": None, "hd": None, "pj": None,
         "date": "2026-11-15", "start": "2026-11-15T18:00Z", "lk": None, "res": None}
    p.update(kw)
    return p


def cand(**kw):
    sport = kw.pop("sport", "nfl")
    c = roi4.candidate(sport, pick(**kw))
    assert c is not None, kw
    return c


def history(sport="nfl", days=12, per_day=30, win_every=2, price=0.55, prob=0.70, start="2026-11-01"):
    """Graded candidates: per_day picks a day, every win_every-th one a hit (price 0.55, 1 in 2 wins: +36%... per win)."""
    out, d0 = [], datetime.date.fromisoformat(start)
    for d in range(days):
        day = (d0 + datetime.timedelta(days=d)).isoformat()
        for i in range(per_day):
            out.append(cand(sport=sport, gid=f"G{d}-{i % 5}", pid=f"P{i}", date=day, start=day + "T18:00Z",
                            price=price, px0=price, prob=prob, res="hit" if i % win_every == 0 else "miss"))
    return out


class CandidateTest(unittest.TestCase):
    def test_only_buyable_picks(self):
        self.assertIsNotNone(roi4.candidate("nfl", pick()))
        for bad in ({"th": 1}, {"vn": None}, {"hd": "X (day-to-day)"}, {"pj": 1}, {"prob": None}, {"src": "sim"},
                    {"price": 0.05, "px0": 0.05}, {"price": 0.80, "px0": 0.30}, {"price": None}):
            self.assertIsNone(roi4.candidate("nfl", pick(**bad)), bad)

    def test_nfl_cents_and_day(self):
        c = roi4.candidate("nfl", pick(price=55, px0=54, start=None, date="2026-11-16"))
        self.assertAlmostEqual(c["pr"], 0.55)
        self.assertEqual(c["day"], "2026-11-16")

    def test_dedupe_keeps_best_line(self):
        a = cand(line=3.5, price=0.70, prob=0.80)
        b = cand(line=4.5, price=0.55, prob=0.72)
        other = cand(pid="P2")
        kept = roi4.dedupe([a, b, other])
        self.assertEqual(len(kept), 2)
        self.assertIn(b, kept)


class PlanTest(unittest.TestCase):
    def test_qualifies_on_past_only(self):
        h = history()   # 55c, half of them win: -9%
        p = {s["key"]: s for s in roi4.plan(h, "2026-11-20")}
        self.assertFalse(p["nfl-edge"]["ok"])            # losing: never bet
        good = [dict(c, res="hit" if i % 5 < 3 else "miss") for i, c in enumerate(history())]
        p = {s["key"]: s for s in roi4.plan(good, "2026-11-20")}
        self.assertTrue(p["nfl-edge"]["ok"])             # 60% at 55c: +9%
        self.assertGreater(p["nfl-edge"]["r"], 0)
        self.assertLess(p["nfl-edge"]["r"], p["nfl-edge"]["roi"])   # shrunk toward zero
        early = {s["key"]: s for s in roi4.plan(good, "2026-11-04")}   # only 3 days (90 picks) before then
        self.assertFalse(early["nfl-edge"]["ok"])
        self.assertNotIn("nba-edge", p)                  # no NBA history: not in the plan

    def test_below_target_does_not_qualify(self):
        # 56% at 55c: about +1.8%, profitable but under the 4% target
        h = [dict(c, res="hit" if i % 25 < 14 else "miss") for i, c in enumerate(history(per_day=25))]
        p = {s["key"]: s for s in roi4.plan(h, "2026-11-20")}
        self.assertLess(p["nfl-edge"]["roi"], roi4.TARGET)
        self.assertFalse(p["nfl-edge"]["ok"])


class StakeTest(unittest.TestCase):
    def test_quarter_kelly_capped(self):
        self.assertEqual(roi4.stake_for(0.55, 0), 0.0)
        self.assertEqual(roi4.stake_for(0.55, None), 0.0)
        s = roi4.stake_for(0.55, 0.03)                   # 100 * 0.25 * 0.55*0.03/0.45 = 0.92 -> 0.90
        self.assertAlmostEqual(s, 0.90)
        self.assertEqual(roi4.stake_for(0.95, 0.10), roi4.MAX_BET)
        self.assertEqual(roi4.stake_for(0.15, 0.001), roi4.MIN_BET)
        self.assertGreater(roi4.stake_for(0.75, 0.03), roi4.stake_for(0.40, 0.03))   # surer bets carry more


PLAN = [{"key": "nfl-edge", "sport": "nfl", "ok": True, "r": 0.05, "n": 500, "days": 10, "roi": 0.06, "lo": 0.0, "label": ""},
        {"key": "nba-edge", "sport": "nba", "ok": False, "r": None, "n": 500, "days": 10, "roi": -0.05, "lo": -0.1, "label": ""}]


class ChooseTest(unittest.TestCase):
    def test_only_qualified_segments(self):
        cs = [cand(), cand(sport="nba", pid="N1"), cand(pid="P3", prob=0.58)]   # P3: edge 3 points, no segment
        bets = roi4.choose(cs, PLAN, [])
        self.assertEqual([b["pid"] for b in bets], ["P1"])
        self.assertEqual(bets[0]["seg"], "nfl-edge")
        self.assertEqual(bets[0]["price"], 0.55)
        self.assertIsNone(bets[0]["res"])

    def test_no_bets_without_a_plan(self):
        self.assertEqual(roi4.choose([cand()], [dict(PLAN[0], ok=False, r=None)], []), [])
        self.assertEqual(roi4.choose([cand()], [], []), [])

    def test_never_twice_and_caps(self):
        first = roi4.choose([cand()], PLAN, [])
        self.assertEqual(roi4.choose([cand(), cand(line=5.5, price=0.50, prob=0.65)], PLAN, first), [])   # same prop, other line
        many = [cand(pid=f"P{i}", price=0.80, px0=0.80, prob=0.95) for i in range(20)]   # 1u each, one game
        bets = roi4.choose(many, PLAN, [])
        self.assertAlmostEqual(sum(b["stake"] for b in bets), roi4.GAME_CAP)
        games = [cand(pid=f"P{i}", gid=f"G{i // 5}", price=0.80, px0=0.80, prob=0.95) for i in range(60)]
        bets = roi4.choose(games, PLAN, [])
        self.assertLessEqual(sum(b["stake"] for b in bets), roi4.DAY_CAP + 1e-9)
        self.assertAlmostEqual(sum(b["stake"] for b in bets), roi4.DAY_CAP)


class GradeTest(unittest.TestCase):
    def bet(self, **kw):
        b = roi4.choose([cand()], PLAN, [])[0]
        b.update(kw)
        return b

    def test_settle(self):
        b = self.bet(stake=1.0)
        self.assertTrue(roi4.grade([b], {b["key"]: "hit"}, "2026-11-16"))
        self.assertAlmostEqual(b["pnl"], 0.45 / 0.55, places=3)
        self.assertFalse(roi4.grade([b], {b["key"]: "miss"}, "2026-11-16"))   # graded once, never rewritten
        m = self.bet(stake=0.6)
        roi4.grade([m], {m["key"]: "miss"}, "2026-11-16")
        self.assertEqual((m["res"], m["pnl"]), ("miss", -0.6))
        v = self.bet()
        roi4.grade([v], {v["key"]: "push"}, "2026-11-16")
        self.assertEqual((v["res"], v["pnl"]), ("void", 0.0))

    def test_old_ungraded_void(self):
        b = self.bet()
        self.assertFalse(roi4.grade([b], {}, "2026-11-18"))
        self.assertIsNone(b["res"])
        roi4.grade([b], {}, "2026-11-25")
        self.assertEqual(b["res"], "void")


class StatsTest(unittest.TestCase):
    def test_numbers(self):
        def b(day, res, stake=1.0, price=0.5, sport="nfl", k="x"):
            return {"day": day, "res": res, "stake": stake, "price": price, "sport": sport, "key": day + k,
                    "pnl": stake if res == "hit" else -stake if res == "miss" else 0.0}
        bets = [b("2026-11-01", "hit"), b("2026-11-01", "hit", k="y"), b("2026-11-02", "miss"), b("2026-11-03", "miss"),
                b("2026-11-04", "hit", sport="nhl"), b("2026-11-04", "void", k="v")]
        s = roi4.stats(bets, ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"])
        self.assertEqual((s["n"], s["staked"], s["pnl"]), (5, 5.0, 1.0))
        self.assertAlmostEqual(s["roi"], 0.2)
        self.assertEqual((s["days"], s["days_hit"], s["days_down"], s["no_bet_days"]), (4, 2, 2, 1))
        self.assertEqual((s["max_dd"], s["losing_days_run"], s["losing_bets_run"], s["voids"]), (2.0, 2, 2, 1))
        self.assertEqual(s["by_sport"]["nhl"]["pnl"], 1.0)
        self.assertEqual([d["cum"] for d in s["daily"]], [2.0, 1.0, 0.0, 1.0])
        self.assertEqual(s["worst_day"], -1.0)


class MonthTest(unittest.TestCase):
    def test_monthly_against_the_bank(self):
        def b(day, res, stake=1.0, k="x"):
            return {"day": day, "res": res, "stake": stake, "price": 0.5, "sport": "nfl", "key": day + k,
                    "pnl": stake if res == "hit" else -stake}
        bets = [b("2026-10-30", "hit", 3), b("2026-10-31", "hit", 2), b("2026-11-02", "miss", 2), b("2026-11-08", "hit", 1)]
        s = roi4.stats(bets)
        self.assertEqual([m["month"] for m in s["monthly"]], ["2026-10", "2026-11"])
        oct_, nov = s["monthly"]
        self.assertEqual((oct_["pnl"], oct_["bank"], oct_["days"], oct_["roi"]), (5.0, 0.05, 2, 1.0))   # 5u of a 100u bank
        self.assertEqual((nov["pnl"], nov["bank"]), (-1.0, -0.01))
        self.assertEqual((s["months_hit"], s["months_down"]), (1, 1))
        self.assertEqual(roi4.stats([])["monthly"], [])

    def test_outlook(self):
        daily = [{"day": f"2026-10-{d:02d}", "pnl": p, "staked": 10.0} for d, p in zip(range(1, 11), [3, -2, 1, 2, -1, 4, -3, 2, 1, 0])]
        o = roi4.outlook(daily, 20, sims=2000)
        self.assertEqual(o["bet_days"], 15)                  # 10 betting days in 20 calendar days -> 15 a month
        self.assertEqual(o["staked"], 150.0)
        real, half, none = o["rows"]
        self.assertAlmostEqual(real["roi"], 0.07)
        self.assertAlmostEqual(half["roi"], 0.035)
        self.assertGreater(real["median"], half["median"])
        self.assertGreater(half["median"], none["median"])
        self.assertLess(none["median"], 0)
        self.assertGreater(none["p_down"], real["p_down"])
        self.assertIsNone(roi4.outlook([], 20))
        self.assertEqual(roi4.outlook(daily, 20, sims=2000), o)   # seeded: the frozen numbers never drift


class PostTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 15, 16, 5, tzinfo=UTC)          # 11:05 AM ET
    META = {"links": {("nfl", "G1"): "nfl-aaa-bbb-2026-11-15"}, "nfl_starts": {"G1": "2026-11-15T18:00Z"}}

    def state(self):
        return {"posted": [], "plans": {"2026-11-15": PLAN}}

    def test_posts_at_the_polymarket_price_from_11(self):
        c = cand(date="2026-11-15", start=None, price=0.50, pp=0.55, pd=40, kp=0.50, prob=0.70)
        st = self.state()
        self.assertEqual(roi4.post(st, [c], self.NOW - datetime.timedelta(hours=1), self.META), [])   # 10:05 AM: not yet
        new = roi4.post(st, [c], self.NOW, self.META)
        self.assertEqual(len(new), 1)
        b = new[0]
        self.assertEqual((b["price"], b["vn"]), (0.55, "P"))            # Polymarket's price, not the cheaper Kalshi one
        self.assertEqual(b["url"], "https://polymarket.us/event/nfl-aaa-bbb-2026-11-15")
        self.assertEqual(b["start"], "2026-11-15T18:00Z")                 # NFL kickoff from slate.json
        self.assertEqual(b["max"], 0.60)                                  # model 70%: still 10 points over at 60c
        self.assertEqual(roi4.post(st, [dict(c, pp=0.40)], self.NOW + datetime.timedelta(minutes=10), self.META), [])   # frozen, never twice
        self.assertEqual(st["posted"][0]["price"], 0.55)

    def test_only_buyable_on_polymarket_and_not_too_late(self):
        st = self.state()
        base = dict(date="2026-11-15", start="2026-11-15T18:00Z", prob=0.70)
        for bad in ({"pp": None}, {"pp": 0.55, "pd": 10}, {"pp": 0.55, "pd": 40, "lk": "2026-11-15T17:35Z"},
                    {"pp": 0.55, "pd": 40, "start": "2026-11-15T16:20Z"}, {"pp": 0.65, "pd": 40},     # 15 minutes away; 5 points over only
                    {"pp": 0.55, "pd": 40, "date": "2026-11-16", "start": "2026-11-16T18:00Z"}):
            self.assertEqual(roi4.post(st, [cand(**dict(base, **bad))], self.NOW, self.META), [], bad)

    def test_graded_and_counted_apart(self):
        c = cand(date="2026-11-15", start="2026-11-15T18:00Z", pp=0.55, pd=40, prob=0.70)
        past = [dict(x, res="hit" if i % 5 < 3 else "miss") for i, x in enumerate(history(start="2026-11-01"))]
        st = {}
        roi4.update(st, past + [c], self.NOW, self.META)
        self.assertEqual(len(st["posted"]), 1)
        self.assertEqual(st["bets"], [])                                  # not locked: no at-lock bet yet
        roi4.update(st, past + [dict(c, res="hit")], self.NOW + datetime.timedelta(hours=6), self.META)
        self.assertEqual(st["posted"][0]["res"], "hit")
        self.assertEqual(st["posted_stats"]["n"], 1)
        self.assertEqual(st["season"]["n"], st["backtest"]["stats"]["n"])   # season = backtest + live at-lock bets (none yet)
        rows = edge_report.roi4_rows(st, "posted", "roi4-posted")
        self.assertEqual([r["sport"] for r in rows], ["roi4-posted"])


class LiveTest(unittest.TestCase):
    def test_bettable(self):
        now = datetime.datetime(2026, 11, 15, 17, 40, tzinfo=UTC)
        c = cand(lk="2026-11-15T17:35Z")
        self.assertTrue(roi4.bettable(c, now))
        self.assertFalse(roi4.bettable(cand(), now))                                   # not locked: price can still move
        self.assertFalse(roi4.bettable(c, datetime.datetime(2026, 11, 15, 18, 1, tzinfo=UTC)))   # started
        nfl = cand(start=None, lk="2026-11-15T17:35Z")
        self.assertTrue(roi4.bettable(nfl, now))
        self.assertFalse(roi4.bettable(nfl, datetime.datetime(2026, 11, 15, 17, 55, tzinfo=UTC)))

    def test_update_freezes_and_grades(self):
        past = [dict(c, res="hit" if i % 5 < 3 else "miss") for i, c in enumerate(history(start="2026-11-01"))]
        now = datetime.datetime(2026, 11, 15, 17, 40, tzinfo=UTC)
        today = [cand(date="2026-11-15", lk="2026-11-15T17:35Z"), cand(pid="P9", date="2026-11-15", lk="2026-11-15T17:35Z")]
        state = {}
        self.assertTrue(roi4.update(state, past + today, now))
        self.assertEqual(state["live_from"], "2026-11-15")
        self.assertIn("backtest", state)
        self.assertIn("outlook", state["backtest"])
        self.assertEqual(state["rules"]["month_target"], 0.04)
        self.assertTrue(all(b["day"] < "2026-11-15" for b in state["backtest"]["bets"]))
        self.assertEqual(len(state["bets"]), 2)
        plan_before, bets_before = state["plans"]["2026-11-15"], [dict(b) for b in state["bets"]]
        # a later pass: the price moved and the history changed, but what was bet stays as it was
        later = [dict(c, pr=0.40) for c in today]
        roi4.update(state, [dict(c, res="miss") for c in past] + later, now + datetime.timedelta(minutes=10))
        self.assertEqual(state["plans"]["2026-11-15"], plan_before)
        self.assertEqual(state["bets"], bets_before)
        self.assertEqual(state["backtest"]["bets"][0]["day"] >= "2026-11-01", True)
        done = [dict(c, res="hit") for c in today]
        self.assertTrue(roi4.update(state, past + done, now + datetime.timedelta(hours=5)))
        self.assertTrue(all(b["res"] == "hit" for b in state["bets"]))
        self.assertFalse(roi4.update(state, past + done, now + datetime.timedelta(hours=5)))   # nothing new: no rewrite

    def test_backtest_has_no_lookahead(self):
        # one great day only: the plan for that day can't have seen it, so nothing is bet
        h = [dict(c, res="hit") for c in history(days=1, per_day=200, start="2026-11-10")]
        bets, plans = roi4.backtest(h, "2026-11-20")
        self.assertEqual(bets, [])
        self.assertFalse(any(s["ok"] for s in plans["2026-11-10"]))


class StudyTest(unittest.TestCase):
    def test_every_method_runs_walk_forward(self):
        import roi4_study
        h = [dict(c, res="hit" if i % 5 < 3 else "miss", nw={"om": 30, "p2": 0.8, "roof": "dome", "wx": [60, 12, 0]})
             for i, c in enumerate(history(days=20, per_day=20, start="2026-10-01"))]
        res = roi4_study.study(h, "2026-11-01", test_from="2026-10-10")
        self.assertEqual(res["days"], 11)              # Oct 10-20
        names = [r["name"] for r in res["rows"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any(r["family"] == "Injury news" for r in res["rows"]))
        self.assertTrue(any(r["family"] == "Past performance" and r["n"] for r in res["rows"]))
        few = [r["n"] < roi4_study.FEW for r in res["rows"]]
        self.assertEqual(few, sorted(few))                 # too-few-to-judge methods come last


class EdgeReportTest(unittest.TestCase):
    def test_rows(self):
        doc = {"bets": [{"day": "2026-11-15", "price": 0.55, "res": "hit", "stake": 0.9, "sport": "nfl", "side": "over",
                         "stat": "rec", "line": 4.5},
                        {"day": "2026-11-15", "price": 0.60, "res": "void", "stake": 1, "sport": "nfl"},
                        {"day": "2026-11-16", "price": 0.60, "res": None, "stake": 1, "sport": "nfl"}],
               "backtest": {"bets": [{"day": "2026-11-01", "price": 0.5, "res": "hit", "stake": 1, "sport": "nfl"}]}}
        rows = edge_report.roi4_rows(doc)
        self.assertEqual(len(rows), 1)                     # live bets only, graded, never the backtest
        self.assertEqual((rows[0]["sport"], rows[0]["pr"], rows[0]["win"]), ("roi4", 0.55, True))
        self.assertIn("roi4", edge_report.OWN_ROWS)
        self.assertIn("roi4", [k for k, _, _, _ in edge_report.STRATEGIES])
        self.assertIn("roi4", edge_report.WAITING_KEYS)
        self.assertIn("roi4-posted", [k for k, _, _, _ in edge_report.STRATEGIES])
        self.assertIn("roi4-posted", edge_report.OWN_ROWS)


if __name__ == "__main__":
    unittest.main()

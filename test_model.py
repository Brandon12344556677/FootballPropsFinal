"""Unit tests for the builder's model, grading, market parsing and list assignment.

Run:  python -m unittest discover -s tests -v
Also writes tests/model_cases.json, which tests/model_sync.mjs feeds to the
JavaScript copy of the model in template.html to prove the two agree.
"""
import json, math, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build as B  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

CASES = [
    # (values oldest->newest, line, kind)
    ([61, 80, 45, 102, 77, 66, 90, 58, 71, 84], 60.5, "yards"),
    ([0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0], 0.5, "count"),
    ([5, 5, 5, 5, 5, 5, 5, 5], 4.5, "count"),
    ([5, 5, 5, 5, 5, 5, 5, 5], 5, "count"),            # whole-number line: pushes possible
    ([250, 310, 198, 275, 330, 260, 240, 305, 290, 215, 280, 265, 300, 245, 270, 255, 285, 310, 225, 295, 260, 240], 249.5, "yards"),
    ([12], 10.5, "yards"),
    ([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 0.5, "count"),
    ([3, 7, 2, 9, 4, 6, 8, 1, 5, 6, 7, 3], 4.5, "count"),
    ([33, 40, 28, 35, 41, 30, 38, 36], 33.5, "count"),
]


class ModelTests(unittest.TestCase):
    def test_probabilities_are_sane(self):
        for vals, line, kind in CASES:
            mp = B.model_prob(vals, line, kind)
            self.assertIsNotNone(mp)
            self.assertAlmostEqual(mp["over"] + mp["under"], 1.0, places=9)
            self.assertGreaterEqual(mp["push"], 0.0)
            self.assertLessEqual(mp["lo"], mp["over"])
            self.assertGreaterEqual(mp["hi"], mp["over"])
            self.assertGreater(mp["neff"], 0)
            self.assertLessEqual(mp["neff"], len(vals) + 1e-9)

    def test_empty_returns_none(self):
        self.assertIsNone(B.model_prob([], 10.5, "yards"))

    def test_never_certain(self):
        mp = B.model_prob([100] * 20, 50.5, "yards")
        self.assertGreater(mp["over"], 0.9)
        self.assertLess(mp["over"], 1.0)
        mp = B.model_prob([0] * 20, 0.5, "count")
        self.assertLess(mp["over"], 0.15)
        self.assertGreater(mp["over"], 0.0)

    def test_small_samples_are_shrunk(self):
        one = B.model_prob([90], 60.5, "yards")["over"]
        ten = B.model_prob([90] * 10, 60.5, "yards")["over"]
        self.assertLess(one, ten)
        self.assertLess(one, 0.9)

    def test_recency_matters(self):
        rising = [20, 25, 30, 35, 40, 70, 80, 90, 95, 100]
        falling = list(reversed(rising))
        self.assertGreater(B.model_prob(rising, 60.5, "yards")["over"],
                           B.model_prob(falling, 60.5, "yards")["over"])

    def test_whole_number_line_has_push_mass(self):
        mp = B.model_prob([5] * 8, 5, "count")
        self.assertGreater(mp["push"], 0.3)
        self.assertAlmostEqual(B.model_prob([5] * 8, 5.5, "count")["push"], 0.0, places=9)

    def test_ncdf(self):
        self.assertAlmostEqual(B.ncdf(0), 0.5, places=7)
        self.assertAlmostEqual(B.ncdf(1.959964), 0.975, places=5)
        self.assertAlmostEqual(B.ncdf(-1.959964), 0.025, places=5)

    def test_seed_line(self):
        self.assertEqual(B.seed_line([]), 0.5)
        self.assertEqual(B.seed_line([0, 0, 1, 0]), 0.5)
        self.assertEqual(B.seed_line([60, 70, 80, 65, 75]), 69.5)
        self.assertEqual(B.seed_line([4, 5, 4, 5]), 4.5)     # median 4.5 -> floor(5.0)-0.5

    def test_grade(self):
        self.assertEqual(B.grade_result(70, 60.5, "over"), "hit")
        self.assertEqual(B.grade_result(50, 60.5, "over"), "miss")
        self.assertEqual(B.grade_result(50, 60.5, "under"), "hit")
        self.assertEqual(B.grade_result(60, 60, "under"), "push")

    def test_side_prob(self):
        mp = B.model_prob([10, 12, 9, 11, 13, 10], 20.5, "yards")
        side, prob, lo, hi = B.side_prob(mp)
        self.assertEqual(side, "under")
        self.assertAlmostEqual(prob, mp["under"])
        self.assertAlmostEqual(lo, 1 - mp["hi"])
        self.assertAlmostEqual(hi, 1 - mp["lo"])

    def test_scale_moves_the_distribution(self):
        vals = [61, 80, 45, 102, 77, 66, 90, 58, 71, 84]
        base = B.model_prob(vals, 70.5, "yards")
        up = B.model_prob(vals, 70.5, "yards", scale=1.2)
        down = B.model_prob(vals, 70.5, "yards", scale=0.8)
        self.assertGreater(up["over"], base["over"])
        self.assertLess(down["over"], base["over"])
        self.assertAlmostEqual(up["mean"], base["mean"] * 1.2, places=9)
        self.assertEqual(up["scale"], 1.2)

    def test_write_cases_for_js_sync(self):
        out = []
        for i, (vals, line, kind) in enumerate(CASES):
            scale = [1.0, 1.15, 0.85][i % 3]
            mp = B.model_prob(vals, line, kind, scale)
            out.append({"values": vals, "line": line, "kind": kind, "scale": scale, "expect": mp, "seed": B.seed_line(vals)})
        ctx_cases = []
        hist_rows = [[2025, 1, "X", "REG"] + [0] * 12 + [1, 0, 44.5, -3.0], [2025, 2, "Y", "REG"] + [0] * 12 + [0, 0, 51.0, 6.5],
                     [2025, 3, "Z", "REG"] + [0] * 12 + [1, 0, None, None], [2025, 4, "W", "REG"] + [0] * 12 + [0, 0, 47.5, 1.0]]
        hist = B.hist_context(hist_rows)
        for fam in ("pass", "rush", "rec"):
            for game_pts, game_spr, dr in ((26.0, 4.0, 1.15), (19.5, -7.0, 0.8), (None, None, None), (24.0, 0.0, None)):
                ctx_cases.append({"fam": fam, "hist": hist, "gamePts": game_pts, "gameSpr": game_spr, "defRatio": dr,
                                  "expect": B.context_scale(fam, hist, game_pts, game_spr, dr)})
        with open(os.path.join(HERE, "model_cases.json"), "w", encoding="utf-8") as f:
            json.dump({"model": out, "ctx": ctx_cases, "hist": {"rows": hist_rows, "expect": hist},
                       "CTX": B.CTX, "MODEL": B.MODEL}, f)


class ContextTests(unittest.TestCase):
    ROW = lambda self, tot, spr: [2025, 1, "X", "REG"] + [0] * 12 + [1, 0, tot, spr]

    def test_hist_context(self):
        rows = [self.ROW(44.5, -3.0), self.ROW(51.0, 6.5)]
        h = B.hist_context(rows)
        self.assertGreater(h["pts"], 20.75)          # weighted toward the newer game (28.75)
        self.assertLess(h["pts"], 28.75)
        self.assertEqual(B.hist_context([self.ROW(None, None)]), {"pts": None, "spr": None})
        self.assertEqual(B.hist_context([]), {"pts": None, "spr": None})

    def test_context_scale_directions(self):
        saved = json.loads(json.dumps(B.CTX))
        try:
            B.CTX["betaPts"] = {"pass": 0.5, "rush": 0.5, "rec": 0.5}
            B.CTX["betaSpr"] = {"pass": -0.2, "rush": 0.2, "rec": -0.2}
            B.CTX["gamma"] = {"pass": 0.75, "rush": 0.25, "rec": 0.5}
            hist = {"pts": 24.0, "spr": 0.0}
            self.assertEqual(B.context_scale("pass", hist, None, None, None)["scale"], 1.0)
            self.assertGreater(B.context_scale("pass", hist, 28.0, 0.0, None)["scale"], 1.0)   # more implied points
            self.assertLess(B.context_scale("pass", hist, 20.0, 0.0, None)["scale"], 1.0)
            self.assertLess(B.context_scale("pass", hist, 24.0, 7.0, None)["scale"], 1.0)      # big favorite passes less
            self.assertGreater(B.context_scale("rush", hist, 24.0, 7.0, None)["scale"], 1.0)   # ... and runs more
            self.assertGreater(B.context_scale("rec", hist, None, None, 1.2)["def"], 1.0)      # soft defense
            self.assertLess(B.context_scale("rec", hist, None, None, 0.8)["def"], 1.0)
            self.assertEqual(B.context_scale("pass", hist, 90.0, 0.0, 3.0)["scale"], B.CTX["clampHi"])
            self.assertEqual(B.context_scale("pass", hist, 5.0, 0.0, 0.2)["scale"], B.CTX["clampLo"])
        finally:
            B.CTX.clear()
            B.CTX.update(saved)

    def test_fitted_parameters_are_sane(self):
        for fam in ("pass", "rush", "rec"):
            self.assertGreaterEqual(B.CTX["betaPts"][fam], 0.0)
            self.assertGreaterEqual(B.CTX["gamma"][fam], 0.0)
            self.assertLessEqual(B.CTX["gamma"][fam], 1.0)

    def test_family_and_def_stat(self):
        self.assertEqual(B.stat_family("pass_yds", "QB"), "pass")
        self.assertEqual(B.stat_family("rush_rec_yds", "RB"), "rush")
        self.assertEqual(B.stat_family("rush_rec_yds", "WR"), "rec")
        self.assertEqual(B.stat_family("rec_td", "TE"), "rec")
        self.assertEqual(B.def_stat_for("tgt", "WR"), "rec")
        self.assertEqual(B.def_stat_for("scrim_td", "RB"), "rush_td")
        self.assertIsNone(B.def_stat_for("pass_int", "QB"))

    def test_def_timeline_is_walk_forward(self):
        def row(season, week, pos, opp, gid, yds):
            return {"season": str(season), "week": str(week), "position": pos, "opponent_team": opp, "game_id": gid,
                    "passing_yards": str(yds), "passing_tds": "0", "rushing_yards": "0", "rushing_tds": "0",
                    "receptions": "0", "receiving_yards": "0", "receiving_tds": "0"}
        rows = [row(2024, w, "QB", "DEN", f"2024_{w:02d}_X_DEN", 200) for w in range(1, 18)]      # prior season: 200/gm
        rows += [row(2025, 1, "QB", "DEN", "2025_01_A_DEN", 400), row(2025, 2, "QB", "DEN", "2025_02_B_DEN", 400)]
        rows += [row(2025, 1, "QB", "KC", "2025_01_C_KC", 100), row(2024, 1, "QB", "KC", "2024_01_C_KC", 100)]
        snap = B.build_def_timeline(rows, {2024, 2025})
        before_w1 = snap(2025, 1)["teams"]["DEN"]["QB"]["pass_yds"]
        before_w2 = snap(2025, 2)["teams"]["QB" and "DEN"]["QB"]["pass_yds"]
        before_w3 = snap(2025, 3)["teams"]["DEN"]["QB"]["pass_yds"]
        self.assertAlmostEqual(before_w1, 200.0)                  # nothing played yet: prior season only
        self.assertAlmostEqual(before_w2, (400 + 6 * 200) / 7.0)  # one game blended with 6 games of prior
        self.assertGreater(before_w3, before_w2)
        self.assertIn("pass_yds", snap(2025, 3)["avg"]["QB"])
        self.assertIsNotNone(B.def_ratio(snap(2025, 3), "DEN", "QB", "pass_yds"))
        self.assertIsNone(B.def_ratio(snap(2025, 3), "DEN", "QB", "pass_int"))


class MarketTests(unittest.TestCase):
    def test_parse_market_over_first(self):
        m = {"question": "Josh Allen: Passing Yards O/U 249.5", "outcomes": '["Over","Under"]',
             "outcomePrices": '["0.55","0.45"]', "bestBid": "0.52", "bestAsk": "0.58", "spread": "0.06",
             "liquidityNum": 1200, "volumeNum": 4000, "line": "249.5"}
        pm = B.parse_market(m)
        self.assertEqual(pm["player"], "Josh Allen")
        self.assertEqual(pm["statText"], "Passing Yards")
        self.assertEqual(pm["line"], 249.5)
        self.assertAlmostEqual(pm["over"], 0.58)        # you pay the ask
        self.assertAlmostEqual(pm["under"], 0.48)       # 1 - bid
        self.assertTrue(pm["tradeable"])
        self.assertEqual(B.mkt_stat_key(pm["statText"]), "pass_yds")

    def test_parse_market_under_first_flips_book(self):
        m = {"question": "Saquon Barkley: Rushing Yards O/U 80.5", "outcomes": '["Under","Over"]',
             "outcomePrices": '["0.40","0.60"]', "bestBid": "0.38", "bestAsk": "0.42", "spread": "0.04",
             "liquidityNum": 500, "volumeNum": 100}
        pm = B.parse_market(m)
        self.assertAlmostEqual(pm["over"], 0.62)        # 1 - bid(Under)
        self.assertAlmostEqual(pm["under"], 0.42)       # ask(Under)
        self.assertEqual(pm["line"], 80.5)

    def test_thin_market_is_not_tradeable(self):
        m = {"question": "Some Guy: Receptions O/U 3.5", "outcomes": '["Over","Under"]',
             "outcomePrices": '["0.5","0.5"]', "bestBid": "0.05", "bestAsk": "0.95", "liquidityNum": 10}
        self.assertFalse(B.parse_market(m)["tradeable"])

    def test_rejects_game_totals_and_bad_text(self):
        self.assertIsNone(B.parse_market({"question": "Eagles vs Cowboys: Total Points O/U 47.5"}))
        self.assertIsNone(B.parse_market({"question": "Will it rain?"}))

    def test_stat_text_mapping(self):
        self.assertEqual(B.mkt_stat_key("Rushing + Receiving Yards"), "rush_rec_yds")
        self.assertEqual(B.mkt_stat_key("Receiving Yards"), "rec_yds")
        self.assertEqual(B.mkt_stat_key("Receptions"), "rec")
        self.assertEqual(B.mkt_stat_key("Passing Touchdowns"), "pass_td")
        self.assertIsNone(B.mkt_stat_key("Longest Reception"))

    def test_pkey(self):
        self.assertEqual(B.pkey("Marvin Harrison Jr."), "marvin harrison")
        self.assertEqual(B.pkey("Ja'Marr Chase"), "jamarr chase")
        self.assertEqual(B.pkey("Audric Estimé"), "audric estime")


class ListTests(unittest.TestCase):
    def _pick(self, prob, lo, price=None, neff=12.0):
        return {"prob": prob, "lo": lo, "hi": min(1, prob + 0.1), "neff": neff, "price": price, "lists": ""}

    def test_assign_lists(self):
        picks = [self._pick(0.9, 0.8, 70), self._pick(0.7, 0.6, 65), self._pick(0.55, 0.45, 50),
                 self._pick(0.86, 0.75, None), self._pick(0.7, 0.6, 65, neff=3)]
        B.assign_lists(picks)
        self.assertIn("T", picks[0]["lists"])       # all fit in the top 25 by chance
        self.assertIn("V", picks[0]["lists"])       # price 0.70 >= 0.30, model 20 pts above
        self.assertNotIn("V", picks[1]["lists"])    # only 5 points above 0.65
        self.assertNotIn("V", picks[2]["lists"])    # only 5 points above 0.50
        self.assertNotIn("V", picks[3]["lists"])    # no price
        self.assertNotIn("B", picks[0]["lists"])    # near-locks removed — no B tag anymore
        self.assertNotIn("V", picks[4]["lists"])    # too few effective games

    def test_value_needs_the_market_to_give_it_30_percent(self):
        """The price floor is what keeps penny longshots off the list, however big
        the edge looks in points."""
        longshot = self._pick(0.40, 0.30, 10)       # 30 points of edge, but a 10c ask
        just_under = self._pick(0.60, 0.50, 29)     # 31 points of edge, but 29c < 30c
        ok = self._pick(0.45, 0.35, 30)             # 30c ask, model exactly 15 points up
        B.assign_lists([longshot, just_under, ok])
        self.assertNotIn("V", longshot["lists"])
        self.assertNotIn("V", just_under["lists"])
        self.assertIn("V", ok["lists"])

    def test_value_list_takes_unders_too(self):
        """A pick whose side is 'under' reaches V on its own ask, and a sub-50%
        row can never take a 25 Guaranteed slot."""
        over = self._pick(0.62, 0.55, 70)
        under = dict(self._pick(0.61, 0.54, 45), side="under")
        slim_under = dict(self._pick(0.48, 0.40, 32), side="under")
        B.assign_lists([over, under, slim_under])
        self.assertIn("V", under["lists"])           # 45c ask, model 16 points above
        self.assertIn("V", slim_under["lists"])      # 32c ask, 16 points up, still under 50%
        self.assertNotIn("V", over["lists"])         # model is below the 70c ask
        self.assertNotIn("T", slim_under["lists"])   # 25 Guaranteed is model-favored sides only

    def test_make_pick_can_record_the_other_side(self):
        mp = {"over": 0.62, "under": 0.38, "lo": 0.5, "hi": 0.74, "neff": 12.0, "scale": 1.0}
        pl = {"id": "p1", "n": "A B", "p": "WR", "t": "X"}
        fav = B.make_pick("live", "g", 2026, 1, "2026-09-20", pl, "Y", "rec_yds", 60.5, mp, 55, "now")
        opp = B.make_pick("live", "g", 2026, 1, "2026-09-20", pl, "Y", "rec_yds", 60.5, mp, 30, "now",
                          side="under")
        self.assertEqual(fav["side"], "over")
        self.assertEqual((fav["prob"], fav["lo"], fav["hi"]), (0.62, 0.5, 0.74))
        self.assertEqual(opp["side"], "under")
        self.assertEqual((opp["prob"], opp["lo"], opp["hi"]), (0.38, 0.26, 0.5))

    def _slate_market(self, question, line, bid, ask):
        return {"question": question, "line": line, "outcomes": ["Over", "Under"],
                "outcomePrices": [str(ask), str(1 - bid)], "bestBid": str(bid), "bestAsk": str(ask),
                "spread": "0.02", "liquidityNum": "5000", "volumeNum": "5000"}

    def _live_fixture(self, bid, ask):
        """One scheduled game, one player with 20 identical-ish games, one market."""
        sched = {"2026_02_AAA_BBB": {"id": "2026_02_AAA_BBB", "season": 2026, "week": 2,
                                     "date": "2026-09-20", "away": "AAA", "home": "BBB",
                                     "final": False, "spread": None, "total": None}}
        rows = []
        for i in range(20):
            r = [2026, i + 1, "BBB", "REG"] + [0] * 12 + [0, 0, None, None]
            r[14] = 70 if i % 2 else 50        # rec_yds alternates
            rows.append(r)
        pl = {"id": "p1", "n": "Test Player", "p": "WR", "t": "AAA", "g": rows}
        slate = [{"away": "AAA", "home": "BBB", "date": "2026-09-20",
                  "markets": [self._slate_market("Test Player: Receiving Yards O/U 59.5", 59.5, bid, ask)]}]
        return slate, sched, {B.pkey("Test Player"): pl}

    def test_live_picks_record_the_value_side_as_well(self):
        # The model leans over (53%), but the over costs 71c. The under costs
        # 1 - 0.69 = 31c against a 47% model chance — 16 points of edge on a 31c ask —
        # so the under is recorded alongside the favored side.
        slate, sched, by_key = self._live_fixture(bid=0.69, ask=0.71)
        picks = []
        B.build_live_picks(picks, slate, sched, by_key, {"teams": {}, "avg": {}})
        sides = sorted(p["side"] for p in picks)
        self.assertEqual(sides, ["over", "under"])
        under = next(p for p in picks if p["side"] == "under")
        self.assertIn("V", under["lists"])
        self.assertEqual(under["price"], 31)

    def test_live_picks_prune_a_flipped_side_instead_of_duplicating(self):
        """A pending row on a side we no longer carry is dropped, not left to grade."""
        slate, sched, by_key = self._live_fixture(bid=0.40, ask=0.60)
        stale = {"src": "live", "gid": "2026_02_AAA_BBB", "pid": "p1", "stat": "rec_yds",
                 "line": 59.5, "side": "under", "res": None, "lists": "V", "prob": 0.5}
        picks = [stale]
        B.build_live_picks(picks, slate, sched, by_key, {"teams": {}, "avg": {}})
        self.assertNotIn(stale, picks)
        self.assertEqual([p["side"] for p in picks], ["over"])

    def test_live_picks_keep_a_graded_row_on_the_other_side(self):
        slate, sched, by_key = self._live_fixture(bid=0.40, ask=0.60)
        graded = {"src": "live", "gid": "2026_02_AAA_BBB", "pid": "p1", "stat": "rec_yds",
                  "line": 59.5, "side": "under", "res": "hit", "lists": "V", "prob": 0.5}
        picks = [graded]
        B.build_live_picks(picks, slate, sched, by_key, {"teams": {}, "avg": {}})
        self.assertIn(graded, picks)

    def test_live_picks_prefer_the_polymarket_us_price(self):
        """Polymarket US quotes both sides properly; the global book's Under price is
        derived from a one-sided book and runs rich, so US wins when it lists the same
        prop at the same line."""
        slate, sched, by_key = self._live_fixture(bid=0.40, ask=0.60)
        us = {(B.pkey("Test Player"), "rec_yds", 59.5): {"over": 41, "under": 60}}
        picks = []
        B.build_live_picks(picks, slate, sched, by_key, {"teams": {}, "avg": {}}, us)
        over = next(p for p in picks if p["side"] == "over")
        self.assertEqual(over["price"], 41)          # US ask, not the global book's 60c

    def test_live_picks_ignore_a_us_price_for_a_different_line(self):
        """A price for 49.5 says nothing about 59.5 — it is a different bet."""
        slate, sched, by_key = self._live_fixture(bid=0.40, ask=0.60)
        us = {(B.pkey("Test Player"), "rec_yds", 49.5): {"over": 41, "under": 60}}
        picks = []
        B.build_live_picks(picks, slate, sched, by_key, {"teams": {}, "avg": {}}, us)
        over = next(p for p in picks if p["side"] == "over")
        self.assertEqual(over["price"], 60)          # falls back to the global book

    def test_grade_picks_waits_for_box_score(self):
        sched = {"2026_01_A_B": {"final": True}}
        pl = {"id": "p1", "g": [[2026, 1, "B", "REG"] + [0] * 12 + [1, 0, 44.5, 1.5]]}
        pl["g"][0][14] = 77   # rec_yds
        pick = {"src": "live", "gid": "2026_01_A_B", "season": 2026, "week": 1, "pid": "p1",
                "stat": "rec_yds", "line": 60.5, "side": "over", "res": None, "actual": None}
        self.assertEqual(B.grade_picks([pick], sched, {"p1": pl}, set()), 0)     # stats not in yet
        self.assertEqual(B.grade_picks([pick], sched, {"p1": pl}, {"2026_01_A_B"}), 1)
        self.assertEqual(pick["res"], "hit")
        self.assertEqual(pick["actual"], 77)
        dnp = dict(pick, pid="nobody", res=None, actual=None)
        B.grade_picks([dnp], sched, {"p1": pl}, {"2026_01_A_B"})
        self.assertEqual(dnp["res"], "dnp")


class SeasonTests(unittest.TestCase):
    def test_season_year(self):
        import datetime
        self.assertEqual(B.season_year(datetime.date(2026, 9, 11)), 2026)
        self.assertEqual(B.season_year(datetime.date(2027, 1, 20)), 2026)
        self.assertEqual(B.season_year(datetime.date(2027, 7, 1)), 2026)
        self.assertEqual(B.season_year(datetime.date(2027, 8, 15)), 2027)


class PolymarketUSTests(unittest.TestCase):
    def test_event_slug(self):
        self.assertEqual(B.pmus_event_slug("CAR", "ATL", "2026-09-20"), "nfl-car-atl-2026-09-20")
        self.assertEqual(B.pmus_event_slug("NYG", "LA", "2026-09-21"), "nfl-nyg-lar-2026-09-21")

    def _event(self, markets):
        return json.dumps({"event": {"markets": markets}}).encode()

    def _market(self, **kw):
        m = {"sportsMarketType": "football_player_receiving_yards", "line": 60,
             "metadata": {"playerName": "Test Player"}, "status": "MARKET_STATUS_OPEN",
             "closed": False, "active": True,
             "bestBidQuote": {"value": "0.4000"}, "bestAskQuote": {"value": "0.4200"}}
        m.update(kw)
        return m

    def _run(self, markets, sched=None, games=None):
        calls = []

        def fake_get(url, timeout=120, tries=3):
            calls.append(url)
            if any(url.endswith(s) for s in (games or ["nfl-aaa-bbb-2026-09-20"])):
                return self._event(markets)
            raise OSError("404")

        real, B.http_get = B.http_get, fake_get
        try:
            out, n = B.fetch_pmus_prices(
                [{"away": "AAA", "home": "BBB", "date": "2026-09-20"}], sched)
        finally:
            B.http_get = real
        return out, n, calls

    def test_parses_both_sides_as_what_you_pay(self):
        """Over = best ask; Under = 1 - best bid. An "N+" market is the O/U line N-0.5."""
        out, n, _ = self._run([self._market()])
        self.assertEqual(n, 1)
        self.assertEqual(out[(B.pkey("Test Player"), "rec_yds", 59.5)], {"over": 42, "under": 60})

    def test_skips_closed_and_unpriced_markets(self):
        for bad in ({"closed": True}, {"active": False}, {"status": "MARKET_STATUS_HALTED"},
                    {"bestBidQuote": None, "bestAskQuote": None}):
            out, _, _ = self._run([self._market(**bad)])
            self.assertEqual(out, {}, bad)

    def test_falls_back_to_the_slate_date_for_night_games(self):
        """The slate dates SNF/MNF a day later than the schedule; the schedule date is
        tried first, then the slate date."""
        sched = {"g": {"id": "g", "away": "AAA", "home": "BBB", "date": "2026-09-19"}}
        out, n, calls = self._run([self._market()], sched=sched)
        self.assertEqual(n, 1)                                  # found on the slate date
        self.assertTrue(calls[0].endswith("nfl-aaa-bbb-2026-09-19"))   # schedule date first
        self.assertTrue(calls[1].endswith("nfl-aaa-bbb-2026-09-20"))

    def test_a_game_that_cannot_be_fetched_is_simply_skipped(self):
        out, n, _ = self._run([self._market()], games=["never-matches"])
        self.assertEqual((out, n), ({}, 0))

if __name__ == "__main__":
    unittest.main()

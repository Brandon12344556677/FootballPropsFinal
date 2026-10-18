"""Tests for next man up (build.py: injury_outs, nmu_adds, compute_injury_boosts, model_rows) and
players who changed teams this season (season_moves).

Run:  python -m unittest test_injury -v
"""
import unittest

import build as B


def row(season, week, opp, car=0, ryds=0, tgt=0, rec=0, recyds=0, rtd=0):
    r = [season, week, opp, "REG"] + [0] * 12 + [0, 0, None, None, 0.5]
    r[9], r[10], r[11], r[12], r[13], r[14] = car, ryds, rtd, rec, tgt, recyds
    return r


WEEKS = [(2025, w, f"O{w}") for w in range(1, 18)] + [(2026, 1, "TEN"), (2026, 2, "GB"), (2026, 3, "DET"), (2026, 4, "CHI")]


def backfield():
    """A starter who missed the last game (week 4), a backup who took it over, a third back."""
    hall = {"id": "hall", "n": "Breece Hall", "p": "RB", "t": "NYJ",
            "g": [row(s, w, o, 15, 70, 4, 3, 25) for s, w, o in WEEKS[:-1]]}
    allen = {"id": "allen", "n": "Braelon Allen", "p": "RB", "t": "NYJ",
             "g": [row(s, w, o, 3 + (w % 3), 12 + 4 * (w % 4), 1, 1, 6) for s, w, o in WEEKS[:-1]]
             + [row(2026, 4, "CHI", 14, 59, 2, 2, 10)]}
    davis = {"id": "davis", "n": "Isaiah Davis", "p": "RB", "t": "NYJ",
             "g": [row(s, w, o, 1, 4) for s, w, o in WEEKS[:-1]] + [row(2026, 4, "CHI", 0, 0)]}
    return hall, allen, davis


class Outs(unittest.TestCase):
    def test_sources(self):
        hall, allen, davis = backfield()
        wr = {"id": "wr", "n": "Garrett Wilson", "p": "WR", "t": "NYJ", "g": [], "inj": ["Out", "Hamstring", "DNP", 5]}
        te = {"id": "te", "n": "Some Tight End", "p": "TE", "t": "NYJ", "g": [], "st": "RES"}
        q = {"id": "q", "n": "Quentin Q", "p": "WR", "t": "NYJ", "g": []}
        espn = [{"name": "Breece Hall", "status": "Out"}, {"name": "Quentin Q", "status": "Questionable"},
                {"name": "Isaiah Davis", "status": "Injured Reserve"}]
        self.assertEqual(B.injury_outs([hall, allen, davis, wr, te, q], espn), {"hall", "davis", "wr", "te"})

    def test_shared_name_is_left_alone(self):
        a = {"id": "a", "n": "Mike Williams", "p": "WR", "t": "NYJ", "g": []}
        b = {"id": "b", "n": "Mike Williams", "p": "WR", "t": "PIT", "g": []}
        self.assertEqual(B.injury_outs([a, b], [{"name": "Mike Williams", "status": "Out"}]), set())


class Rebuild(unittest.TestCase):
    def setUp(self):
        self.hall, self.allen, self.davis = backfield()
        self.players = [self.hall, self.allen, self.davis]
        self.eff = B.position_eff(self.players)

    def test_backup_takes_the_carries(self):
        adds = B.nmu_adds(self.players, {"hall"}, self.eff, lam=1.0)
        wk3 = (2026, 3, "DET")
        self.assertAlmostEqual(adds["allen"][wk3][9], 15.0, places=6)   # the starter's 15 carries
        self.assertNotIn("davis", adds)                                # ~5% of the work: no real role, inherits nothing
        self.assertNotIn((2026, 4, "CHI"), adds["allen"])              # the game he already missed stays as played
        self.assertGreater(adds["allen"][wk3][10], 50)                 # the carries come with yards

    def test_work_goes_to_the_same_position(self):
        wr = {"id": "wr", "n": "A Receiver", "p": "WR", "t": "NYJ",
              "g": [row(s, w, o, 0, 0, 8, 5, 60) for s, w, o in WEEKS[:-1]]}
        adds = B.nmu_adds(self.players + [wr], {"hall"}, B.position_eff(self.players + [wr]), lam=1.0)
        self.assertNotIn("wr", adds)                                   # a back's carries never go to a receiver

    def test_lambda_scales_the_handoff(self):
        half = B.nmu_adds(self.players, {"hall"}, self.eff, lam=0.5)
        self.assertAlmostEqual(half["allen"][(2026, 3, "DET")][9], 7.5, places=6)

    def test_backtest_sees_only_earlier_games(self):
        adds = B.nmu_adds(self.players, {"hall"}, self.eff, before=(2026, 3))
        self.assertTrue(all((k[0], k[1]) < (2026, 3) for k in adds["allen"]))

    def test_end_to_end_moves_the_under(self):
        res = B.compute_injury_boosts(self.players, [{"name": "Breece Hall", "status": "Out"}])
        self.assertEqual(res, (1, 0, 1, 1))                      # Hall out, Allen handed work, Hall's own props held
        self.assertIn("Breece Hall", self.allen["inj_boost"]["why"])
        self.assertTrue(B.inj_on(self.allen, "rush_yds"))
        self.assertFalse(B.inj_on(self.allen, "pass_yds"))
        before = B.model_prob([B.stat_value("rush_yds", r) for r in self.allen["g"]], 49.5, "yards")
        after = B.model_prob([B.stat_value("rush_yds", r) for r in B.model_rows(self.allen)], 49.5, "yards")
        self.assertLess(after["under"], before["under"])          # a nudge (the backtest's strength)
        self.assertIsNone(B.hold_reason(self.allen, "rush_yds"))  # confirmed out: settled, back on the lists
        self.assertEqual(B.hold_reason(self.hall, "rush_yds"), "Breece Hall (out)")   # he isn't playing

    def test_held_props_stay_off_the_lists(self):
        mk = lambda prob, hd, pid: {"prob": prob, "neff": 9, "price": 60, "hd": hd, "lists": "", "gid": "g", "pid": pid, "stat": "rec"}
        picks = [mk(0.97, "X (questionable)", "a"), mk(0.78, None, "b"), mk(0.77, "Y (doubtful)", "c")]
        B.assign_lists(picks)
        self.assertEqual([p["lists"] for p in picks], ["", "TV", ""])

    def test_long_absence_is_not_new(self):
        hall, allen, davis = backfield()
        hall["g"] = hall["g"][:10]                                  # last played in 2025 week 10
        res = B.compute_injury_boosts([hall, allen, davis], [{"name": "Breece Hall", "status": "Injured Reserve"}])
        self.assertEqual(res, (1, 0, 0, 1))     # out since 2025 week 10: the log already shows it

    def test_model_rows_leave_the_log_alone(self):
        B.compute_injury_boosts(self.players, [{"name": "Breece Hall", "status": "Out"}])
        rebuilt = B.model_rows(self.allen)
        self.assertEqual(self.allen["g"][-2][9], 3 + (3 % 3))      # the stored game log is unchanged
        self.assertGreater(rebuilt[-2][9], self.allen["g"][-2][9])
        self.assertEqual(rebuilt[-1], self.allen["g"][-1])

    def test_nobody_out_changes_nothing(self):
        self.assertEqual(B.compute_injury_boosts(self.players, []), (0, 0, 0, 0))
        self.assertIs(B.model_rows(self.allen), self.allen["g"])


class Holds(unittest.TestCase):
    def receivers(self):
        wr1 = {"id": "wr1", "n": "DeVonta Smith", "p": "WR", "t": "PHI",
               "g": [row(s, w, o, 0, 0, 9, 6, 80) for s, w, o in WEEKS[:-1]]}
        wr3 = {"id": "wr3", "n": "Dontayvion Wicks", "p": "WR", "t": "PHI",
               "g": [row(s, w, o, 0, 0, 4, 3, 35) for s, w, o in WEEKS]}
        te = {"id": "te", "n": "A Tight End", "p": "TE", "t": "PHI",
              "g": [row(s, w, o, 0, 0, 5, 4, 40) for s, w, o in WEEKS]}
        rb = {"id": "rb", "n": "Saquon Barkley", "p": "RB", "t": "PHI",
              "g": [row(s, w, o, 18, 90, 3, 2, 15) for s, w, o in WEEKS]}
        return wr1, wr3, te, rb

    def test_questionable_receiver_holds_his_group(self):
        wr1, wr3, te, rb = self.receivers()
        res = B.compute_injury_boosts([wr1, wr3, te, rb], [{"name": "DeVonta Smith", "status": "Questionable"}])
        self.assertEqual(res, (0, 1, 0, 4))
        self.assertEqual(B.hold_reason(wr3, "rec"), "DeVonta Smith (questionable)")
        self.assertTrue(B.hold_reason(te, "rec_yds"))
        self.assertTrue(B.hold_reason(rb, "rec"))                # backs catch passes too
        self.assertIsNone(B.hold_reason(rb, "rush_yds"))          # but his carries don't depend on a receiver
        self.assertTrue(B.hold_reason(wr1, "rec"))                # his own props: he may not play
        self.assertNotIn("inj_add", wr3)                          # no hand-off until he's ruled out

    def test_doubtful_waits_too(self):
        wr1, wr3, te, rb = self.receivers()
        B.compute_injury_boosts([wr1, wr3, te, rb], [{"name": "DeVonta Smith", "status": "Doubtful"}])
        self.assertEqual(B.hold_reason(wr3, "rec"), "DeVonta Smith (doubtful)")

    def test_cleared_or_ruled_out_settles_it(self):
        wr1, wr3, te, rb = self.receivers()
        wr1["inj"] = ["Questionable", "Hamstring", "Limited", 5]   # the official report, from Friday
        B.compute_injury_boosts([wr1, wr3, te, rb], [{"name": "DeVonta Smith", "status": "Active"}])
        self.assertIsNone(B.hold_reason(wr3, "rec"))              # ESPN shows him active: settled
        self.assertIsNone(B.hold_reason(wr1, "rec"))
        wr1, wr3, te, rb = self.receivers()
        B.compute_injury_boosts([wr1, wr3, te, rb], [{"name": "DeVonta Smith", "status": "Out"}])
        self.assertIsNone(B.hold_reason(wr3, "rec"))              # ruled out: back on, with the model's numbers
        self.assertEqual(B.hold_reason(wr1, "rec"), "DeVonta Smith (out)")

    def test_official_report_when_espn_is_down(self):
        wr1, wr3, te, rb = self.receivers()
        wr1["inj"] = ["Questionable", "Hamstring", "Limited", 5]
        B.compute_injury_boosts([wr1, wr3, te, rb], None)
        self.assertTrue(B.hold_reason(wr3, "rec"))

    def test_quarterback_holds_the_passing_game(self):
        wr1, wr3, te, rb = self.receivers()
        qb = {"id": "qb", "n": "Jalen Hurts", "p": "QB", "t": "PHI", "g": [row(s, w, o) for s, w, o in WEEKS]}
        qb2 = {"id": "qb2", "n": "Backup QB", "p": "QB", "t": "PHI", "g": []}
        for r in qb["g"]:
            r[4], r[6] = 230, 32                                  # pass yards, attempts
        B.compute_injury_boosts([wr1, wr3, te, rb, qb, qb2], [{"name": "Jalen Hurts", "status": "Questionable"}])
        self.assertTrue(B.hold_reason(qb2, "pass_yds"))
        self.assertTrue(B.hold_reason(wr1, "rec_yds"))
        self.assertTrue(B.hold_reason(rb, "rec"))
        self.assertIsNone(B.hold_reason(rb, "rush_yds"))

    def test_a_deep_backup_holds_nobody_else(self):
        wr1, wr3, te, rb = self.receivers()
        wr5 = {"id": "wr5", "n": "Deep Backup", "p": "WR", "t": "PHI",
               "g": [row(s, w, o, 0, 0, 0, 0, 0) for s, w, o in WEEKS[:-3]] + [row(s, w, o, 0, 0, 1, 1, 5) for s, w, o in WEEKS[-3:]]}
        B.compute_injury_boosts([wr1, wr3, te, rb, wr5], [{"name": "Deep Backup", "status": "Questionable"}])
        self.assertTrue(B.hold_reason(wr5, "rec"))                # his own props wait
        self.assertIsNone(B.hold_reason(wr1, "rec"))              # ~3% of the targets: no real role

    def test_newcomer_with_no_games_for_the_team_holds_nobody_else(self):
        wr1, wr3, te, rb = self.receivers()
        new = {"id": "new", "n": "Just Signed", "p": "WR", "t": "PHI",
               "g": [row(s, w, "X" + o, 0, 0, 9, 6, 80) for s, w, o in WEEKS[:-2]]}    # all for another team
        sched = {i: {"home": "PHI", "away": o, "season": s, "week": w} for i, (s, w, o) in enumerate(WEEKS)}
        B.compute_injury_boosts([wr1, wr3, te, rb, new], [{"name": "Just Signed", "status": "Questionable"}], sched)
        self.assertTrue(B.hold_reason(new, "rec"))
        self.assertIsNone(B.hold_reason(wr1, "rec"))   # without the schedule, his old team's games read as 100% of the work


class Trades(unittest.TestCase):
    """A player who changed teams this season (build.season_moves) leaves his work to his old team."""
    SCHED = {f"ari{i}": {"home": "ARI", "away": o, "season": s, "week": w} for i, (s, w, o) in enumerate(WEEKS)}
    SCHED.update({f"hou{w}": {"home": "HOU", "away": f"H{w}", "season": 2026, "week": w} for w in range(1, 5)})

    def cardinals(self):
        """Harrison played every Arizona game but the last (week 4) and is now on Houston's roster."""
        mhj = {"id": "mhj", "n": "Marvin Harrison Jr.", "p": "WR", "t": "HOU", "lt": "ARI",
               "g": [row(s, w, o, 0, 0, 8, 5, 70) for s, w, o in WEEKS[:-1]]}
        wilson = {"id": "wilson", "n": "Michael Wilson", "p": "WR", "t": "ARI",
                  "g": [row(s, w, o, 0, 0, 6, 4, 50) for s, w, o in WEEKS]}
        mcbride = {"id": "mcbride", "n": "Trey McBride", "p": "TE", "t": "ARI",
                   "g": [row(s, w, o, 0, 0, 9, 7, 70) for s, w, o in WEEKS]}
        rb = {"id": "rb", "n": "A Back", "p": "RB", "t": "ARI", "g": [row(s, w, o, 15, 65, 3, 2, 15) for s, w, o in WEEKS]}
        nico = {"id": "nico", "n": "Nico Collins", "p": "WR", "t": "HOU",
                "g": [row(2026, w, f"H{w}", 0, 0, 9, 6, 85) for w in range(1, 5)]}
        return mhj, wilson, mcbride, rb, nico

    def test_found_from_the_game_log(self):
        mhj, wilson, mcbride, rb, nico = self.cardinals()
        old = {"id": "old", "n": "Left Last Spring", "p": "WR", "t": "HOU",           # moved in the offseason
               "g": [row(s, w, o, 0, 0, 5, 3, 40) for s, w, o in WEEKS[:17]]}
        cut = {"id": "cut", "n": "Released", "p": "WR", "t": "ARI", "st": "CUT",
               "g": [row(s, w, o, 0, 0, 2, 1, 10) for s, w, o in WEEKS[:-1]]}
        mv = B.season_moves([mhj, wilson, mcbride, rb, nico, old, cut], self.SCHED, 2026)
        self.assertEqual(list(mv), ["ARI"])
        self.assertEqual([(x["id"], x["to"], len(x["g"])) for x in mv["ARI"]], [("mhj", "HOU", 20)])

    def test_old_teammates_get_his_targets(self):
        mhj, wilson, mcbride, rb, nico = self.cardinals()
        before = B.model_prob([B.stat_value("rec_yds", r) for r in wilson["g"]], 54.5, "yards")
        B.compute_injury_boosts([mhj, wilson, mcbride, rb, nico], [], self.SCHED, 2026)
        # the hand-off: TRADE_LAMBDA of his 8 targets, split between the pass catchers by share
        self.assertAlmostEqual(B.model_rows(wilson)[-2][13] - wilson["g"][-2][13]
                               + B.model_rows(mcbride)[-2][13] - mcbride["g"][-2][13], 8 * B.TRADE_LAMBDA["rec"], places=1)
        self.assertGreater(B.model_rows(mcbride)[-2][13], B.model_rows(wilson)[-2][13])   # the bigger share gets more
        self.assertEqual(B.model_rows(wilson)[-1], wilson["g"][-1])     # the game he already missed stays as played
        self.assertIn("Marvin Harrison Jr. (now HOU)", wilson["inj_boost"]["why"])
        self.assertTrue(B.inj_on(wilson, "rec_yds"))
        after = B.model_prob([B.stat_value("rec_yds", r) for r in B.model_rows(wilson)], 54.5, "yards")
        self.assertGreater(after["over"], before["over"])
        self.assertNotIn("inj_boost", rb)              # a receiver's targets go to receivers and tight ends
        self.assertNotIn("inj_boost", mhj)             # projected from his own log, on Houston now
        self.assertNotIn("inj_boost", nico)            # his new teammates are left as they are
        self.assertIsNone(B.hold_reason(wilson, "rec"))   # settled news: nothing to wait for

    def test_traded_back_and_quarterback(self):
        sched = self.SCHED
        rb1 = {"id": "rb1", "n": "Traded Back", "p": "RB", "t": "HOU",
               "g": [row(s, w, o, 16, 70, 2, 2, 10) for s, w, o in WEEKS[:-1]]}
        rb2 = {"id": "rb2", "n": "Backup Back", "p": "RB", "t": "ARI", "g": [row(s, w, o, 6, 25) for s, w, o in WEEKS]}
        qb1 = {"id": "qb1", "n": "Traded QB", "p": "QB", "t": "HOU", "g": [row(s, w, o, 4, 20) for s, w, o in WEEKS[:-1]]}
        qb2 = {"id": "qb2", "n": "Backup QB", "p": "QB", "t": "ARI", "g": [row(s, w, o, 1, 3) for s, w, o in WEEKS]}
        for r in qb1["g"]:
            r[4], r[6], r[7] = 240, 34, 22            # pass yards, attempts, completions
        for r in qb2["g"]:
            r[4], r[6], r[7] = 40, 6, 4
        B.compute_injury_boosts([rb1, rb2, qb1, qb2], [], sched, 2026)
        add = B.model_rows(rb2)[-2][9] - rb2["g"][-2][9]
        self.assertAlmostEqual(add, 16 * B.TRADE_LAMBDA["rush"], places=6)   # his carries, to the back left
        self.assertAlmostEqual(B.model_rows(qb2)[-2][6] - 6, 34 * B.TRADE_LAMBDA["pass"], places=6)
        self.assertGreater(B.model_rows(qb2)[-2][4], 40)                      # the attempts come with yards
        self.assertTrue(B.inj_on(qb2, "pass_yds"))
        self.assertIn("Traded QB (now HOU)", qb2["inj_boost"]["why"])
        self.assertNotIn("Traded Back", qb2["inj_boost"]["why"])


if __name__ == "__main__":
    unittest.main()

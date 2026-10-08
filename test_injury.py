"""Tests for next man up (build.py: injury_outs, nmu_adds, compute_injury_boosts, model_rows).

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
        mk = lambda prob, hd: {"prob": prob, "neff": 9, "price": 40, "hd": hd, "lists": ""}
        picks = [mk(0.97, "X (questionable)"), mk(0.80, None), mk(0.75, "Y (doubtful)")]
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


if __name__ == "__main__":
    unittest.main()

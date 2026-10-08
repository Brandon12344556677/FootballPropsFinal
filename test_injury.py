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
        n_out, n_adj = B.compute_injury_boosts(self.players, [{"name": "Breece Hall", "status": "Out"}])
        self.assertEqual((n_out, n_adj), (1, 1))
        self.assertIn("Breece Hall", self.allen["inj_boost"]["why"])
        self.assertTrue(B.inj_on(self.allen, "rush_yds"))
        self.assertFalse(B.inj_on(self.allen, "pass_yds"))
        before = B.model_prob([B.stat_value("rush_yds", r) for r in self.allen["g"]], 49.5, "yards")
        after = B.model_prob([B.stat_value("rush_yds", r) for r in B.model_rows(self.allen)], 49.5, "yards")
        self.assertGreater(before["under"], 0.8)
        self.assertLess(after["under"], 0.5)

    def test_model_rows_leave_the_log_alone(self):
        B.compute_injury_boosts(self.players, [{"name": "Breece Hall", "status": "Out"}])
        rebuilt = B.model_rows(self.allen)
        self.assertEqual(self.allen["g"][-2][9], 3 + (3 % 3))      # the stored game log is unchanged
        self.assertGreater(rebuilt[-2][9], self.allen["g"][-2][9])
        self.assertEqual(rebuilt[-1], self.allen["g"][-1])

    def test_nobody_out_changes_nothing(self):
        self.assertEqual(B.compute_injury_boosts(self.players, []), (0, 0))
        self.assertIs(B.model_rows(self.allen), self.allen["g"])


if __name__ == "__main__":
    unittest.main()

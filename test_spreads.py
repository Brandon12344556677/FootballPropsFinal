import datetime
import unittest

import edge_report
import spreads

UTC = datetime.timezone.utc


def season(n, gap, home_edge, strong="AAA"):
    """n rounds of games among 4 teams: `strong` beats the others by `gap`, home teams by `home_edge`."""
    teams, rows, day = ["AAA", "BBB", "CCC", "DDD"], [], datetime.date(2026, 1, 1)
    for k in range(n):
        for i, h in enumerate(teams):
            a = teams[(i + 1 + k) % 4]
            if a == h:
                continue
            m = home_edge + (gap if h == strong else -gap if a == strong else 0)
            hs = 100 + max(m, 0) if m > 0 else 100
            rows.append([day.isoformat(), h, a, int(hs), int(hs - m), 0, f"{k}-{i}"])
        day += datetime.timedelta(days=1)
    return rows


class SpreadsTest(unittest.TestCase):
    def test_normal_fit_recovers_ratings_and_home_edge(self):
        m = spreads.fit_normal(season(40, 8, 3), "2026-03-01", dict(spreads.SPORTS["nba"], shrink=0.1))
        self.assertAlmostEqual(m["h"], 3, delta=0.3)
        self.assertGreater(m["r"]["AAA"] - m["r"]["BBB"], 7)
        mean, sigma = spreads.margin_dist(m, "AAA", "BBB")
        self.assertAlmostEqual(mean, m["h"] + m["r"]["AAA"] - m["r"]["BBB"])

    def test_cover_chance_normal(self):
        dist = (4.0, 12.0)                        # home by 4 expected
        self.assertAlmostEqual(spreads.cover_chance(dist, -4.0), 0.5)
        home, away = spreads.cover_chance(dist, -3.5), spreads.cover_chance(dist, 3.5, home_side=False)
        self.assertAlmostEqual(home + away, 1.0)  # home -3.5 and away +3.5 are the two sides of one line
        self.assertGreater(spreads.cover_chance(dist, 7.5), spreads.cover_chance(dist, 1.5))

    def test_count_model_margins(self):
        games = [["2026-01-%02d" % (1 + i % 28), "AAA", "BBB", 4, 2, 0, str(i)] for i in range(30)] + \
                [["2026-01-%02d" % (1 + i % 28), "BBB", "AAA", 2, 3, 0, "b" + str(i)] for i in range(30)]
        m = spreads.fit_count(games, "2026-02-01", spreads.SPORTS["nhl"])
        dist = spreads.margin_dist(m, "AAA", "BBB")
        self.assertAlmostEqual(sum(dist.values()), 1.0)
        self.assertNotIn(0, dist)                 # no ties: overtime decides
        self.assertGreater(spreads.cover_chance(dist, -1.5), spreads.cover_chance(dist, -1.5, home_side=False))

    def test_calibration_pulls_toward_half(self):
        self.assertAlmostEqual(spreads.calibrated(0.7, "nba"), 0.7)
        self.assertLess(spreads.calibrated(0.7, "nhl"), 0.7)
        self.assertGreater(spreads.calibrated(0.3, "nhl"), 0.3)
        self.assertAlmostEqual(spreads.calibrated(0.5, "mlb"), 0.5)

    def test_choose_takes_the_best_side_inside_the_rules(self):
        game = {"home": "DET", "away": "BOS", "hname": "pistons", "aname": "celtics", "neutral": False}
        model = {"kind": "normal", "r": {"DET": 2.0, "BOS": 0.0}, "h": 2.0, "sigma": 12.0, "n": {}}   # DET by 4
        rungs = [{"name": "celtics", "abbr": "BOS", "line": 1.5, "slug": "a"},      # BOS +1.5: model ~42%
                 {"name": "celtics", "abbr": "BOS", "line": -6.5, "slug": "b"}]     # BOS -6.5: model ~19%
        book = {"a": {"ask": 0.49, "bid": 0.48, "over": 500, "under": 500},   # No = DET -1.5 at 52c, model ~58%
                "b": {"ask": 0.20, "bid": 0.19, "over": 500, "under": 500}}   # No at 81c: over MAX_PRICE
        pick = spreads.choose(game, model, rungs, book, "nba")
        self.assertEqual((pick["team"], pick["line"], pick["side"], pick["price"]), ("DET", -1.5, "no", 0.52))
        self.assertTrue(spreads.MIN_EDGE <= pick["edge"] <= spreads.MAX_EDGE)
        thin = {"a": dict(book["a"], under=10), "b": book["b"]}
        self.assertIsNone(spreads.choose(game, model, rungs, thin, "nba"))   # not enough offered

    def test_grade(self):
        pick = {"gid": "9", "home": False, "line": 1.5, "price": 0.5, "date": "2026-10-20"}
        spreads.grade(pick, {"9": ["2026-10-20", "DET", "BOS", 101, 100, 0, "9"]}, "2026-10-21")   # BOS lost by 1
        self.assertEqual((pick["res"], pick["units"]), ("hit", 1.0))
        pick = {"gid": "9", "home": True, "line": -1.5, "price": 0.5, "date": "2026-10-20"}
        spreads.grade(pick, {"9": ["2026-10-20", "DET", "BOS", 101, 100, 0, "9"]}, "2026-10-21")
        self.assertEqual(pick["res"], "miss")
        late = {"gid": "x", "home": True, "line": 1.5, "price": 0.5, "date": "2026-10-10"}
        self.assertTrue(spreads.grade(late, {}, "2026-10-20"))
        self.assertEqual(late["res"], "void")

    def test_months_read(self):
        got = spreads.months_to_read("nfl", datetime.date(2026, 10, 20), {"202512": []})
        self.assertIn("202610", got)
        self.assertNotIn("202606", got)           # no NFL in June
        self.assertNotIn("202512", got)           # cached and not recent

    def test_edge_tracker_rows(self):
        doc = {"picks": [{"sport": "nba", "date": "2026-10-20", "res": "hit", "price": 0.5, "units": 1.0},
                         {"sport": "nhl", "date": "2026-10-20", "res": "miss", "price": 0.4, "units": -1.0},
                         {"sport": "nhl", "date": "2026-10-20", "res": "void", "price": 0.4, "units": 0.0}]}
        out = {s["key"]: s for s in edge_report.build(edge_report.spread_rows(doc), "2026-10-21")}
        self.assertEqual((out["spreads-nba"]["n"], out["spreads-nhl"]["n"], out["spreads-all"]["n"]), (1, 1, 2))
        self.assertEqual(out["all-nba"]["n"], 0)  # spreads never count as prop picks


if __name__ == "__main__":
    unittest.main()

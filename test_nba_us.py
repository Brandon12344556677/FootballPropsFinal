"""Tests for build_nba.fetch_markets_us: Polymarket US NBA player-prop ladders, network faked."""
import datetime
import json
import unittest
from unittest import mock

import build_nba as N

TODAY = datetime.date(2026, 10, 21)


def row(pts):
    r = [0] * 16
    r[4] = pts
    return r


PLAYERS = {N.pkey("LeBron James"): {"id": "1966", "n": "LeBron James", "t": "LAL", "g": [row(25)] * 10}}


def market(slug, title, line, smt="basketball_player_points", closed=False):
    return {"slug": slug, "title": title, "line": line, "sportsMarketType": smt, "closed": closed}


EVENTS = {"events": [
    {"slug": "nba-lal-gs-2026-10-21", "markets": [
        market("m20", "LeBron James 20+ points", 20), market("m25", "LeBron James 25+ points", 25),
        market("m30", "LeBron James 30+ points", 30), market("m35", "LeBron James 35+ points", 35),
        market("m40", "LeBron James 40+ points", 40),
        market("x", "Lakers vs Warriors total", 220.5, smt="basketball_total"),
        market("nobody", "Some Rookie 10+ points", 10)]},
    {"slug": "nba-champ-2027-06-18-w", "markets": []},
    {"slug": "nba-uta-was-2026-10-30", "markets": []}]}


class FetchUS(unittest.TestCase):
    def run_it(self):
        books = []

        def http_get(url, *a, **k):
            if "/book" in url:
                books.append(url.split("/markets/")[1].split("/")[0])
                return json.dumps({"marketData": {}})
            return json.dumps(EVENTS)
        with mock.patch.object(N, "http_get", side_effect=http_get), \
                mock.patch.object(N.depth, "pmus_book", return_value={"ask": 0.55, "bid": 0.5, "over": 300.0, "under": 200.0}), \
                mock.patch.object(N.time, "sleep"):
            games = N.fetch_markets_us(PLAYERS, today=TODAY)
        return games, books

    def test_prices_the_rungs_nearest_his_average(self):
        games, books = self.run_it()
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual((g["away"], g["home"], g["date"]), ("LAL", "GS", "2026-10-21"))
        self.assertEqual(sorted(books), ["m20", "m25", "m30"])          # 3 rungs nearest his 25-point average
        pm = sorted((m["pm"] for m in g["markets"]), key=lambda p: p["line"])
        self.assertEqual([p["line"] for p in pm], [19.5, 24.5, 29.5])
        self.assertEqual((pm[0]["over"], pm[0]["under"], pm[0]["tradeable"]), (0.55, 0.5, True))

    def test_team_codes_match_the_nba_data(self):
        self.assertEqual((N.us_team("uta"), N.us_team("was"), N.us_team("ny")), ("UTAH", "WSH", "NY"))


class StatNames(unittest.TestCase):
    def test_polymarket_us_combo_names(self):
        # Polymarket US's prop type points_rebounds_assists arrives as "points rebounds assists" (no "+"),
        # which read as plain rebounds until Oct 22, 2026
        self.assertEqual(N.mkt_stat_key("points rebounds assists"), "pra")
        self.assertEqual(N.mkt_stat_key("Points + Rebounds + Assists"), "pra")
        self.assertEqual([N.mkt_stat_key(t) for t in ("points rebounds", "points assists", "rebounds assists")], ["pr", "pa", "ra"])
        self.assertEqual([N.mkt_stat_key(t) for t in ("points", "rebounds", "assists", "threes", "steals", "blocks")],
                         ["pts", "reb", "ast", "tpm", "stl", "blk"])


class VoidPRA(unittest.TestCase):
    def test_listed_picks_are_voided_once(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "void.json")
        with open(path, "w") as f:
            json.dump([["2026-10-20-BOS-DET", "3078576", "reb", 14.5]], f)
        hit = {"src": "live", "gid": "2026-10-20-BOS-DET", "pid": "3078576", "stat": "reb", "line": 14.5, "res": "hit", "actual": 6}
        other = dict(hit, line=4.5)
        pending = dict(hit, gid="2026-10-20-BOS-DET", res=None)
        picks = [hit, other]
        self.assertEqual(N.void_pra(picks, path), 1)
        self.assertEqual((hit["res"], hit["actual"]), ("void", None))
        self.assertEqual(other["res"], "hit")
        self.assertEqual(N.void_pra(picks, path), 0)                 # already void: counted once
        self.assertEqual(N.void_pra([pending], path), 1)              # pending ones too: they were never real
        self.assertEqual(N.void_pra(picks, path + "x"), 0)            # no file: nothing happens


if __name__ == "__main__":
    unittest.main()

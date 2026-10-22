"""The NFL slate comes from Polymarket US since Polymarket stopped serving its global event list (404
since Oct 21, 2026): the games, their player props as markets parse_market() reads, and their prices."""
import datetime
import json
import unittest
from unittest import mock

import build as B


def us_market(name, smt, n, bid, ask, **kw):
    return dict({"sportsMarketType": smt, "line": n, "metadata": {"playerName": name}, "subject": None,
                 "slug": f"astatc-{name.split()[0].lower()}-{n}", "status": "MARKET_STATUS_OPEN", "active": True,
                 "closed": False, "bestBidQuote": {"value": str(bid)}, "bestAskQuote": {"value": str(ask)}}, **kw)


LISTING = {"events": [
    {"slug": "nfl-ne-chi-2026-10-22", "startDate": "2026-10-23T00:15:00Z", "title": "NE Patriots vs. CHI Bears"},
    {"slug": "nfl-lar-lv-2026-10-25", "startDate": "2026-10-25T20:25:00Z", "title": "LA Rams vs. LV Raiders"},
    {"slug": "nfl-ne-chi-2026-10-22-more-markets", "startDate": "2026-10-23T00:15:00Z"},   # not a game
    {"slug": "nfl-dal-phi-2026-12-20", "startDate": "2026-12-20T18:00:00Z"},               # too far out
]}
EVENTS = {
    "nfl-ne-chi-2026-10-22": {"event": {"markets": [
        us_market("Caleb Williams", "football_player_passing_yards", 150, 0.68, 0.72),
        us_market("Rome Odunze", "football_player_receptions", 4, 0.40, 0.45),
        us_market("Caleb Williams", "football_player_interceptions_thrown", 1, 0.44, 0.45),   # never on the old board
        us_market("Rome Odunze", "football_player_touchdowns", 1, 0.40, 0.42),               # no stat text for it
        us_market("Caleb Williams", "football_player_most_passing_yards", 1, 0.5, 0.55),     # not a prop we model
        us_market("Drake Maye", "football_player_passing_yards", 200, 0.5, 0.55, closed=True),
        {"sportsMarketType": "football_team_full_game_spread", "line": 3.5},
    ]}},
    "nfl-lar-lv-2026-10-25": {"event": {"markets": [
        us_market("Puka Nacua", "football_player_receiving_yards", 70, 0.55, 0.58)]}},
}


def fake_get(url, timeout=None, tries=None):
    if "/v1/events?" in url:
        return json.dumps(LISTING)
    slug = url.rsplit("/", 1)[1]
    if slug in EVENTS:
        return json.dumps(EVENTS[slug])
    raise OSError("HTTP Error 404: Not Found")


class UsSlate(unittest.TestCase):
    def slate(self, get=fake_get):
        with mock.patch.object(B, "http_get", side_effect=get), \
                mock.patch.object(B, "TODAY", datetime.date(2026, 10, 21)):
            return B.fetch_slate()

    def test_games_and_props(self):
        games = self.slate()
        self.assertEqual([(g["slug"], g["away"], g["home"], g["date"]) for g in games],
                         [("nfl-ne-chi-2026-10-22", "NE", "CHI", "2026-10-22"),
                          ("nfl-lar-lv-2026-10-25", "LA", "LV", "2026-10-25")])     # lar -> nflverse LA
        self.assertEqual(games[0]["start"], "2026-10-23T00:15:00Z")
        pms = [B.parse_market(m) for m in games[0]["markets"]]
        self.assertEqual([(p["player"], B.mkt_stat_key(p["statText"]), p["line"]) for p in pms],
                         [("Caleb Williams", "pass_yds", 149.5), ("Rome Odunze", "rec", 3.5)])
        self.assertAlmostEqual(pms[0]["over"], 0.72)     # what you'd pay: the ask...
        self.assertAlmostEqual(pms[0]["under"], 0.32)    # ...and 1 - the bid
        self.assertTrue(pms[0]["tradeable"])

    def test_prices_reuse_the_fetched_events(self):
        games = self.slate()
        calls = []
        with mock.patch.object(B, "http_get", side_effect=lambda *a, **k: calls.append(a) or fake_get(*a)):
            prices, n = B.fetch_pmus_prices(games)
        self.assertEqual(calls, [])                      # no second fetch per game
        self.assertEqual(n, 2)
        self.assertEqual(prices[(B.pkey("Caleb Williams"), "pass_yds", 149.5)]["over"], 72)
        self.assertEqual(prices[(B.pkey("Puka Nacua"), "rec_yds", 69.5)]["under"], 45)

    def test_a_side_nobody_can_buy_has_no_price(self):
        # NBA-style: the No side (the under) marked not tradable on Polymarket US
        sides = [{"description": "Yes", "long": True, "tradable": True}, {"description": "No", "long": False, "tradable": False}]
        m = us_market("Caleb Williams", "football_player_passing_yards", 150, 0.68, 0.72, marketSides=sides)
        self.assertEqual(B.depth.tradable_sides(m), {"over": True, "under": False})
        pm = B.parse_market(B.pmus_as_market(m))
        self.assertAlmostEqual(pm["over"], 0.72)
        self.assertIsNone(pm["under"])
        ev = {"event": {"markets": [m]}}
        with mock.patch.object(B, "http_get", side_effect=lambda *a, **k: json.dumps(ev)):
            prices, _ = B.fetch_pmus_prices([{"slug": "x", "away": "NE", "home": "CHI", "date": "2026-10-22"}])
        self.assertEqual(prices[(B.pkey("Caleb Williams"), "pass_yds", 149.5)]["under"], None)
        self.assertEqual(prices[(B.pkey("Caleb Williams"), "pass_yds", 149.5)]["over"], 72)

    def test_builders_note_sides(self):
        B.depth.note_sides({"slug": "s1", "marketSides": [{"description": "No", "long": False, "tradable": False}]})
        self.assertTrue(B.depth.side_ok("s1", "over"))
        self.assertFalse(B.depth.side_ok("s1", "under"))
        self.assertTrue(B.depth.side_ok("never-seen", "under"))   # unknown: tradable

    def test_global_list_is_the_fallback(self):
        def us_down(url, timeout=None, tries=None):
            if "polymarket.us" in url:
                raise OSError("HTTP Error 503")
            if "/events/slug/" in url:
                return json.dumps({"markets": [{"question": "Rome Odunze: Receptions O/U 3.5"}]})
            return json.dumps([{"slug": "nfl-ne-chi-2026-10-22-player-props", "startDate": "2026-10-23T00:15:00Z"}])
        games = self.slate(us_down)
        self.assertEqual([g["slug"] for g in games], ["nfl-ne-chi-2026-10-22-player-props"])
        self.assertEqual(len(games[0]["markets"]), 1)

    def test_both_down_raises(self):
        def down(url, timeout=None, tries=None):
            raise OSError("HTTP Error 404: Not Found")
        with self.assertRaises(OSError):                 # main() catches it: "slate: skipped"
            self.slate(down)


if __name__ == "__main__":
    unittest.main()

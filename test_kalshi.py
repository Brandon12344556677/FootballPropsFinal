"""Tests for kalshi.py (Kalshi prices, side by side with Polymarket) and the builders' use of it.
Markets are shaped like Kalshi's /markets responses.

Run:  python -m unittest test_kalshi -v
"""
import unittest

import kalshi
import build as NFL
import build_mlb as MLB


def market(event="KXMLBHIT-26OCT072000TBNYY", sub="Trent Grisham: 2+", strike=1.5, yb="0.1800", ya="0.2000", na="0.8200",
           **kw):
    m = {"event_ticker": event, "ticker": event + "-NYYTGRISHAM12-2", "yes_sub_title": sub, "floor_strike": strike,
         "strike_type": "greater", "yes_bid_dollars": yb, "yes_ask_dollars": ya, "no_ask_dollars": na, "status": "active"}
    m.update(kw)
    return m


def pick(**kw):
    p = {"res": None, "player": "Trent Grisham", "stat": "h", "line": 1.5, "side": "over", "price": 0.22,
         "pp": 0.22, "vn": "P", "start": "2026-10-08T00:05Z", "date": "2026-10-08"}
    p.update(kw)
    return p


class Parse(unittest.TestCase):
    def test_rung(self):
        k = kalshi.parse(market(), "h")
        self.assertEqual(k, {"player": "Trent Grisham", "sk": "h", "line": 1.5, "date": "2026-10-07",
                             "over": 0.2, "under": 0.82, "tradeable": True})

    def test_nfl_event_has_no_time(self):
        k = kalshi.parse(market(event="KXNFLRECYDS-26OCT11HOUTEN", sub="Calvin Ridley: 50+", strike=49.5), "rec_yds")
        self.assertEqual((k["line"], k["date"]), (49.5, "2026-10-11"))

    def test_no_bid_means_no_under(self):
        k = kalshi.parse(market(yb="0.0000", ya="0.0500", na="1.0000"), "h")
        self.assertEqual((k["over"], k["under"], k["tradeable"]), (0.05, None, True))

    def test_wide_spread_not_tradeable(self):
        self.assertFalse(kalshi.parse(market(yb="0.2000", ya="0.4000", na="0.8000"), "h")["tradeable"])

    def test_not_a_rung(self):
        self.assertIsNone(kalshi.parse(market(sub="Trent Grisham: 2+", strike=2.5), "h"))   # strike disagrees with N+
        self.assertIsNone(kalshi.parse(market(sub="Both teams 14+ points"), "h"))
        self.assertIsNone(kalshi.parse(market(strike_type="custom"), "h"))
        self.assertIsNone(kalshi.parse(market(status="settled"), "h"))


class Pricing(unittest.TestCase):
    def test_best(self):
        self.assertEqual(kalshi.best(0.50, 0.48), (0.48, "K"))
        self.assertEqual(kalshi.best(0.48, 0.50), (0.48, "P"))
        self.assertEqual(kalshi.best(0.50, 0.50), (0.50, "P"))      # a tie stays on Polymarket
        self.assertEqual(kalshi.best(None, 0.40), (0.40, "K"))
        self.assertEqual(kalshi.best(None, None), (None, None))

    def test_et_date(self):
        self.assertEqual(kalshi.et_date("2026-10-08T02:05Z"), "2026-10-07")     # 10:05 PM EDT
        self.assertEqual(kalshi.et_date("2026-10-07T17:05Z"), "2026-10-07")
        self.assertIsNone(kalshi.et_date(None))

    def test_apply_cheaper_wins_each_side(self):
        mk = [kalshi.parse(market(), "h")]
        over, under = pick(), pick(side="under", price=0.80, pp=0.80)
        n = kalshi.apply([over, under], mk, MLB.pkey, lambda p: True)
        self.assertEqual(n, 2)
        self.assertEqual((over["price"], over["vn"], over["kp"]), (0.2, "K", 0.2))       # Kalshi 20c < Polymarket 22c
        self.assertEqual((under["price"], under["vn"], under["kp"]), (0.8, "P", 0.82))   # Polymarket 80c < Kalshi 82c

    def test_apply_needs_same_line_and_game_day(self):
        mk = [kalshi.parse(market(), "h")]
        other_line = pick(line=0.5)
        other_day = pick(start="2026-10-09T00:05Z")
        kalshi.apply([other_line, other_day], mk, MLB.pkey, lambda p: True)
        self.assertEqual([p["kp"] for p in (other_line, other_day)], [None, None])
        self.assertEqual([p["vn"] for p in (other_line, other_day)], ["P", "P"])

    def test_apply_name_spelling(self):
        mk = [kalshi.parse(market(sub="Ángel Martínez Jr.: 2+"), "h")]
        p = pick(player="Angel Martinez")
        kalshi.apply([p], mk, MLB.pkey, lambda p: True)
        self.assertEqual(p["kp"], 0.2)

    def test_apply_kalshi_only(self):
        p = pick(price=None, pp=None, vn=None)
        kalshi.apply([p], [kalshi.parse(market(), "h")], MLB.pkey, lambda p: True)
        self.assertEqual((p["price"], p["vn"]), (0.2, "K"))

    def test_apply_skips_locked_and_graded(self):
        mk = [kalshi.parse(market(), "h")]
        locked, graded = pick(lk="2026-10-07T23:50Z"), pick(res="hit")
        kalshi.apply([locked, graded], mk, MLB.pkey, lambda p: not p.get("lk"))
        self.assertEqual([p.get("kp") for p in (locked, graded)], [None, None])
        self.assertEqual([p["price"] for p in (locked, graded)], [0.22, 0.22])

    def test_apply_unreachable_keeps_last_kalshi_price(self):
        p = pick(kp=0.19, price=0.19, vn="K")
        kalshi.apply([p], None, MLB.pkey, lambda p: True)
        self.assertEqual((p["kp"], p["price"], p["vn"]), (0.19, 0.19, "K"))

    def test_apply_delisted_clears_kalshi_price(self):
        p = pick(kp=0.19, price=0.19, vn="K")
        kalshi.apply([p], [], MLB.pkey, lambda p: True)
        self.assertEqual((p["kp"], p["price"], p["vn"]), (None, 0.22, "P"))

    def test_apply_legacy_pick_price_is_polymarket(self):
        p = pick(pp=None, vn=None, price=0.30, line=3.5)        # recorded before Kalshi; no Kalshi rung at 3.5
        kalshi.apply([p], [kalshi.parse(market(), "h")], MLB.pkey, lambda p: True)
        self.assertEqual((p["pp"], p["price"], p["vn"]), (0.30, 0.30, "P"))

    def test_mlb_refresh_keeps_kalshi_when_cheaper(self):
        p = pick(kp=0.19, price=0.19, vn="K")
        MLB.refresh_price(p, {"over": 0.25, "under": 0.77, "tradeable": True})
        self.assertEqual((p["pp"], p["price"], p["vn"]), (0.25, 0.19, "K"))


class NFLBoard(unittest.TestCase):
    def test_kalshi_board_only_this_weeks_game(self):
        mk = [kalshi.parse(market(event="KXNFLRECYDS-26OCT11HOUTEN", sub="Calvin Ridley: 50+", strike=49.5,
                                  yb="0.4500", ya="0.4700", na="0.5500"), "rec_yds"),
              kalshi.parse(market(event="KXNFLRECYDS-26OCT18HOUTEN", sub="Calvin Ridley: 60+", strike=59.5), "rec_yds")]
        names = {"calvin ridley": "nfl-hou-ten-2026-10-11"}
        sgs = {"nfl-hou-ten-2026-10-11": {"date": "2026-10-11"}}
        self.assertEqual(NFL.kalshi_board(mk, names, sgs), {"calvin ridley|rec_yds|49.5": [47, 55]})

    def test_make_pick_records_venue(self):
        mp = {"over": 0.6, "under": 0.4, "lo": 0.5, "hi": 0.7, "neff": 8.0}
        pl = {"id": "1", "n": "Calvin Ridley", "p": "WR", "t": "TEN"}
        p = NFL.make_pick("live", "g", 2026, 6, "2026-10-11", pl, "HOU", "rec_yds", 49.5, mp, 47, "r", pp=49, kp=47)
        self.assertEqual((p["price"], p["pp"], p["kp"], p["vn"]), (47, 49, 47, "K"))


if __name__ == "__main__":
    unittest.main()

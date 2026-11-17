"""depth.exchange_links: the exact Polymarket US event and Kalshi events behind each game's pending picks."""
import unittest

import depth


def pick(**kw):
    p = {"src": "live", "gid": "401", "pid": "p1", "stat": "pts", "line": 0.5, "side": "over", "res": None}
    p.update(kw)
    return p


class EventParts(unittest.TestCase):
    def test_pmus_event_from_market_slug(self):
        self.assertEqual(depth.pmus_event("astatc-nhl-la-bos-2026-11-17-ast-quibyf-gte1"), "nhl-la-bos-2026-11-17")
        self.assertEqual(depth.pmus_event("astatc-nba-ny-tor-2026-11-17-3pm-jalbru-gte5"), "nba-ny-tor-2026-11-17")

    def test_pmus_event_slug_is_itself(self):
        self.assertEqual(depth.pmus_event("nfl-kc-buf-2026-11-22"), "nfl-kc-buf-2026-11-22")

    def test_pmus_event_unknown(self):
        for s in (None, "", "no-date-here", "nhl-la-bos-2026-11"):
            self.assertIsNone(depth.pmus_event(s))

    def test_kalshi_event(self):
        self.assertEqual(depth.kalshi_event("KXNHLPTS-26NOV16VANUTA-VANTWILLANDER5-1"), "KXNHLPTS-26NOV16VANUTA")
        self.assertEqual(depth.kalshi_event("kxnbapts-26nov17nytor-x-25"), "KXNBAPTS-26NOV17NYTOR")
        self.assertIsNone(depth.kalshi_event("KXNHLPTS"))
        self.assertIsNone(depth.kalshi_event(None))


class Links(unittest.TestCase):
    def test_one_game_both_exchanges(self):
        ps = [pick(_us="astatc-nhl-la-bos-2026-11-17-ast-quibyf-gte1", _kt="KXNHLAST-26NOV17LABOS-X-1", stat="ast"),
              pick(pid="p2", _us="astatc-nhl-la-bos-2026-11-17-pts-abc-gte1", _kt="KXNHLPTS-26NOV17LABOS-Y-1")]
        self.assertEqual(depth.exchange_links(ps), {"401": {"p": "nhl-la-bos-2026-11-17",
                                                            "k": {"ast": "KXNHLAST-26NOV17LABOS", "pts": "KXNHLPTS-26NOV17LABOS"}}})

    def test_nfl_ps_field(self):
        ps = [pick(gid="2026_11_KC_BUF", stat="rec_yds", _ps="astatc-nfl-kc-buf-2026-11-22-recyds-x-gte50")]
        self.assertEqual(depth.exchange_links(ps), {"2026_11_KC_BUF": {"p": "nfl-kc-buf-2026-11-22"}})

    def test_skips_graded_locked_backtest_and_unpriced(self):
        us = "astatc-nhl-la-bos-2026-11-17-ast-quibyf-gte1"
        ps = [pick(_us=us, res="hit"), pick(_us=us, lk="2026-11-17T23:40Z"), pick(_us=us, src="bt"),
              pick(gid="402"), pick(gid=None, _us=us)]
        self.assertEqual(depth.exchange_links(ps), {})
        self.assertEqual(depth.exchange_links([pick(_us=us)], lambda p: True), {})

    def test_kalshi_only(self):
        self.assertEqual(depth.exchange_links([pick(gid=7, _kt="KXMLBHIT-26APR01NYYBOS-A-1", stat="hits")]),
                         {"7": {"k": {"hits": "KXMLBHIT-26APR01NYYBOS"}}})

    def test_never_raises(self):
        self.assertEqual(depth.exchange_links([None]), {})
        self.assertEqual(depth.exchange_links(None), {})
        self.assertEqual(depth.exchange_links([pick(_us="x")], lambda p: 1 / 0), {})


if __name__ == "__main__":
    unittest.main()

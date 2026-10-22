"""A pending pick whose Polymarket US market disappears loses its Polymarket price (depth.drop_vanished),
so it can't stay on Top 25 / Value at a price nobody can get (seen Oct 22, 2026: Cason Wallace under 9.5
rebounds stayed on Value at 67c after Polymarket stopped listing it)."""
import unittest

import depth


def pick(pid, line, pp=0.67, kp=None, kd=None, **kw):
    return dict({"src": "live", "gid": "2026-10-22-DEN-OKC", "pid": pid, "stat": "reb", "line": line, "side": "under",
                 "res": None, "pp": pp, "pd": 300.0, "kp": kp, "kd": kd, "price": pp, "vn": "P", "th": None,
                 "_us": "slug", "lists": "V"}, **kw)


class DropVanished(unittest.TestCase):
    def test_only_gone_markets_lose_their_price(self):
        gone, kept = pick("1", 9.5), pick("2", 4.5)
        to_kalshi = pick("3", 9.5, kp=0.62, kd=100.0)
        locked = pick("4", 9.5, lk="2026-10-22T23:00Z")
        graded = pick("5", 9.5, res="hit")
        other_game = pick("6", 9.5, gid="2026-10-22-CLE-PHI")
        picks = [gone, kept, to_kalshi, locked, graded, other_game]
        listed = {("2", "reb", 4.5)}
        n = depth.drop_vanished(picks, "2026-10-22-DEN-OKC", listed, lambda p: bool(p.get("lk")))
        self.assertEqual(n, 2)
        self.assertEqual((gone["pp"], gone["price"], gone["vn"], gone["_us"]), (None, None, None, None))
        self.assertEqual((to_kalshi["price"], to_kalshi["vn"]), (0.62, "K"))        # Kalshi still lists it
        self.assertEqual(kept["price"], 0.67)                                         # still listed: untouched
        for p in (locked, graded, other_game):                                        # locked / graded / not read
            self.assertEqual(p["price"], 0.67)


if __name__ == "__main__":
    unittest.main()

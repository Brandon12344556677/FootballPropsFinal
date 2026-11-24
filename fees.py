"""
Prop Streak Lab — what a 1-unit bet on a pick returned after the exchange's taker fee, and how sure that is.

One place for the numbers every record leads with (the sport boards' banners and list headers, the Record
page, the home page): units won after fees, the return per unit staked after fees with a +/- range, and the
average price paid, which a hit rate means nothing without.

Fees: buying at price p costs a taker fee of FEE[venue] x p x (1 - p) per contract (arbs.FEE: Polymarket US
0.05, Kalshi 0.07). A 1-unit stake buys 1/p contracts, so the fee is FEE x (1 - p) units, win or lose. A pick
whose venue isn't known is charged Kalshi's (higher) fee. Kalshi rounds each order's fee up to the cent;
that rounding isn't modeled, so these are, if anything, a touch generous. Resting (maker) orders pay less or
nothing: the after-fee figure is what someone taking the price, as the site shows it, would have got.

The range: +/- 1.96 standard errors of the mean return per pick (about a 95% range). A return whose range
includes zero is "too early to tell" (TOO_EARLY): the record can't yet tell an edge from luck.

Standard library only.
"""
import math

from arbs import FEE

Z = 1.96          # +/- this many standard errors: about a 95% range
MIN_RANGE = 10    # fewer priced picks than this: no range (it would mean little)


def fee(price, vn=None):
    """Taker fee, in units, on a 1-unit stake at price (a fraction)."""
    return (FEE.get(vn) or FEE["K"]) * (1.0 - price)


def gross(price, win):
    """What 1 unit at price returned before fees: 1/price - 1 on a win, -1 on a loss."""
    return (1.0 / price - 1.0) if win else -1.0


def net(price, win, vn=None):
    """What 1 unit at price returned after the taker fee."""
    return gross(price, win) - fee(price, vn)


def summary(bets):
    """bets: [(price as a fraction, won?, venue 'P'/'K'/None), ...], priced bets only.
    {"net": units after fees, "roiNet": return per unit after fees, "pm": the +/- range on roiNet (None under
    MIN_RANGE bets), "early": True when that range includes zero, "avgPx": average price paid}."""
    bets = [b for b in bets if b and b[0]]
    if not bets:
        return {"net": None, "roiNet": None, "pm": None, "early": True, "avgPx": None}
    rs = [net(p, w, vn) for p, w, vn in bets]
    n = len(rs)
    mean = sum(rs) / n
    pm = None
    if n >= MIN_RANGE:
        var = sum((r - mean) ** 2 for r in rs) / (n - 1)
        pm = Z * math.sqrt(var / n)
    return {"net": round(sum(rs), 2), "roiNet": round(mean, 4), "pm": round(pm, 4) if pm is not None else None,
            "early": pm is None or abs(mean) < pm, "avgPx": round(sum(p for p, _, _ in bets) / n, 4)}

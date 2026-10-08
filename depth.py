"""
Prop Streak Lab — is there enough money at the price? (the thin-market filter)

A price is only as good as what's offered at it. In a near-empty book a $25 bet buys up the
best ask and then the next ones, so you pay well above the price the site showed. So Top 25
Surest and Value only count an exchange's price for a side when at least MIN_USD is offered
to buy that side within WITHIN of it — the price shown, up to 2 cents worse:

  - Polymarket US: /v1/markets/{slug}/book. Over = buy Yes from the offers; under = buy No,
    i.e. sell Yes into the bids, at 1 - bid.
  - Kalshi: the market list carries the size at the best Yes bid and ask; /markets/{ticker}/
    orderbook has every level. Over = buy Yes against the No bids (at 1 - No bid); under = buy
    No against the Yes bids.
  - Polymarket's global book (NBA, NHL): the CLOB /book of the side's own token, its asks.

Each pick keeps both exchanges' prices (pp, kp) and the dollars offered within 2c of each (pd,
kd). choose() sets price/vn to the cheaper exchange that clears MIN_USD; when neither does, it
shows the cheaper anyway and marks the pick thin ("th"), which keeps it off Top 25 and Value.

Standard library only. Never fatal: a book that can't be read leaves that depth unknown, and an
unknown depth doesn't count as enough.
"""
import json
import time
import urllib.request

MIN_USD = 25.0           # dollars offered to buy the side...
WITHIN = 0.02            # ...at the price shown or up to 2c worse
PMUS_BOOK = "https://gateway.polymarket.us/v1/markets/{slug}/book"
KALSHI_BOOK = "https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
CLOB_BOOK = "https://clob.polymarket.com/book?token_id={token}"
UA = {"Accept": "application/json", "User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}


def _f(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def usd_within(levels):
    """levels: [(price, qty)] a side can be bought at. Dollars offered from the best (lowest)
    price up to WITHIN worse."""
    lv = [(p, q) for p, q in levels if p is not None and q and 0 < p < 1]
    if not lv:
        return 0.0
    best = min(p for p, _ in lv)
    return round(sum(p * q for p, q in lv if p <= best + WITHIN + 1e-9), 2)


def pmus_book(md):
    """Polymarket US book ("marketData") -> {"ask", "bid", "over", "under"}: the best Yes ask
    and bid, and the dollars within 2c to buy the over and the under."""
    offers = [(_f(o.get("px")), _f(o.get("qty"))) for o in (md or {}).get("offers") or []]
    bids = [(_f(b.get("px")), _f(b.get("qty"))) for b in (md or {}).get("bids") or []]
    asks = [p for p, q in offers if p is not None and q]
    bps = [p for p, q in bids if p is not None and q]
    return {"ask": min(asks) if asks else None, "bid": max(bps) if bps else None,
            "over": usd_within(offers),
            "under": usd_within([(1 - p, q) for p, q in bids if p is not None])}


def kalshi_book(ob):
    """Kalshi orderbook -> {"over", "under"}: dollars within 2c to buy each side."""
    o = (ob or {}).get("orderbook_fp") or {}
    yes = [(_f(p), _f(q)) for p, q in o.get("yes_dollars") or []]
    no = [(_f(p), _f(q)) for p, q in o.get("no_dollars") or []]
    return {"over": usd_within([(1 - p, q) for p, q in no if p is not None]),
            "under": usd_within([(1 - p, q) for p, q in yes if p is not None])}


def clob_book(bk):
    """Polymarket CLOB book of one outcome token -> dollars within 2c to buy it."""
    return usd_within([(_f(a.get("price")), _f(a.get("size"))) for a in (bk or {}).get("asks") or []])


def _get(url):
    time.sleep(0.15)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read())


def fetch_pmus(slug):
    return pmus_book(_get(PMUS_BOOK.format(slug=slug)).get("marketData") or {})


def fetch_kalshi(ticker):
    return kalshi_book(_get(KALSHI_BOOK.format(ticker=ticker)))


def fetch_clob(token):
    return clob_book(_get(CLOB_BOOK.format(token=token)))


RULE_DAY = "2026-10-07"   # the $25 rule went live that evening


def unchecked(p):
    """A Top 25 / Value pick from the rule's launch day recorded before the rule ran: its depth was
    never checked, so (the site owner's call) it's left out of Past picks and the record like a
    thin-market rule-out. Mirrors PS.thinOut on the pages."""
    return bool(p.get("lists")) and str(p.get("date")) == RULE_DAY and p.get("vn") is None and not p.get("th")


def deep(usd):
    return usd is not None and usd >= MIN_USD


def choose(p):
    """price / vn / th from the pick's two prices for its side (pp Polymarket, kp Kalshi) and the
    dollars offered within 2c of each (pd, kd): the cheaper exchange with MIN_USD+ offered;
    when neither has that much, the cheaper one, with th = 1 (thin: no Top 25 or Value)."""
    have = [(px, d, vn) for px, d, vn in ((p.get("pp"), p.get("pd"), "P"), (p.get("kp"), p.get("kd"), "K"))
            if px is not None]
    ok = [o for o in have if deep(o[1])]
    pool = ok or have
    if not pool:
        p["price"], p["vn"], p["th"] = None, None, None
        return
    px, _, vn = min(pool, key=lambda o: (o[0], o[2] != "P"))      # a tie stays on Polymarket
    p["price"], p["vn"], p["th"] = px, vn, (None if ok else 1)


def verify(picks, wanted, workers=4):
    """For each pick wanted(p) is true for (it could make Top 25 or Value) whose depth isn't
    known to be enough on an exchange that prices it, read that exchange's full book: the
    Kalshi orderbook ("_kt" ticker), the Polymarket US book ("_ps" slug) or the CLOB book of
    the side's token ("_pt"). Then choose() again. Returns how many books were read."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for p in picks:
        if not wanted(p):
            continue
        if p.get("kp") is not None and not deep(p.get("kd")) and p.get("_kt"):
            jobs.append((p, "kd", fetch_kalshi, p["_kt"], True))
        if p.get("pp") is not None and not deep(p.get("pd")):
            if p.get("_ps"):
                jobs.append((p, "pd", fetch_pmus, p["_ps"], True))
            elif p.get("_pt"):
                jobs.append((p, "pd", fetch_clob, p["_pt"], False))

    def run(job):
        p, col, fn, key, sided = job
        try:
            r = fn(key)
        except Exception:  # noqa: BLE001 — unreadable: depth stays unknown, which doesn't count
            return job, None
        return job, (r[p["side"]] if sided else r)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (p, col, _fn, _key, _s), usd in ex.map(run, jobs):
            if usd is not None:
                p[col] = round(usd, 2)
    for p in {id(j[0]): j[0] for j in jobs}.values():
        choose(p)
    return len(jobs)

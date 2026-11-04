"""
Prop Streak Lab — Polymarket US / Kalshi arbitrage finder (team only: team/arbs.enc).

An arb is one player prop (same player, stat, line, game) where buying the over on one
exchange and the under on the other costs less than $1.00 a pair, fees included: one of the
two pays $1.00 whatever happens. It counts when the return on the money staked is MIN_RET+
(1%) after fees and at least depth.MIN_USD ($25) can be put on EACH side at prices that keep it
there, the site's $25 rule read from the live order books.

Two steps:
  1. Each builder, after its usual fetches, calls note(sport, quotes, kalshi_markets, pkey) with
     every Polymarket US quote it read (both sides) and the Kalshi rungs (kalshi.fetch, both
     sides). That pairs the same prop at the same line on the same game date and saves the pairs
     whose quoted prices are under $1.00 after fees to .arbs/<sport>.json (not committed). No
     extra requests.
  2. `python arbs.py` (update_pass.sh, after the builders) reads both live books of each of those
     pairs, keeps the real arbs and writes team/arbs.enc, encrypted with TEAM_DASH_PASSWORD like
     team/spreads.enc, rewritten only on a change. The dashboard's Arbitrage tab reads it.

Fees (taker, per contract at price p): FEE["P"] x p x (1 - p) on Polymarket US (sports, 0.05) and
FEE["K"] x p x (1 - p) on Kalshi (0.07), each order's fee rounded up to the cent. Kalshi lists a
prop as "N+": over 1.5 is "2+" Yes, the under is its No. Lines must match exactly.

Standard library only. Never fatal: note() never raises, and main() exits 0 on any error.
"""
import datetime
import glob
import json
import math
import os
import sys

import depth
import kalshi

FEE = {"P": 0.05, "K": 0.07}     # taker fee coefficient: fee = FEE x contracts x p x (1 - p)
MIN_RET = 0.01                   # 1%+ return on the money staked, after fees (the owner's call, Nov 4, 2026)
MIN_USD = depth.MIN_USD          # $25+ on each side at prices that keep the arb at MIN_RET+
NOTES = ".arbs"                  # builders' pairs for this pass (gitignored)
FRESH_MIN = 30                   # a note older than this (its builder failed this pass) is ignored
NEAR = 8                         # closest misses kept for the dashboard
KEEP_DAYS = 30                   # arbs kept in the log
OUT = os.path.join("team", "arbs.enc")
VENUE = {"P": "Polymarket", "K": "Kalshi"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def fee(ex, p, n=1.0):
    """Taker fee on n contracts bought at p on exchange ex ("P" or "K"), unrounded."""
    return FEE[ex] * n * p * (1 - p)


def order_fee(ex, p_n):
    """One order's fee, rounded up to the cent. p_n: [(price, contracts)] it filled at."""
    return math.ceil(round(sum(fee(ex, p, n) for p, n in p_n) * 100, 6)) / 100


def unit_cost(po, exo, pu, exu):
    """What one over + one under cost, fees included (no rounding)."""
    return po + pu + fee(exo, po) + fee(exu, pu)


def ret(cost):
    """Return on the money staked when the pair pays $1.00."""
    return 1 / cost - 1 if cost > 0 else -1


# ---------------------------------------------------------------- step 1: pair the quotes
def from_games(games, stat_key=None):
    """Polymarket US quotes from an NBA/NHL/MLB builder's fetch_markets_us() games: each pm with a
    "us" slug (the global book's markets aren't tradable in the US and are skipped)."""
    out = []
    for g in games or []:
        for m in g.get("markets") or []:
            pm = m.get("pm") or {}
            if not pm.get("us"):
                continue
            sk = pm.get("sk") or (stat_key(pm.get("statText")) if stat_key else None)
            if sk:
                out.append({"player": pm["player"], "sk": sk, "line": pm["line"], "dates": [g.get("date")],
                            "over": pm.get("over"), "under": pm.get("under"), "slug": pm["us"]})
    return out


def from_pmus(pmus):
    """Polymarket US quotes from build.py's fetch_pmus_prices() (prices in cents)."""
    c = lambda v: v / 100 if v is not None else None
    return [{"player": v.get("who") or k[0], "sk": k[1], "line": k[2], "dates": v.get("dates") or [],
             "over": c(v.get("over")), "under": c(v.get("under")), "slug": v.get("slug")}
            for k, v in (pmus or {}).items() if v.get("slug")]


def pair(quotes, markets, keyfn):
    """Each Polymarket US quote with the Kalshi rung for the same player, stat and line on the same
    game date (the first of its dates Kalshi lists). Only tradeable Kalshi prices count."""
    idx = kalshi.index(markets, keyfn)
    out = []
    for q in quotes:
        dates = [d for d in q.get("dates") or [] if d]
        k = kalshi.find(idx, keyfn(q["player"]), q["sk"], q["line"], dates) if dates else None
        if not k:
            continue
        out.append({"player": q["player"], "sk": q["sk"], "line": round(float(q["line"]), 1), "date": k["date"],
                    "P": {"over": q.get("over"), "under": q.get("under"), "slug": q["slug"]},
                    "K": {"over": kalshi.side_price(k, "over"), "under": kalshi.side_price(k, "under"),
                          "ticker": k["ticker"]}})
    return out


def combos(pr):
    """The two ways to cover one paired prop: over on one exchange, under on the other, at the
    quoted prices, cheapest first. Each: {"over": ex, "under": ex, "po", "pu", "cost", "ret"}."""
    out = []
    for exo, exu in (("P", "K"), ("K", "P")):
        po, pu = pr[exo]["over"], pr[exu]["under"]
        if po is None or pu is None:
            continue
        c = unit_cost(po, exo, pu, exu)
        out.append({"over": exo, "under": exu, "po": po, "pu": pu, "cost": round(c, 4), "ret": round(ret(c), 4)})
    return sorted(out, key=lambda c: c["cost"])


def candidates(pairs):
    """(cands, near): the combos whose quoted cost is under $1.00 after fees (the books are read
    for these), and the NEAR closest of the rest. Each carries its prop's fields."""
    rows = []
    for pr in pairs:
        cs = combos(pr)
        if cs:
            rows.append({**{k: pr[k] for k in ("player", "sk", "line", "date")}, **cs[0],
                         "slug": pr["P"]["slug"], "ticker": pr["K"]["ticker"]})
    rows.sort(key=lambda r: r["cost"])
    return [r for r in rows if r["cost"] < 1], [r for r in rows if r["cost"] >= 1][:NEAR]


def note(sport, quotes, markets, keyfn, now=None, folder=NOTES):
    """Builder hook: pair this sport's quotes and save them for `python arbs.py`. Never raises."""
    try:
        if markets is None:
            print("  arbs: skipped (no Kalshi prices this run)")
            return 0
        pairs = pair(quotes, markets, keyfn)
        cands, near = candidates(pairs)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{sport}.json"), "w", encoding="utf-8") as f:
            json.dump({"sport": sport, "at": _iso(now or _now()), "n": len(pairs), "cands": cands, "near": near}, f)
        print(f"  arbs: {len(pairs)} prop(s) priced on both exchanges, {len(cands)} under $1.00 a pair after fees")
        return len(cands)
    except Exception as e:  # noqa: BLE001
        print(f"  arbs: skipped ({type(e).__name__}: {e})")
        return 0


# ---------------------------------------------------------------- step 2: the live books
def pm_levels(md):
    """Polymarket US book ("marketData") -> {"over": [(price, qty)], "under": [...]}, cheapest first:
    over = buy Yes from the offers, under = buy No at 1 - each Yes bid."""
    f = depth._f
    offers = [(f(o.get("px")), f(o.get("qty"))) for o in (md or {}).get("offers") or []]
    bids = [(f(b.get("px")), f(b.get("qty"))) for b in (md or {}).get("bids") or []]
    return {"over": sorted((p, q) for p, q in offers if p is not None and q and 0 < p < 1),
            "under": sorted((1 - p, q) for p, q in bids if p is not None and q and 0 < p < 1)}


def kalshi_levels(ob):
    """Kalshi orderbook -> the same shape: over = buy Yes at 1 - each No bid, under = buy No at
    1 - each Yes bid."""
    f = depth._f
    o = (ob or {}).get("orderbook_fp") or {}
    side = lambda key: sorted((1 - f(p), f(q)) for p, q in o.get(key) or []
                              if f(p) is not None and f(q) and 0 < f(p) < 1)
    return {"over": side("no_dollars"), "under": side("yes_dollars")}


def fill(over, exo, under, exu):
    """Walk the over's offers (on exo) and the under's (on exu) together, cheapest first, while each
    extra pair still returns MIN_RET+ after fees. Returns {"n": pairs, "usd_o", "usd_u", "fees",
    "cost", "profit", "ret", "po", "pu"} (po/pu: the best prices), or None when not even the first pair
    qualifies."""
    i = j = 0
    qo = over[0][1] if over else 0
    qu = under[0][1] if under else 0
    fo, fu = [], []
    while i < len(over) and j < len(under):
        po, pu = over[i][0], under[j][0]
        if ret(unit_cost(po, exo, pu, exu)) < MIN_RET:
            break
        q = min(qo, qu)
        fo.append((po, q))
        fu.append((pu, q))
        qo -= q
        qu -= q
        if qo <= 1e-9:
            i += 1
            qo = over[i][1] if i < len(over) else 0
        if qu <= 1e-9:
            j += 1
            qu = under[j][1] if j < len(under) else 0
    if not fo:
        return None
    n = sum(q for _, q in fo)
    usd_o, usd_u = sum(p * q for p, q in fo), sum(p * q for p, q in fu)
    fees = order_fee(exo, fo) + order_fee(exu, fu)
    cost = usd_o + usd_u + fees
    return {"n": round(n, 2), "usd_o": round(usd_o, 2), "usd_u": round(usd_u, 2), "fees": round(fees, 2),
            "cost": round(cost, 2), "profit": round(n - cost, 2), "ret": round(n / cost - 1, 4),
            "po": fo[0][0], "pu": fu[0][0]}


def judge(c, books):
    """One candidate against its live books ({"P": levels, "K": levels}): (arb, None) when it's real,
    else (None, why): "gone" (not MIN_RET+ at the live prices) or "thin" (under MIN_USD a side)."""
    exo, exu = c["over"], c["under"]
    r = fill(books[exo]["over"], exo, books[exu]["under"], exu)
    if r is None:
        return None, "gone"
    if r["usd_o"] < MIN_USD or r["usd_u"] < MIN_USD or r["ret"] < MIN_RET:   # on a sliver, the fee's cent rounding eats it
        return None, "thin"
    return {**{k: c[k] for k in ("sport", "player", "sk", "line", "date", "over", "under", "slug", "ticker")}, **r}, None


def read_books(c):
    pm = pm_levels(depth._get(depth.PMUS_BOOK.format(slug=c["slug"])).get("marketData") or {})
    ks = kalshi_levels(depth._get(depth.KALSHI_BOOK.format(ticker=c["ticker"])))
    return {"P": pm, "K": ks}


def check(cands, reader=read_books, workers=4):
    """(arbs, misses): each candidate judged on its live books; misses carry "why" ("gone", "thin",
    or "unread" when a book couldn't be read)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(c):
        try:
            return c, judge(c, reader(c))
        except Exception:  # noqa: BLE001
            return c, (None, "unread")

    arbs, misses = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, (a, why) in ex.map(one, cands):
            if a:
                arbs.append(a)
            else:
                misses.append({**c, "why": why})
    arbs.sort(key=lambda a: -a["ret"])
    return arbs, misses


def load_notes(now, folder=NOTES):
    """The builders' notes from this pass (FRESH_MIN or newer), by sport."""
    out = {}
    for path in glob.glob(os.path.join(folder, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            at = datetime.datetime.strptime(d["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if now - at <= datetime.timedelta(minutes=FRESH_MIN):
            out[d["sport"]] = d
    return out


def key(a):
    return "|".join(str(a[k]) for k in ("sport", "player", "sk", "line", "date", "over", "under"))


def step(state, notes, arbs, misses, now):
    """Fold this pass into state ({"now", "near", "scan", "log"}). Returns True when anything the
    dashboard shows changed (the times aside)."""
    before = json.dumps({k: state.get(k) for k in ("now", "near", "scan", "log")}, sort_keys=True)
    stamp = _iso(now)
    state["now"] = arbs
    near = misses + [{**r, "sport": s, "why": "quote"} for s, d in notes.items() for r in d.get("near") or []]
    state["near"] = sorted(near, key=lambda r: r["cost"])[:NEAR]
    state["scan"] = {s: {"n": d.get("n", 0), "cands": len(d.get("cands") or [])} for s, d in sorted(notes.items())}
    log = {e["id"]: e for e in state.get("log") or []}
    for a in arbs:
        e = log.get(key(a))
        if e is None:
            e = log[key(a)] = {"id": key(a), **{k: a[k] for k in ("sport", "player", "sk", "line", "date", "over", "under")},
                               "first": stamp, "runs": 0, "best": 0, "profit": 0, "usd": 0}
        e["last"] = stamp
        e["runs"] += 1
        e["best"] = max(e["best"], a["ret"])
        e["profit"] = max(e["profit"], a["profit"])
        e["usd"] = max(e["usd"], a["cost"])
    cut = (now - datetime.timedelta(days=KEEP_DAYS)).date().isoformat()
    state["log"] = sorted((e for e in log.values() if e["last"][:10] >= cut), key=lambda e: e["first"], reverse=True)
    after = json.dumps({k: state.get(k) for k in ("now", "near", "scan", "log")}, sort_keys=True)
    return before != after or not state.get("gen")


def read_state(password):
    import team_stats
    try:
        with open(OUT, encoding="ascii") as f:
            return json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        return {"now": [], "near": [], "scan": {}, "log": []}


def main():
    import team_stats
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    now = _now()
    notes = load_notes(now)
    cands = [{**c, "sport": s} for s, d in notes.items() for c in d.get("cands") or []]
    arbs, misses = check(cands) if cands else ([], [])
    print(f"arbs: {sum(d.get('n', 0) for d in notes.values())} prop(s) on both exchanges in {len(notes)} sport(s), "
          f"{len(cands)} candidate(s), {len(arbs)} arb(s) at {MIN_RET:.0%}+ after fees with ${MIN_USD:.0f}+ a side")
    for a in arbs:
        print(f"  {a['sport'].upper()} {a['player']} {a['sk']} {a['line']}: over on {VENUE[a['over']]} {a['po']:.2f}, "
              f"under on {VENUE[a['under']]} {a['pu']:.2f} -> {a['ret']:.1%} on ${a['cost']:.0f}")
    if not password:
        print("arbs: TEAM_DASH_PASSWORD not set, not saved")
        return 0
    state = read_state(password)    # an unreadable file raises: never start over and lose the log
    if not step(state, notes, arbs, misses, now):
        print("arbs: no change")
        return 0
    state["gen"] = _iso(now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":")), password) + "\n")
    print(f"arbs: wrote {OUT} ({len(arbs)} now, {len(state['log'])} in the last {KEEP_DAYS} days)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"arbs failed ({type(e).__name__}: {e})")
        sys.exit(0)

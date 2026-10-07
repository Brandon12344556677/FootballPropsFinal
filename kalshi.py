"""
Prop Streak Lab — Kalshi player-prop prices, shared by every builder.

Kalshi (kalshi.com, the CFTC-regulated exchange) lists the same kind of "at least N"
player props as Polymarket US, and its public trade API needs no key for prices. Each
per-game stat is one series (KXMLBHIT = hits, KXNFLRECYDS = receiving yards, ...), so one
request per series prices a whole slate. One market is one rung for one player in one game:

    event_ticker   KXMLBHIT-26OCT072000TBNYY       (game's US Eastern date: 26OCT07 = 2026-10-07)
    yes_sub_title  "Trent Grisham: 2+"             floor_strike 1.5, strike_type "greater"
    yes_bid_dollars "0.1800"  yes_ask_dollars "0.2000"  no_ask_dollars "0.8200"

"2+" is over 1.5. What you'd PAY: Over = buy Yes at the Yes ask, Under = buy No at the No
ask — the same convention as the Polymarket prices. A pick shows both venues' prices for
its side and is judged (Top 25 Surest, Value) on the cheaper one that has enough money offered
at it (depth.py); "vn" records which.

Standard library only. Never fatal: a series that can't be fetched prints
"    kalshi <series>: skipped (...)" and is left out; if every series fails, fetch() returns
None so callers keep the Kalshi prices they already had.
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.request

import depth

API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"Accept": "application/json", "User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}
PACE = 0.4               # seconds between requests: Kalshi rate-limits bursts (HTTP 429)

# Kalshi series -> each builder's stat key
SERIES = {
    "mlb": {"KXMLBHIT": "h", "KXMLBTB": "tb", "KXMLBHRR": "hrr", "KXMLBRBI": "rbi", "KXMLBHR": "hr",
            "KXMLBSB": "sb", "KXMLBKS": "k", "KXMLBOUTS": "outs", "KXMLBHA": "ha", "KXMLBERA": "er",
            "KXMLBWA": "pbb"},
    "nhl": {"KXNHLPTS": "pts", "KXNHLGOAL": "g", "KXNHLAST": "a", "KXNHLSAVE": "sv"},
    "nba": {"KXNBAPTS": "pts", "KXNBAREB": "reb", "KXNBAAST": "ast", "KXNBA3PT": "tpm", "KXNBASTL": "stl",
            "KXNBABLK": "blk", "KXNBAPRA": "pra", "KXNBAPR": "pr", "KXNBAPA": "pa", "KXNBARA": "ra"},
    "nfl": {"KXNFLPASSYDS": "pass_yds", "KXNFLPASSTDS": "pass_td", "KXNFLPASSCOMP": "pass_cmp",
            "KXNFLPASSATT": "pass_att", "KXNFLPASSINT": "pass_int", "KXNFLRSHYDS": "rush_yds",
            "KXNFLRSHATT": "rush_att", "KXNFLRECYDS": "rec_yds", "KXNFLREC": "rec", "KXNFLRRYDS": "rush_rec_yds"},
}
EVENT = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(?:\d{4})?[A-Z]+$")
RUNG = re.compile(r"^(.+?):\s*(\d+)\+\s*$")
MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _get(path, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(3 * (i + 1))       # rate-limited or a blip: back off, retry
        except (urllib.error.URLError, TimeoutError, OSError):
            if i == tries - 1:
                raise
            time.sleep(2)


def _ok(p):
    return p is not None and 0.02 < p < 0.98


def parse(m, sk):
    """One Kalshi market -> {"player", "sk", "line", "date", "over", "under", "tradeable",
    "ticker", "od", "ud"}, or None if it isn't a plain "Player: N+" rung. date is the game's US
    Eastern date (ISO); od/ud are the dollars offered at the best over / under price."""
    if m.get("status") not in (None, "active", "open") or m.get("strike_type") != "greater":
        return None
    rm = RUNG.match(m.get("yes_sub_title") or "")
    em = EVENT.match(m.get("event_ticker") or "")
    line = _f(m.get("floor_strike"))
    if not rm or not em or line is None or abs(line - (int(rm.group(2)) - 0.5)) > 1e-6:
        return None
    try:
        date = datetime.date(2000 + int(em.group(1)), MONTHS[em.group(2)], int(em.group(3)))
    except (KeyError, ValueError):
        return None
    ya, yb, na = _f(m.get("yes_ask_dollars")), _f(m.get("yes_bid_dollars")), _f(m.get("no_ask_dollars"))
    over = ya if _ok(ya) else None                  # buy Yes = over
    under = na if _ok(na) else None                 # buy No = under
    spread = (ya - yb) if ya is not None and yb is not None else None
    tradeable = (over is not None or under is not None) and (spread is None or spread <= 0.15)
    ys, bs = _f(m.get("yes_ask_size_fp")), _f(m.get("yes_bid_size_fp"))
    return {"player": rm.group(1).strip(), "sk": sk, "line": round(line, 1), "date": date.isoformat(),
            "over": over, "under": under, "tradeable": tradeable, "ticker": m.get("ticker"),
            "od": round(over * ys, 2) if over is not None and ys is not None else None,     # Yes ask x its size
            "ud": round(under * bs, 2) if under is not None and bs is not None else None}   # No ask = 1 - Yes bid


def fetch(sport, days=8):
    """Every open Kalshi player-prop rung for `sport` whose game is from yesterday to `days`
    ahead (US Eastern dates), parsed. None when every series failed."""
    lo = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    hi = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    out, failed = [], 0
    for series, sk in SERIES[sport].items():
        cursor = ""
        try:
            for _ in range(10):                     # pages of 1000; a week of NFL yards is ~800
                time.sleep(PACE)
                d = _get(f"/markets?series_ticker={series}&status=open&limit=1000"
                         + (f"&cursor={cursor}" if cursor else ""))
                ms = d.get("markets") or []
                for m in ms:
                    k = parse(m, sk)
                    if k and lo <= k["date"] <= hi:
                        out.append(k)
                cursor = d.get("cursor") or ""
                if not cursor or not ms:
                    break
        except Exception as e:  # noqa: BLE001
            print(f"    kalshi {series}: skipped ({e})")
            failed += 1
    if failed == len(SERIES[sport]):
        print(f"  kalshi: skipped (all {failed} {sport.upper()} series failed)")
        return None
    print(f"  kalshi: {len(out)} {sport.upper()} prop rungs priced"
          f"{f' ({failed} series skipped)' if failed else ''}")
    return out


def index(markets, keyfn):
    """(player key, stat, line) -> [market, ...], one per game date listed."""
    idx = {}
    for k in markets or []:
        idx.setdefault((keyfn(k["player"]), k["sk"], k["line"]), []).append(k)
    return idx


def et_date(start_utc):
    """'2026-10-08T02:05Z' -> '2026-10-07': a game's US Eastern date, as Kalshi dates it."""
    if not start_utc:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(start_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:  # noqa: BLE001 — no tz database: EDT/EST by month is close enough here
        return (t - datetime.timedelta(hours=4 if 3 <= t.month <= 10 else 5)).date().isoformat()


def find(idx, key, sk, line, dates):
    """The Kalshi market for this exact prop on one of `dates` (ET dates, first match wins)."""
    try:
        cands = idx.get((key, sk, round(float(line), 1))) or []
    except (TypeError, ValueError):
        return None
    for d in dates:
        for k in cands:
            if k["date"] == d:
                return k
    return None


def side_price(k, side):
    """What you'd pay on Kalshi for one side, or None (no market, or not tradeable)."""
    if not k or not k.get("tradeable"):
        return None
    return k["over"] if side == "over" else k["under"]


def best(pp, kp):
    """(price, venue) from the Polymarket and Kalshi prices of one side: the cheaper wins
    ("P" on a tie, the site's original book); (None, None) when neither has one."""
    if kp is not None and (pp is None or kp < pp):
        return kp, "K"
    if pp is not None:
        return pp, "P"
    return None, None


def apply(picks, markets, keyfn, is_open):
    """Kalshi side by side with Polymarket on every pending pick is_open(p) allows (its game
    hasn't locked): pp = Polymarket's price for the pick's side, kp = Kalshi's (None when
    Kalshi doesn't list that exact prop at that line), kd = dollars offered at Kalshi's price,
    price/vn = the cheaper of the two with enough money offered (depth.choose) — the price
    Top 25 Surest and Value are judged on. Prices are fractions (MLB/NHL/NBA). markets None
    (Kalshi unreachable this run) keeps each pick's last Kalshi price. Returns how many picks
    have a Kalshi price."""
    idx = index(markets, keyfn) if markets is not None else None
    n = 0
    for p in picks:
        if p.get("res") is not None or not is_open(p):
            continue
        if p.get("vn") is None and p.get("pp") is None and p.get("kp") is None and p.get("price") is not None:
            p["pp"] = p["price"]        # recorded before Kalshi was added: that price is Polymarket's
        if idx is not None:
            if p.get("start"):
                dates = [et_date(p["start"])]
            else:                       # ESPN's UTC date, or the day before for a late game
                d = datetime.date.fromisoformat(p["date"])
                dates = [d.isoformat(), (d - datetime.timedelta(days=1)).isoformat()]
            k = find(idx, keyfn(p["player"]), p["stat"], p["line"], dates)
            kp = side_price(k, p["side"])
            p["kp"] = round(kp, 3) if kp is not None else None
            p["kd"] = k["od" if p["side"] == "over" else "ud"] if kp is not None else None
            p["_kt"] = k["ticker"] if kp is not None else None     # for depth.verify (not saved)
        depth.choose(p)
        n += p.get("kp") is not None
    return n

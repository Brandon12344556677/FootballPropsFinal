"""
Prop Streak Lab — the spread tester (team only, never on the public site).

Tests game spreads on Polymarket US privately, for every sport, the way parlay.py tests parlays.

Model (per sport, refit every pass from final scores):
  - NBA, NFL: a point-margin rating for each team plus a home edge, least squares on every final
    since the previous season, recent games weighted more (HALF_LIFE days), shrunk toward average
    (SHRINK games at 0). Margins ~ Normal(expected margin, sigma), sigma from the fit's misses.
  - NHL, MLB: each team's scoring and allowing rates plus a home factor (Poisson-style, fitted the
    same way). Each side's score ~ negative binomial (dispersion fitted from the data; Poisson when
    there is none), the margin from the two; a tie goes to overtime / extra innings as a 1-goal or
    1-run win, split by the two scoring rates.
  A team "covers +L" when its final margin plus L is above 0 (Polymarket's rule, overtime included).

Picks (Balanced): from OPEN_AT ET, for each game today that starts LEAD_MIN+ minutes later, every
line in its full-game spread ladder, both sides (Yes = the team +L at the ask; No = the other team
-L at 1 - bid). A side qualifies at a price of MIN_PRICE-MAX_PRICE, MIN_USD+ offered near it, and
the model MIN_EDGE to MAX_EDGE above the price (a bigger gap is news the model can't see); the
game's best edge is recorded, at most one pick a game, frozen once made. Graded from ESPN's final score as a 1-unit bet at the recorded price (a win pays
1/price - 1); a game still not final VOID_AFTER_DAYS later is void.

Data: ESPN's public scoreboards (one request per league-month), cached in spread_scores.json
(public scores; refreshed for recent months each pass). Picks: team/spreads.enc, encrypted with
TEAM_DASH_PASSWORD like team/parlays.enc, rewritten only on a change. edge_report.py grades them
in the edge tracker; the dashboard's Spreads tab shows them.

  python spreads.py             one pass (the update job)
  python spreads.py backtest    replay last season: are the model's cover chances calibrated?

Standard library only. Never fails the deploy.
"""
import datetime
import json
import math
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import depth
import team_stats

OUT = os.path.join("team", "spreads.enc")
SCORES = "spread_scores.json"
ET = ZoneInfo("America/New_York")
UA = {"Accept": "application/json", "User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}
ESPN = "https://site.web.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={dates}&limit=500"   # site.api.espn.com refuses UA
PM_EVENTS = ("https://gateway.polymarket.us/v1/events?tagSlug={tag}&active=true&closed=false"
             "&startDateMin={a}T00:00:00Z&startDateMax={b}T00:00:00Z&limit=200")
PM_EVENT = "https://gateway.polymarket.us/v1/events/slug/{slug}"
PM_BOOK = "https://gateway.polymarket.us/v1/markets/{slug}/book"

# sport: ESPN path, in-season months, kind, half-life (days), shrink (games at average)
SPORTS = {
    "nba": {"path": "basketball/nba", "months": {10, 11, 12, 1, 2, 3, 4, 5, 6}, "kind": "normal", "half": 120, "shrink": 3},
    "nfl": {"path": "football/nfl", "months": {9, 10, 11, 12, 1, 2}, "kind": "normal", "half": 200, "shrink": 4,
            "sigma_min": 13.5, "home0": 1.5, "home_k": 150},   # home edge pulled toward 1.5 points   # 17 games a season: the fit's own misses understate how random a game is
    "nhl": {"path": "hockey/nhl", "months": {10, 11, 12, 1, 2, 3, 4, 5, 6}, "kind": "count", "half": 150, "shrink": 6},
    "mlb": {"path": "baseball/mlb", "months": {3, 4, 5, 6, 7, 8, 9, 10, 11}, "kind": "count", "half": 120, "shrink": 10},
}
MONTHS_BACK = 19          # every final since about the start of the previous season
REFRESH_DAYS = 40         # months touching the last 40 days are re-read every pass
MIN_GAMES = 5             # a team needs this many finals in the data to be priced
# Calibration: chances come out p' = sigmoid(CAL * logit(p)). The raw NHL, NFL and MLB models were
# overconfident in the backtest of the 2025-26 seasons (the NFL model's 65% covered 58%), so they
# are pulled toward 50%; CAL is the stretch that fit best there (python spreads.py backtest
# prints a fresh fit). 1 = unchanged.
CAL = {"nba": 1.0, "nfl": 1.0, "nhl": 0.83, "mlb": 0.87}   # fit Oct 20, 2026

OPEN_AT = (11, 0)         # ET
LEAD_MIN = 45
MIN_PRICE, MAX_PRICE = 0.35, 0.65
MIN_EDGE = 0.05
MAX_EDGE = 0.15           # a bigger gap against a liquid market is almost always news the model can't see
MIN_USD = depth.MIN_USD
VOID_AFTER_DAYS = 3


# ---------------------------------------------------------------- data
def http_json(url, timeout=30, tries=2):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            err = e
            if getattr(e, "code", None) in (400, 403, 404):
                break
            if i < tries - 1:
                time.sleep(1.5)
    raise err


def parse_espn(doc):
    """ESPN scoreboard -> game dicts (regular season and playoffs only)."""
    out = []
    for e in (doc or {}).get("events") or []:
        if ((e.get("season") or {}).get("type")) not in (2, 3):
            continue
        comp = (e.get("competitions") or [{}])[0]
        side = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in side or "away" not in side:
            continue
        st = (e.get("status") or {}).get("type") or {}
        g = {"id": str(e.get("id")), "start": e.get("date"), "neutral": bool(comp.get("neutralSite")),
             "home": side["home"]["team"].get("abbreviation"), "away": side["away"]["team"].get("abbreviation"),
             "hname": (side["home"]["team"].get("name") or "").lower(), "aname": (side["away"]["team"].get("name") or "").lower(),
             "state": st.get("state"), "final": bool(st.get("completed"))}
        if g["final"]:
            try:
                g["hs"], g["as"] = int(float(side["home"].get("score"))), int(float(side["away"].get("score")))
            except (TypeError, ValueError):
                g["final"] = False
        out.append(g)
    return out


def months_to_read(sport, today, cached):
    """YYYYMM keys: every in-season month in the window not cached yet, plus recent ones."""
    out, y, m = [], today.year, today.month
    for _ in range(MONTHS_BACK + 1):
        key = f"{y:04d}{m:02d}"
        recent = (today - datetime.date(y, m, 1)).days <= REFRESH_DAYS + 31
        if m in SPORTS[sport]["months"] and (key not in cached or recent):
            out.append(key)
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def load_scores(today, read=True):
    """{sport: [final games]} from the cache, re-reading recent and missing months from ESPN."""
    try:
        with open(SCORES, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    changed = False
    if read:
        for sport, cfg in SPORTS.items():
            mine = cache.setdefault(sport, {})
            for key in months_to_read(sport, today, mine):
                try:
                    games = parse_espn(http_json(ESPN.format(path=cfg["path"], dates=key)))
                except Exception as e:  # noqa: BLE001
                    print(f"    spreads: {sport} {key} skipped ({type(e).__name__})")   # one month: health.py waits for repeats
                    continue
                rows = sorted([g["start"][:10], g["home"], g["away"], g["hs"], g["as"], int(g["neutral"]), g["id"]]
                              for g in games if g["final"])
                if mine.get(key) != rows:
                    mine[key], changed = rows, True
            if changed:   # after each sport: a first run cut off by its time limit keeps what it read
                with open(SCORES, "w", encoding="utf-8") as f:
                    json.dump(cache, f, separators=(",", ":"), sort_keys=True)
        oldest = (today - datetime.timedelta(days=31 * (MONTHS_BACK + 1))).strftime("%Y%m")
        for sport in cache:
            for key in [k for k in cache[sport] if k < oldest]:
                del cache[sport][key]; changed = True
        if changed:
            with open(SCORES, "w", encoding="utf-8") as f:
                json.dump(cache, f, separators=(",", ":"), sort_keys=True)
    return {s: sorted({r[6]: r for rows in cache.get(s, {}).values() for r in rows}.values()) for s in SPORTS}


# ---------------------------------------------------------------- model
def weights(games, asof, half):
    a = datetime.date.fromisoformat(asof)
    return [0.5 ** (max(0, (a - datetime.date.fromisoformat(g[0])).days) / half) for g in games]


def fit_normal(games, asof, cfg):
    """Margin ratings: home margin = h + r[home] - r[away] + noise."""
    w = weights(games, asof, cfg["half"])
    teams = {t for g in games for t in (g[1], g[2])}
    r, h, lam = {t: 0.0 for t in teams}, 0.0, cfg["shrink"]
    for _ in range(60):
        num = sum(wi * ((g[3] - g[4]) - (r[g[1]] - r[g[2]])) for wi, g in zip(w, games) if not g[5])
        den = sum(wi for wi, g in zip(w, games) if not g[5])
        h = (num + cfg.get("home_k", 1) * cfg.get("home0", 0.0)) / (den + cfg.get("home_k", 1))
        acc = {t: [0.0, lam] for t in teams}
        for wi, g in zip(w, games):
            hh = 0.0 if g[5] else h
            m = g[3] - g[4]
            acc[g[1]][0] += wi * (m - hh + r[g[2]]); acc[g[1]][1] += wi
            acc[g[2]][0] += wi * (-(m - hh) + r[g[1]]); acc[g[2]][1] += wi
        r = {t: a / b for t, (a, b) in acc.items()}
        mean = sum(r.values()) / len(r)
        r = {t: v - mean for t, v in r.items()}
    res = [(wi, (g[3] - g[4]) - ((0.0 if g[5] else h) + r[g[1]] - r[g[2]])) for wi, g in zip(w, games)]
    sw = sum(wi for wi, _ in res) or 1.0
    sigma = max(math.sqrt(sum(wi * e * e for wi, e in res) / sw) if res else 12.0, cfg.get("sigma_min", 0))
    n = {t: 0 for t in teams}
    for g in games:
        n[g[1]] += 1; n[g[2]] += 1
    return {"kind": "normal", "r": r, "h": h, "sigma": sigma, "n": n}


def fit_count(games, asof, cfg):
    """Scoring rates: home score ~ mu*H*att[home]*dfn[away], away ~ mu*att[away]*dfn[home]."""
    w = weights(games, asof, cfg["half"])
    teams = {t for g in games for t in (g[1], g[2])}
    sw = sum(w) or 1.0
    mu = sum(wi * g[4] for wi, g in zip(w, games)) / sw or 1.0
    H = (sum(wi * g[3] for wi, g in zip(w, games)) / sw) / mu if mu else 1.0
    att, dfn, k = {t: 1.0 for t in teams}, {t: 1.0 for t in teams}, cfg["shrink"]
    hf = lambda g: 1.0 if g[5] else H  # noqa: E731
    for _ in range(40):
        a_num, a_den = {t: k for t in teams}, {t: k for t in teams}
        for wi, g in zip(w, games):
            a_num[g[1]] += wi * g[3]; a_den[g[1]] += wi * mu * hf(g) * dfn[g[2]]
            a_num[g[2]] += wi * g[4]; a_den[g[2]] += wi * mu * dfn[g[1]]
        att = {t: a_num[t] / a_den[t] for t in teams}
        d_num, d_den = {t: k for t in teams}, {t: k for t in teams}
        for wi, g in zip(w, games):
            d_num[g[2]] += wi * g[3]; d_den[g[2]] += wi * mu * hf(g) * att[g[1]]
            d_num[g[1]] += wi * g[4]; d_den[g[1]] += wi * mu * att[g[2]]
        dfn = {t: d_num[t] / d_den[t] for t in teams}
        hn = sum(wi * g[3] for wi, g in zip(w, games) if not g[5])
        hd = sum(wi * mu * att[g[1]] * dfn[g[2]] for wi, g in zip(w, games) if not g[5])
        H = hn / hd if hd else 1.0
        mu = sum(wi * g[4] for wi, g in zip(w, games)) / (sum(wi * att[g[2]] * dfn[g[1]] for wi, g in zip(w, games)) or 1.0)
    # dispersion: Var = lam + lam^2 / disp (negative binomial); none left over -> Poisson
    ex = sx = 0.0
    for wi, g in zip(w, games):
        for score, lam in ((g[3], mu * hf(g) * att[g[1]] * dfn[g[2]]), (g[4], mu * att[g[2]] * dfn[g[1]])):
            ex += wi * ((score - lam) ** 2 - lam); sx += wi * lam * lam
    disp = sx / ex if ex > 0 else None
    n = {t: 0 for t in teams}
    for g in games:
        n[g[1]] += 1; n[g[2]] += 1
    return {"kind": "count", "mu": mu, "H": H, "att": att, "dfn": dfn, "disp": disp, "n": n}


def fit(sport, games, asof):
    games = [g for g in games if g[0] < asof]
    return (fit_normal if SPORTS[sport]["kind"] == "normal" else fit_count)(games, asof, SPORTS[sport])


def score_pmf(lam, disp, top):
    if disp is None or disp > 1e6:
        p = [math.exp(-lam)]
        for k in range(1, top + 1):
            p.append(p[-1] * lam / k)
        return p
    r, q = disp, disp / (disp + lam)
    return [math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(q) + k * math.log(1 - q))
            for k in range(top + 1)]


def margin_dist(model, home, away, neutral=False):
    """{home margin: chance} (count sports) or (mean, sigma) (normal sports)."""
    if model["kind"] == "normal":
        return (0.0 if neutral else model["h"]) + model["r"].get(home, 0.0) - model["r"].get(away, 0.0), model["sigma"]
    lh = model["mu"] * (1.0 if neutral else model["H"]) * model["att"].get(home, 1.0) * model["dfn"].get(away, 1.0)
    la = model["mu"] * model["att"].get(away, 1.0) * model["dfn"].get(home, 1.0)
    top = int(max(lh, la) * 4 + 12)
    ph, pa = score_pmf(lh, model["disp"], top), score_pmf(la, model["disp"], top)
    out = {}
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            out[i - j] = out.get(i - j, 0.0) + x * y
    tie, qh = out.pop(0, 0.0), lh / (lh + la)
    out[1] = out.get(1, 0.0) + tie * qh          # overtime / extra innings: a 1-goal or 1-run win
    out[-1] = out.get(-1, 0.0) + tie * (1 - qh)
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def calibrated(p, sport):
    a = CAL.get(sport, 1.0)
    p = min(max(p, 1e-6), 1 - 1e-6)
    return 1 / (1 + math.exp(-a * math.log(p / (1 - p))))


def cover_chance(dist, line, home_side=True):
    """Chance the side covers +line: its margin + line > 0 (half-point lines; whole lines can push)."""
    if isinstance(dist, tuple):
        mean, sigma = dist
        m = mean if home_side else -mean
        return 0.5 * (1 + math.erf((m + line) / (sigma * math.sqrt(2))))
    return sum(p for d, p in dist.items() if (d if home_side else -d) + line > 0)


# ---------------------------------------------------------------- picks
def start_utc(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def ladders(sport, today):
    """Polymarket US full-game spread markets of today's games: [{name, team, line, slug}]."""
    a, b = today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()
    events = (http_json(PM_EVENTS.format(tag=sport, a=a, b=b)) or {}).get("events") or []
    pat = re.compile(rf"^{sport}-[a-z]+-[a-z]+-{a}$")
    out = []
    for ev in events:
        if not pat.match(ev.get("slug") or ""):
            continue
        try:
            full = (http_json(PM_EVENT.format(slug=ev["slug"])) or {}).get("event") or {}
        except Exception:  # noqa: BLE001
            continue
        for m in full.get("markets") or []:
            if not (m.get("sportsMarketType") or "").endswith("_full_game_spread") or m.get("closed"):
                continue
            side = next((s for s in m.get("marketSides") or [] if s.get("long")), None) or {}
            team = side.get("team") or {}
            try:
                line = float(m.get("line"))
            except (TypeError, ValueError):
                continue
            if line == int(line):
                continue   # whole-number lines can push: left out
            out.append({"event": ev["slug"], "name": (team.get("name") or "").lower(),
                        "abbr": (team.get("abbreviation") or "").upper(), "line": line, "slug": m.get("slug")})
    return out


def books(slugs):
    def one(slug):
        time.sleep(0.3)
        try:
            return slug, depth.pmus_book((http_json(PM_BOOK.format(slug=slug)) or {}).get("marketData") or {})
        except Exception:  # noqa: BLE001
            return slug, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, slugs))


def choose(game, model, rungs, book, sport):
    """The game's best qualifying side, or None. game: ESPN dict; rungs: its ladder markets."""
    dist = margin_dist(model, game["home"], game["away"], game["neutral"])
    best = None
    for m in rungs:
        bk = book.get(m["slug"])
        if not bk:
            continue
        team_home = m["name"] == game["hname"] or (not m["name"] and m["abbr"] == game["home"])
        p_yes = calibrated(cover_chance(dist, m["line"], home_side=team_home), sport)
        sides = (("yes", bk.get("ask"), bk.get("over"), p_yes, m["line"], team_home),
                 ("no", None if bk.get("bid") is None else 1 - bk["bid"], bk.get("under"), 1 - p_yes, -m["line"], not team_home))
        for kind, price, usd, p, line, is_home in sides:
            if price is None or not MIN_PRICE <= price <= MAX_PRICE or (usd or 0) < MIN_USD or not MIN_EDGE <= p - price <= MAX_EDGE:
                continue
            if best is None or p - price > best["edge"]:
                best = {"team": game["home"] if is_home else game["away"], "opp": game["away"] if is_home else game["home"],
                        "home": is_home, "line": line, "price": round(price, 4), "model": round(p, 4),
                        "edge": round(p - price, 4), "side": kind, "slug": m["slug"], "usd": round(usd or 0)}
    return best


def grade(pick, finals, today):
    g = finals.get(pick["gid"])
    if g is not None:
        margin = (g[3] - g[4]) * (1 if pick["home"] else -1)
        pick["final"] = f"{g[2]} {g[4]} - {g[1]} {g[3]}"
        if margin + pick["line"] > 0:
            pick["res"], pick["units"] = "hit", round(1 / pick["price"] - 1, 3)
        else:
            pick["res"], pick["units"] = "miss", -1.0
        return True
    if (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(pick["date"])).days > VOID_AFTER_DAYS:
        pick["res"], pick["units"] = "void", 0.0
        return True
    return False


def step(state, scores, now, fetch=True):
    """Grade open picks, then look for today's. Returns True if anything changed."""
    et = now.astimezone(ET)
    today = et.date().isoformat()
    picks = state.setdefault("picks", [])
    finals = {g[6]: g for games in scores.values() for g in games}
    changed = False
    for p in picks:
        if not p.get("res"):
            changed |= grade(p, finals, today)
    if not fetch or (et.hour, et.minute) < OPEN_AT:
        return changed
    done = {p["gid"] for p in picks}
    for sport, cfg in SPORTS.items():
        try:
            todays = [g for g in parse_espn(http_json(ESPN.format(path=cfg["path"], dates=et.strftime("%Y%m%d"))))
                      if g["state"] == "pre" and g["id"] not in done
                      and (start_utc(g["start"]) or now) >= now + datetime.timedelta(minutes=LEAD_MIN)]
            if not todays:
                continue
            model = fit(sport, scores[sport], today)
            todays = [g for g in todays if min(model["n"].get(g["home"], 0), model["n"].get(g["away"], 0)) >= MIN_GAMES]
            rungs = ladders(sport, et.date())
            book = books([r["slug"] for r in rungs if any(r["name"] in (g["hname"], g["aname"]) for g in todays)])
        except Exception as e:  # noqa: BLE001
            print(f"  spreads: {sport} skipped ({type(e).__name__}: {e})")
            continue
        for g in todays:
            mine = [r for r in rungs if r["name"] in (g["hname"], g["aname"])]
            pick = choose(g, model, mine, book, sport)
            if pick:
                picks.append(dict(pick, sport=sport, date=today, gid=g["id"], start=g["start"],
                                  game=f"{g['away']} @ {g['home']}", made=now.strftime("%Y-%m-%dT%H:%MZ"), res=None))
                changed = True
                print(f"  spreads: {sport} {g['away']} @ {g['home']}: {pick['team']} {pick['line']:+g} at "
                      f"{round(pick['price'] * 100)}c, model {round(pick['model'] * 100)}%")
    return changed


# ---------------------------------------------------------------- backtest
def backtest(scores, sport, start, end, every=7, calibrate=True):
    """Replay start..end: ratings from earlier games only (refit every `every` days); the chance each
    game's home side covers a grid of lines against what happened. Returns calibration rows."""
    games = [g for g in scores[sport] if start <= g[0] <= end]
    grid = {"normal": [-14.5, -10.5, -7.5, -4.5, -2.5, -0.5, 0.5, 2.5, 4.5, 7.5, 10.5, 14.5],
            "count": [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]}[SPORTS[sport]["kind"]]
    if sport == "mlb":
        grid = [-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5]
    model, fit_on, rows = None, None, []
    for g in games:
        if model is None or (datetime.date.fromisoformat(g[0]) - datetime.date.fromisoformat(fit_on)).days >= every:
            fit_on = g[0]
            model = fit(sport, scores[sport], fit_on)
        if min(model["n"].get(g[1], 0), model["n"].get(g[2], 0)) < MIN_GAMES:
            continue
        dist = margin_dist(model, g[1], g[2], bool(g[5]))
        for line in grid:
            p = calibrated(cover_chance(dist, line, True), sport) if calibrate else cover_chance(dist, line, True)
            if 0.03 < p < 0.97:
                rows.append((p, 1 if (g[3] - g[4]) + line > 0 else 0))
    return rows


def fit_cal(rows):
    """The stretch a (sigmoid(a * logit(p))) with the lowest log loss on rows of raw chances."""
    def loss(a):
        t = 0.0
        for p, y in rows:
            q = 1 / (1 + math.exp(-a * math.log(p / (1 - p))))
            t -= math.log(q if y else 1 - q)
        return t
    return min((x / 100 for x in range(40, 131)), key=loss)


def report(rows):
    if not rows:
        return "no games"
    brier = sum((p - y) ** 2 for p, y in rows) / len(rows)
    base = sum(y for _, y in rows) / len(rows)
    out = [f"{len(rows)} line checks, Brier {brier:.4f}"]
    for lo in [x / 10 for x in range(10)]:
        b = [(p, y) for p, y in rows if lo <= p < lo + 0.1]
        if len(b) >= 30:
            out.append(f"  model {lo:.1f}-{lo + 0.1:.1f}: said {sum(p for p, _ in b) / len(b):.3f}, "
                       f"happened {sum(y for _, y in b) / len(b):.3f} (n={len(b)})")
    return "\n".join(out) + f"\n  (every line at the overall rate {base:.3f} would score Brier {base * (1 - base):.4f})"


# ---------------------------------------------------------------- main
def read_state(password):
    try:
        with open(OUT, encoding="ascii") as f:
            return json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        return {"picks": []}


def main(args):
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(ET).date()
    if args[:1] == ["backtest"]:
        scores = load_scores(today)
        for sport, (a, b) in {"nba": ("2025-11-15", "2026-06-30"), "nhl": ("2025-11-15", "2026-06-30"),
                              "nfl": ("2025-10-01", "2026-02-28"), "mlb": ("2025-05-01", "2025-11-30")}.items():
            raw = backtest(scores, sport, a, b, calibrate=False)
            print(f"{sport}: {len(scores[sport])} finals; best stretch on the raw model {fit_cal(raw):.2f} "
                  f"(in use {CAL[sport]})\n{report(backtest(scores, sport, a, b))}")
        return 0
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("spreads: TEAM_DASH_PASSWORD not set, skipping")
        return 0
    state = read_state(password)    # an unreadable file raises: never start over and lose the record
    scores = load_scores(today)
    if not step(state, scores, now):
        print(f"spreads: no change ({len(state.get('picks', []))} pick(s) on record)")
        return 0
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":")), password) + "\n")
    print(f"spreads: wrote {OUT} ({len(state['picks'])} pick(s) on record)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print(f"spreads failed ({type(e).__name__}: {e})")
        sys.exit(0)

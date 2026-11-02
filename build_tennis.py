#!/usr/bin/env python3
"""
Prop Streak Lab — tennis data builder (sibling of build_nhl.py), ATP and WTA singles.

Tennis isn't priced as player props (neither exchange lists them): the page prices match markets.
Each match gets a model chance for the match winner, the game spread and the total games, set
against Polymarket US (match winner) and Kalshi (match winner, total games, game spread).

Model (refit every pass from results):
  - A rating per player per tour: an Elo over every completed singles match since HISTORY_START,
    overall plus one per surface, blended SURF_W toward the surface's (K shrinks with matches played,
    the FiveThirtyEight form). The win chance of one game on each player's serve comes from the two
    ratings and the tour/surface hold rate, so that the set-by-set chain below gives the Elo's match
    chance; the same chain gives every final scoreline, hence the total games and the game spread.
  - A set: games alternate serve, 6 games with a 2-game lead, a tiebreak at 6-6 (a final set too,
    since 2022 at every Slam: a 10-point one, counted as one game, as every exchange does).
  Best of 5 at the men's Slams, best of 3 otherwise.

Data: ESPN's public tennis scoreboards (every tournament active on a date, with its whole draw),
cached in tennis_results.json and re-read for recent weeks each pass.

  python build_tennis.py             one pass (the update job)
  python build_tennis.py backtest    replay the cached results: calibration and log loss

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

UA = {"Accept": "application/json", "User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}
ESPN_SB = "https://site.web.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={date}"
TOURS = ("atp", "wta")
RESULTS = "tennis_results.json"
HISTORY_START = datetime.date(2025, 1, 1)
STEP_DAYS = 5             # a tournament (with qualifying) runs 7+ days, so a date every 5 days sees each one
REFRESH_DAYS = 21         # dates in the last 3 weeks are re-read every pass
_START = time.time()
BUDGET_SEC = 240


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


# ---------------------------------------------------------------- surfaces
# ESPN doesn't say what a tournament is played on. Clay and grass events by name; everything else is
# hard (indoor hard included: the model doesn't split them).
CLAY = re.compile(r"roland|french open|monte.?carlo|madrid|internazionali|italian open|rome|barcelona|hamburg|"
                  r"estoril|munich|bmw open|geneva|lyon|bastad|nordea|gstaad|swiss open|umag|croatia|kitzb|"
                  r"generali|houston|clay court|marrakech|grand prix hassan|buenos aires|argentina open|rio open|"
                  r"santiago|chile open|cordoba|bogota|rabat|strasbourg|parma|palermo|budapest|prague|warsaw|"
                  r"charleston|credit one|rouen|istanbul|bucharest|iasi|portoroz|lausanne|hamburg|morocco", re.I)
GRASS = re.compile(r"wimbledon|queen|halle|terra wortmann|s-hertogenbosch|libema|libéma|eastbourne|mallorca|"
                   r"newport|hall of fame|stuttgart.*june|boss open|berlin|bad homburg|nottingham|birmingham|"
                   r"rothesay|ecotrans|lexus|ilkley|surbiton", re.I)


def surface(name, start):
    """'clay' / 'grass' / 'hard' for a tournament from its name and start date. Stuttgart is grass for
    the men (June) and clay for the women (April): the date decides."""
    n = name or ""
    month = int(str(start)[5:7] or 0)
    if re.search(r"stuttgart|porsche", n, re.I):
        return "grass" if month == 6 else "clay"
    if GRASS.search(n) and month in (6, 7):
        return "grass"
    if CLAY.search(n) and month in (2, 3, 4, 5, 6, 7, 8, 9):
        return "clay"
    return "hard"


# ---------------------------------------------------------------- results
SHORT_SETS = re.compile(r"next\s*gen", re.I)


def parse_scoreboard(doc, feed):
    """ESPN tennis scoreboard -> (matches, names, upcoming, gone). A match row:
    [date, tour, event id, surface, best of, round, p1, p2, winner (1 or 2), sets [[g1, g2], ...],
     status ("F" final, "R" retired), match id, start (UTC)].
    Players are ESPN athlete ids; names: {id: name}. Only finished singles matches (no walkovers); gone: the
    ids of matches over with no result (walkovers, cancellations), whose picks are void at once."""
    rows, names, upcoming, gone = [], {}, [], []
    for e in (doc or {}).get("events") or []:
        tour = feed
        surf = surface(e.get("name"), e.get("date") or "")
        major = bool(e.get("major"))
        for gr in e.get("groupings") or []:
            gname = ((gr.get("grouping") or {}).get("displayName") or "")
            if "Singles" not in gname:
                continue
            # combined events (the Slams, Indian Wells, Madrid...) list both draws under either tour's feed
            tour = "wta" if gname.startswith("Women") else "atp" if gname.startswith("Men") else tour
            for c in gr.get("competitions") or []:
                comp = c.get("competitors") or []
                if len(comp) != 2 or any(x.get("type") != "athlete" for x in comp):
                    continue
                comp = sorted(comp, key=lambda x: x.get("order") or 0)
                ids = [str(x.get("id")) for x in comp]
                for x, pid in zip(comp, ids):
                    names[pid] = ((x.get("athlete") or {}).get("displayName") or "").strip()
                st = ((c.get("status") or {}).get("type") or {})
                rnd = ((c.get("round") or {}).get("displayName") or "")
                bo = 5 if (major and tour == "atp" and not rnd.lower().startswith("qualifying")) else 3
                base = [str(c.get("date") or "")[:10], tour, str(e.get("id")), surf, bo, rnd]
                if st.get("state") == "pre":
                    # The Next Gen Finals play first-to-4 sets, which the scoreline chain doesn't model: never priced.
                    if not SHORT_SETS.search(e.get("name") or ""):
                        upcoming.append({"mid": str(c.get("id")), "tour": tour, "event": e.get("name"), "eid": str(e.get("id")),
                                         "surface": surf, "bo": bo, "round": rnd, "p1": ids[0], "p2": ids[1],
                                         "start": c.get("date") or c.get("startDate"),
                                         "tv": c.get("timeValid") is not False})   # False: ESPN's placeholder time, not a schedule
                    continue
                status = {"STATUS_FINAL": "F", "STATUS_RETIRED": "R"}.get(st.get("name"))
                ls = [x.get("linescores") or [] for x in comp]
                if not status or not ls[0] or len(ls[0]) != len(ls[1]):
                    if st.get("state") == "post":
                        gone.append(str(c.get("id")))   # over without a result: a walkover, a cancellation
                    continue
                sets = []
                for a, b in zip(*ls):
                    try:
                        sets.append([int(a.get("value")), int(b.get("value"))])
                    except (TypeError, ValueError):
                        sets = None
                        break
                if not sets:
                    continue
                win = 1 if comp[0].get("winner") else 2 if comp[1].get("winner") else 0
                if not win:
                    continue
                rows.append(base + [ids[0], ids[1], win, sets, status, str(c.get("id")), c.get("date")])
    return rows, names, upcoming, gone


def scan_dates(today, cached):
    """Dates (YYYYMMDD) to read: every STEP_DAYS since HISTORY_START not cached yet, plus recent ones."""
    out, d = [], HISTORY_START
    while d <= today:
        key = d.strftime("%Y%m%d")
        if key not in cached or (today - d).days <= REFRESH_DAYS:
            out.append(key)
        d += datetime.timedelta(days=STEP_DAYS)
    if today.strftime("%Y%m%d") not in out:
        out.append(today.strftime("%Y%m%d"))
    return out


def load_results(today, read=True):
    """{"matches": [rows], "names": {id: name}, "upcoming": [...]}: the cache, topped up from ESPN.
    The cache is {"dates": {tour: [YYYYMMDD read]}, "matches": {match id: row}, "names": {...}}."""
    try:
        with open(RESULTS, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    cache.setdefault("dates", {})
    matches = cache.setdefault("matches", {})
    names = cache.setdefault("names", {})
    gone = cache.setdefault("gone", {})        # match id -> the date it was seen over with no result
    upcoming = []
    changed = False
    missed = 0
    if read:
        jobs = [(t, d) for t in TOURS for d in scan_dates(today, set(cache["dates"].get(t, [])))]

        def one(job):
            if time.time() - _START > BUDGET_SEC:
                return job, None
            try:
                return job, parse_scoreboard(http_json(ESPN_SB.format(tour=job[0], date=job[1])), job[0])
            except Exception as e:  # noqa: BLE001
                print(f"    tennis: {job[0]} {job[1]} skipped ({type(e).__name__})")
                return job, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            for (tour, date), got in ex.map(one, jobs):
                if got is None:
                    missed += 1
                    continue
                rows, nm, up, gn = got
                for mid in gn:
                    if mid not in gone and mid not in matches:
                        gone[mid], changed = date, True
                for r in rows:
                    if matches.get(r[11]) != r:
                        matches[r[11]], changed = r, True
                for k, v in nm.items():
                    if v and names.get(k) != v:
                        names[k], changed = v, True
                if date == today.strftime("%Y%m%d") or date >= (today - datetime.timedelta(days=STEP_DAYS)).strftime("%Y%m%d"):
                    upcoming += up
                seen = cache["dates"].setdefault(tour, [])
                if date not in seen:
                    seen.append(date)
                    changed = True
        if changed:
            with open(RESULTS, "w", encoding="utf-8") as f:
                json.dump(cache, f, separators=(",", ":"), sort_keys=True)
    up = {u["mid"]: u for u in upcoming if u["mid"] not in matches}
    rows = sorted(matches.values(), key=lambda r: (r[12] or r[0], r[11]))
    # complete: 95%+ of the history's dates read for each tour (now or on earlier runs). A first run cut off
    # by its time limit isn't, and ratings from part of the history would be wrong, so main() records no new
    # picks until it is; a date or two ESPN keeps refusing doesn't hold tennis up forever.
    expected = len(scan_dates(today, set()))
    complete = all(len(cache["dates"].get(t, [])) >= 0.95 * expected for t in TOURS)
    return {"matches": rows, "names": names, "upcoming": list(up.values()), "complete": complete, "missed": missed,
            "gone": set(gone)}


# ---------------------------------------------------------------- model: ratings
# ==== MODEL (Python only: the tennis page shows the chances this file writes and never recomputes them;
# tennis.json carries these settings for reference)
ELO = {"k": 250.0, "kOff": 5.0, "kPow": 0.5, "surfW": 0.3, "start": 1500.0}
# The hold rate (share of service games won) of an even match, per tour and surface. Not the tour's
# average hold: fitted with TAU, the two trade off, and these with TAU put the totals where they land.
HOLD = {"atp": {"hard": 0.86, "clay": 0.78, "grass": 0.82},
        "wta": {"hard": 0.58, "clay": 0.66, "grass": 0.66}}
# How much the gap between the two players varies from match to match (see NODES): fit with HOLD on
# the 2026 results by the likelihood of each final total and margin (fit Nov 2, 2026).
TAU = {"atp": {"hard": 0.08, "clay": 0.08, "grass": 0.04},
       "wta": {"hard": 0.08, "clay": 0.12, "grass": 0.08}}
CAL = {"atp": 1.0, "wta": 1.0}   # p' = sigmoid(CAL * logit(p)); 1 = unchanged
# Total games: the scoreline chain leans to overs in the WTA (44% over the middle line, 40% hit) and a
# touch to unders in the ATP; over chances are shifted by this much on the logit scale. The same shift
# fit best in both halves of 2026 (WTA -0.12 each; ATP +0.06 and +0.14).
OVER_SHIFT = {"atp": 0.10, "wta": -0.12}
P_MAX = 0.97
MIN_MATCHES = 8           # a player needs this many matches in the data to be priced
# ==== /MODEL


def elo_p(d):
    return 1.0 / (1.0 + 10 ** (-d / 400.0))


def new_ratings():
    return {"o": {}, "s": {"hard": {}, "clay": {}, "grass": {}}, "n": {}, "ns": {"hard": {}, "clay": {}, "grass": {}}}


def rating_diff(R, a, b, surf, cfg=ELO):
    st = cfg["start"]
    do = R["o"].get(a, st) - R["o"].get(b, st)
    ds = R["s"][surf].get(a, st) - R["s"][surf].get(b, st)
    return (1 - cfg["surfW"]) * do + cfg["surfW"] * ds


def win_chance(R, a, b, surf, tour, cfg=ELO, cal=None):
    """Model chance that player a beats player b (before the best-of-5 stretch; see match_chance)."""
    p = elo_p(rating_diff(R, a, b, surf, cfg))
    c = (cal or CAL).get(tour, 1.0)
    if c != 1.0:
        p = 1 / (1 + math.exp(-c * math.log(p / (1 - p))))
    return min(P_MAX, max(1 - P_MAX, p))


def update(R, row, cfg=ELO):
    """One finished match into the ratings (retirements count only as matches played)."""
    surf, a, b, win, status = row[3], row[6], row[7], row[8], row[10]
    st = cfg["start"]
    for pool, n in ((R["o"], R["n"]), (R["s"][surf], R["ns"][surf])):
        ra, rb = pool.get(a, st), pool.get(b, st)
        if status == "F":
            e = elo_p(ra - rb)
            s = 1.0 if win == 1 else 0.0
            ka = cfg["k"] / (n.get(a, 0) + cfg["kOff"]) ** cfg["kPow"]
            kb = cfg["k"] / (n.get(b, 0) + cfg["kOff"]) ** cfg["kPow"]
            pool[a], pool[b] = ra + ka * (s - e), rb - kb * (s - e)
        n[a], n[b] = n.get(a, 0) + 1, n.get(b, 0) + 1


def rate(rows, cfg=ELO, until=None):
    R = new_ratings()
    for r in rows:
        if until and (r[12] or r[0]) >= until:
            break
        update(R, r, cfg)
    return R


# ---------------------------------------------------------------- model: scorelines
def hold_from_point(s):
    """Chance of holding serve when winning each service point with chance s."""
    if s <= 0:
        return 0.0
    if s >= 1:
        return 1.0
    q = 1 - s
    deuce = s * s / (s * s + q * q)
    return s ** 4 * (1 + 4 * q + 10 * q * q) + 20 * s ** 3 * q ** 3 * deuce


def point_from_hold(h):
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if hold_from_point(mid) < h:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tiebreak(sa, sb, to=7):
    """Chance that A (serving the first point) wins a tiebreak; sa, sb: each one's serve point chances.
    Serve goes A, B, B, A, A, B, B, ..."""
    memo = {}

    def go(x, y):
        if x >= to and x - y >= 2:
            return 1.0
        if y >= to and y - x >= 2:
            return 0.0
        if x >= to - 1 and y >= to - 1 and x == y:
            # from deuce-like states: two points, one each serve
            pa = sa * (1 - sb)                    # A wins both of a pair (one served each)
            pb = (1 - sa) * sb
            return pa / (pa + pb) if pa + pb > 0 else 0.5
        k = (x + y)
        a_serves = (k % 4) in (0, 3)
        w = sa if a_serves else 1 - sb
        key = (x, y)
        if key not in memo:
            memo[key] = w * go(x + 1, y) + (1 - w) * go(x, y + 1)
        return memo[key]
    return go(0, 0)


def set_dist(ha, hb, a_first, tb_a):
    """Final scores of one set: {(games A, games B): chance}. ha/hb: each one's hold chance;
    a_first: A serves the first game; tb_a: A's chance of winning a 6-6 tiebreak."""
    out = {}
    states = {(0, 0): 1.0}
    while states:
        nxt = {}
        for (x, y), pr in states.items():
            if (x == 6 and y <= 4) or (y == 6 and x <= 4) or x == 7 or y == 7:
                out[(x, y)] = out.get((x, y), 0.0) + pr
                continue
            if x == 6 and y == 6:
                out[(7, 6)] = out.get((7, 6), 0.0) + pr * tb_a
                out[(6, 7)] = out.get((6, 7), 0.0) + pr * (1 - tb_a)
                continue
            a_serves = ((x + y) % 2 == 0) == a_first
            w = ha if a_serves else 1 - hb
            nxt[(x + 1, y)] = nxt.get((x + 1, y), 0.0) + pr * w
            nxt[(x, y + 1)] = nxt.get((x, y + 1), 0.0) + pr * (1 - w)
        states = nxt
    return out


def _sets(ha, hb):
    sa, sb = point_from_hold(ha), point_from_hold(hb)
    tba, tbb = tiebreak(sa, sb), 1 - tiebreak(sb, sa)        # A's chance when A / B serves first in it
    return {True: set_dist(ha, hb, True, tba), False: set_dist(ha, hb, False, tbb)}


def match_dist(ha, hb, bo=3):
    """{(games A, games B, A won): chance} over whole matches, the first server a coin flip."""
    sets = _sets(ha, hb)
    need = bo // 2 + 1
    states = {(0, 0, 0, 0, True): 0.5, (0, 0, 0, 0, False): 0.5}   # sets A, sets B, games A, games B, A serves next
    out = {}
    while states:
        nxt = {}
        for (wa, wb, ga, gb, af), pr in states.items():
            for (x, y), q in sets[af].items():
                na, nb = wa + (x > y), wb + (y > x)
                g = (ga + x, gb + y)
                if na == need or nb == need:
                    k = (g[0], g[1], na == need)
                    out[k] = out.get(k, 0.0) + pr * q
                else:
                    k = (na, nb, g[0], g[1], af if (x + y) % 2 == 0 else not af)
                    nxt[k] = nxt.get(k, 0.0) + pr * q
        states = nxt
    return out


def match_sets(ha, hb, bo=3):
    """Set-level outcomes for A: {"set": [chance A wins set 1, set 2, ...] (a set never played counts as
    not won), "exact": {(A's sets, B's sets): chance}, "tb": chance of at least one tiebreak}."""
    sets = _sets(ha, hb)
    need = bo // 2 + 1
    win_k, exact, tb = [0.0] * bo, {}, 0.0
    states = {(0, 0, True, False): 0.5, (0, 0, False, False): 0.5}   # sets A, sets B, A serves next, a tiebreak so far
    while states:
        nxt = {}
        for (wa, wb, af, t), pr in states.items():
            k = wa + wb
            for (x, y), q in sets[af].items():
                na, nb, tt = wa + (x > y), wb + (y > x), t or (x + y == 13)
                if x > y:
                    win_k[k] += pr * q
                if na == need or nb == need:
                    exact[(na, nb)] = exact.get((na, nb), 0.0) + pr * q
                    tb += pr * q * tt
                else:
                    key = (na, nb, af if (x + y) % 2 == 0 else not af, tt)
                    nxt[key] = nxt.get(key, 0.0) + pr * q
        states = nxt
    return {"set": win_k, "exact": exact, "tb": tb}


def match_win(ha, hb, bo=3):
    sets = _sets(ha, hb)
    need = bo // 2 + 1
    states = {(0, 0, True): 0.5, (0, 0, False): 0.5}
    win = 0.0
    while states:
        nxt = {}
        for (wa, wb, af), pr in states.items():
            for (x, y), q in sets[af].items():
                na, nb = wa + (x > y), wb + (y > x)
                if na == need:
                    win += pr * q
                elif nb < need:
                    k = (na, nb, af if (x + y) % 2 == 0 else not af)
                    nxt[k] = nxt.get(k, 0.0) + pr * q
        states = nxt
    return win


# The gap between two players isn't the same every match (form, conditions, an off day): the hold
# difference is the model's d0 plus a normal TAU spread, read off at these 5 points (Gauss-Hermite).
NODES = ((0.0, 0.533333), (1.355626, 0.222076), (-1.355626, 0.222076), (2.856970, 0.011257), (-2.856970, 0.011257))
NODES = tuple((z, w / sum(x for _, x in NODES)) for z, w in NODES)      # the rounded weights, summing to exactly 1
_TABLES = {}


def _clamp(h):
    return min(0.985, max(0.015, h))


def _mix_win(base, d0, tau, bo):
    return sum(w * match_win(_clamp(base + d0 + tau * z), _clamp(base - d0 - tau * z), bo) for z, w in NODES)


def gap_for(p3, tour, surf):
    """d0, the hold gap that makes A win a best-of-3 with chance p3 (from a table, interpolated)."""
    key = (tour, surf, HOLD[tour][surf], TAU[tour][surf])
    if key not in _TABLES:
        base, tau = HOLD[tour][surf], TAU[tour][surf]
        top = min(base, 1 - base) - 0.02
        _TABLES[key] = [(d, _mix_win(base, d, tau, 3)) for d in [top * i / 40 for i in range(41)]]
    tab = _TABLES[key]
    sign, p = (1, p3) if p3 >= 0.5 else (-1, 1 - p3)
    for (d1, w1), (d2, w2) in zip(tab, tab[1:]):
        if w2 >= p:
            return sign * (d1 + (d2 - d1) * (p - w1) / max(1e-9, w2 - w1))
    return sign * tab[-1][0]


def price_match(p3, tour, surf, bo):
    """Everything the page prices for one match from the model's best-of-3 chance that A wins:
    {"win": A's chance, "games": {total: chance}, "spread": {A minus B games: chance}, "set": [A wins set k],
     "exact": {(A's sets, B's sets): chance}, "tb": chance of a tiebreak}.
    Best of 5 uses the same holds, so the better player's edge grows."""
    base, tau = HOLD[tour][surf], TAU[tour][surf]
    d0 = gap_for(p3, tour, surf)
    win, games, spread = 0.0, {}, {}
    setw, exact, tb = [0.0] * bo, {}, 0.0
    for z, w in NODES:
        ha, hb = _clamp(base + d0 + tau * z), _clamp(base - d0 - tau * z)
        for (ga, gb, aw), q in match_dist(ha, hb, bo).items():
            q *= w
            win += q if aw else 0.0
            games[ga + gb] = games.get(ga + gb, 0.0) + q
            spread[ga - gb] = spread.get(ga - gb, 0.0) + q
        ms = match_sets(ha, hb, bo)
        setw = [a + w * b for a, b in zip(setw, ms["set"])]
        for k, q in ms["exact"].items():
            exact[k] = exact.get(k, 0.0) + w * q
        tb += w * ms["tb"]
    return {"win": win, "games": games, "spread": spread, "set": setw, "exact": exact, "tb": tb}


def over_chance(games, line, tour=None):
    """Chance the match goes over `line` total games (with the tour's OVER_SHIFT when tour is given)."""
    p = min(0.999, max(0.001, sum(q for g, q in games.items() if g > line)))
    if tour:
        p = 1 / (1 + math.exp(-(math.log(p / (1 - p)) + OVER_SHIFT.get(tour, 0.0))))
    return p


def cover_chance(spread, line):
    """A covers +line (line may be negative): A's games minus B's games + line > 0."""
    return sum(q for d, q in spread.items() if d + line > 0)


# ---------------------------------------------------------------- backtest
def backtest(rows, start="2026-01-01", cfg=ELO, games=False, cal=None):
    """Walk every match in order; from `start` on, record the model's chance before updating.
    Returns rows of (tour, surf, p, won, [total games, model over-chance at the median line])."""
    R = new_ratings()
    out = []
    for r in rows:
        when = r[12] or r[0]
        a, b = r[6], r[7]
        if when >= start and r[10] == "F" and min(R["n"].get(a, 0), R["n"].get(b, 0)) >= MIN_MATCHES:
            p3 = win_chance(R, a, b, r[3], r[1], cfg, cal)
            rec = [r[1], r[3], p3, 1 if r[8] == 1 else 0, r[4]]
            if games:
                pm = price_match(p3, r[1], r[3], r[4])
                tot = sum(x + y for x, y in r[9])
                exp = sum(g * q for g, q in pm["games"].items())
                line = math.floor(exp) + 0.5
                rec += [tot, line, over_chance(pm["games"], line, r[1]), pm["win"], exp,
                        sum(x - y for x, y in r[9]), cover_chance(pm["spread"], -1.5)]
            out.append(rec)
        update(R, r, cfg)
    return out


def logloss(rows, i_p=2, i_y=3):
    eps = 1e-9
    return sum(-(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)))
               for p, y in ((r[i_p], r[i_y]) for r in rows)) / max(1, len(rows))


def calib_table(pairs, bins=10):
    b = {}
    for p, y in pairs:
        k = min(bins - 1, int(p * bins))
        s = b.setdefault(k, [0, 0.0, 0])
        s[0] += 1; s[1] += p; s[2] += y
    return [(f"{k * 10}-{k * 10 + 10}%", n, round(sp / n * 100, 1), round(sy / n * 100, 1)) for k, (n, sp, sy) in sorted(b.items())]


def run_backtest(rows):
    print("Elo settings (log loss on 2026 matches, both players with", MIN_MATCHES, "+ matches):")
    best = None
    for k in (150, 250, 350):
        for kp in (0.3, 0.4, 0.5):
            for sw in (0.0, 0.3, 0.5, 0.7):
                cfg = dict(ELO, k=k, kPow=kp, surfW=sw)
                bt = backtest(rows, cfg=cfg, cal={"atp": 1.0, "wta": 1.0})
                ll = logloss(bt)
                if best is None or ll < best[0]:
                    best = (ll, cfg, len(bt))
    print("  best", {k: best[1][k] for k in ("k", "kPow", "surfW")}, f"log loss {best[0]:.4f} over {best[2]}")
    bt = backtest(rows, cal={"atp": 1.0, "wta": 1.0}, cfg=best[1])
    for tour in TOURS:
        sub = [r for r in bt if r[0] == tour]
        fits = []
        for c in [x / 100 for x in range(70, 131, 2)]:
            ll = sum(-(y * math.log(q) + (1 - y) * math.log(1 - q))
                     for p, y in ((r[2], r[3]) for r in sub)
                     for q in [min(P_MAX, max(1 - P_MAX, 1 / (1 + math.exp(-c * math.log(p / (1 - p))))))]) / len(sub)
            fits.append((ll, c))
        print(f"  {tour}: {len(sub)} matches, log loss {logloss(sub):.4f}, best CAL {min(fits)[1]} -> {min(fits)[0]:.4f}")
        for row in calib_table([(r[2], r[3]) for r in sub]):
            print("     ", row)
    print("Total games (current HOLD and ELO):")
    bt = backtest(rows, games=True)
    for tour in TOURS:
        for surf in ("hard", "clay", "grass"):
            sub = [r for r in bt if r[0] == tour and r[1] == surf]
            if not sub:
                continue
            avg_t = sum(r[5] for r in sub) / len(sub)
            avg_e = sum(r[9] for r in sub) / len(sub)
            over = sum(r[5] > r[6] for r in sub) / len(sub)
            pov = sum(r[7] for r in sub) / len(sub)
            cov = sum(r[10] - 1.5 > 0 for r in sub) / len(sub)
            pcov = sum(r[11] for r in sub) / len(sub)
            ll = logloss([[0, 0, r[7], int(r[5] > r[6])] for r in sub])
            print(f"  {tour} {surf}: {len(sub)} matches, games {avg_t:.2f} (model {avg_e:.2f}), "
                  f"over the median line {over:.3f} (model {pov:.3f}, log loss {ll:.4f}), "
                  f"A by 2+ {cov:.3f} (model {pcov:.3f})")


# ---------------------------------------------------------------- markets
PM_EVENTS = ("https://gateway.polymarket.us/v1/events?tagSlug={tour}&active=true&closed=false"
             "&startDateMin={a}T00:00:00Z&startDateMax={b}T00:00:00Z&limit=200")
PM_BOOK = "https://gateway.polymarket.us/v1/markets/{slug}/book"
# Kalshi series -> our market key. Match winner ("ml"), total games ("games"), game spread ("spread").
# Set winner ("set", the set number from the event ticker) and exact score in sets ("exact") too. Kalshi
# also has series for aces, tiebreaks, total sets, set spreads and straight-set wins; none had a market
# open when this was written (Nov 2, 2026), so their wording is unknown and they aren't read.
KX_SERIES = {"atp": {"KXATPMATCH": "ml", "KXATPGTOTAL": "games", "KXATPGSPREAD": "spread",
                     "KXATPSETWINNER": "set", "KXATPEXACTMATCH": "exact"},
             "wta": {"KXWTAMATCH": "ml", "KXWTAGTOTAL": "games", "KXWTAGSPREAD": "spread",
                     "KXWTASETWINNER": "set", "KXWTAEXACTMATCH": "exact"}}
KX_EVENT = re.compile(r"^KX[A-Z]+-(\d{2}[A-Z]{3}\d{2})([A-Z]+)(?:-(\d))?$")
KX_EXACT = re.compile(r"^(.+?)\s+wins\s+(\d)-(\d)$", re.I)
KX_TOTAL = re.compile(r"^over\s+([\d.]+)\s+games?$", re.I)
KX_SPREAD = re.compile(r"^(.+?)\s+-([\d.]+)\s+games?$", re.I)
KX_WIDE = 0.15            # a Kalshi market whose bid-ask is wider than this isn't counted as a price


def pkey(name):
    """A name as a comparable key: accents off, lower case, letters only ("Botic van de Zandschulp" ->
    "boticvandezandschulp")."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def short_key(name):
    """First initial + last name, for names an exchange spells differently ("Alex" / "Alexander")."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    parts = re.findall(r"[a-z]+", s)
    return (parts[0][:1] + parts[-1]) if len(parts) >= 2 else "".join(parts)


def _f(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def fetch_polymarket(today):
    """Polymarket US tennis match-winner markets for matches in [-1, +3] days:
    [{"tour", "slug", "long": name, "short": name, "start"}] (Yes = the long side's player wins)."""
    import depth
    a = (today - datetime.timedelta(days=1)).isoformat()
    b = (today + datetime.timedelta(days=4)).isoformat()
    out = []
    for tour in TOURS:
        try:
            events = (http_json(PM_EVENTS.format(tour=tour, a=a, b=b), timeout=60) or {}).get("events") or []
        except Exception as e:  # noqa: BLE001
            print(f"  polymarket US {tour}: skipped ({e})")
            continue
        for ev in events:
            for m in ev.get("markets") or []:
                if m.get("sportsMarketType") != "tennis_match_winner" or m.get("closed"):
                    continue
                sides = m.get("marketSides") or []
                lg = next((s for s in sides if s.get("long") is True), None)
                sh = next((s for s in sides if s.get("long") is False), None)
                if not lg or not sh:
                    continue
                depth.note_sides(m)
                out.append({"tour": tour, "slug": m.get("slug"),
                            "long": ((lg.get("team") or {}).get("name") or lg.get("description") or ""),
                            "short": ((sh.get("team") or {}).get("name") or sh.get("description") or ""),
                            "start": m.get("gameStartTime") or ev.get("startTime")})
    return out


def pm_books(slugs):
    import depth

    def one(slug):
        time.sleep(0.2)
        try:
            return slug, depth.pmus_book((http_json(PM_BOOK.format(slug=slug)) or {}).get("marketData") or {})
        except Exception:  # noqa: BLE001
            return slug, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, slugs))


def fetch_kalshi():
    """Open Kalshi tennis markets: {event code: {"ml": [...], "games": [...], "spread": [...]}}, the event
    code being the date + players part of the ticker shared by a match's three series. Each market:
    {"ticker", "name" (player, for ml/spread), "line" (games/spread), "yes", "no" (asks), "yd", "nd"
    (dollars at them), "ok" (tight enough to count)}."""
    import kalshi
    out, failed, n = {}, 0, 0
    for tour, series in KX_SERIES.items():
        for s, key in series.items():
            cursor = ""
            try:
                for _ in range(5):
                    time.sleep(kalshi.PACE)
                    d = kalshi._get(f"/markets?series_ticker={s}&status=open&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
                    ms = d.get("markets") or []
                    for m in ms:
                        em = KX_EVENT.match(m.get("event_ticker") or "")
                        if not em:
                            continue
                        sub = (m.get("yes_sub_title") or "").strip()
                        k = {"ticker": m.get("ticker"), "tour": tour, "date": em.group(1)}
                        if key == "ml":
                            k["name"] = sub
                        elif key == "set":
                            if not em.group(3):
                                continue
                            k["name"], k["line"] = sub, float(em.group(3))
                        elif key == "exact":
                            t = KX_EXACT.match(sub)
                            if not t:
                                continue
                            k["name"], k["line"] = t.group(1).strip(), float(t.group(2)) + float(t.group(3)) / 10   # 2-1 -> 2.1
                        elif key == "games":
                            t = KX_TOTAL.match(sub)
                            if not t:
                                continue
                            k["line"] = float(t.group(1))
                        else:
                            t = KX_SPREAD.match(sub)
                            if not t:
                                continue
                            k["name"], k["line"] = t.group(1).strip(), -float(t.group(2))
                        ya, yb, na = _f(m.get("yes_ask_dollars")), _f(m.get("yes_bid_dollars")), _f(m.get("no_ask_dollars"))
                        ys, bs = _f(m.get("yes_ask_size_fp")), _f(m.get("yes_bid_size_fp"))
                        k["yes"] = ya if ya is not None and 0.02 < ya < 0.98 else None
                        k["no"] = na if na is not None and 0.02 < na < 0.98 else None
                        k["yd"] = round(ya * ys, 2) if k["yes"] is not None and ys is not None else None
                        k["nd"] = round(na * bs, 2) if k["no"] is not None and bs is not None else None
                        k["ok"] = ya is not None and yb is not None and ya - yb <= KX_WIDE
                        out.setdefault(em.group(1) + em.group(2), {}).setdefault(key, []).append(k)
                        n += 1
                    cursor = d.get("cursor") or ""
                    if not cursor or not ms:
                        break
            except Exception as e:  # noqa: BLE001
                print(f"    kalshi {s}: skipped ({e})")
                failed += 1
    if failed == sum(len(v) for v in KX_SERIES.values()):
        print("  kalshi: skipped (every tennis series failed)")
        return None
    print(f"  kalshi: {n} tennis markets in {len(out)} matches")
    return out


def same_player(a, b):
    return bool(a and b) and (pkey(a) == pkey(b) or short_key(a) == short_key(b))


def kalshi_for(km, name_a, name_b):
    """The Kalshi event (its three series) for a match between these two players, or None."""
    for code, ev in (km or {}).items():
        names = [k["name"] for k in ev.get("ml") or []]
        if len(names) == 2 and ((same_player(names[0], name_a) and same_player(names[1], name_b)) or
                                (same_player(names[0], name_b) and same_player(names[1], name_a))):
            return ev
    return None


# ---------------------------------------------------------------- picks
PICK_COLS = ["src", "gid", "mid", "date", "tour", "event", "round", "surface", "bo", "pid", "player", "oid", "opp",
             "stat", "line", "side", "prob", "price", "lists", "actual", "score", "res", "start", "px0", "pxc",
             "mv", "lk", "pp", "kp", "pd", "kd", "vn", "th", "pj", "elo", "oelo"]
PICKS_FILE = "tennis_picks.json"
DATA_FILE = "tennis.json"
TEMPLATE = "tennis_template.html"
PAGE = "tennis.html"
MODEL_V = 1
LOCK_MIN = 30
VOID_AFTER_DAYS = 3       # a match still not finished 3 days after its date (a walkover, a washout) is void...
VOID_AFTER_HOURS = 36     # ...or 36 hours after its start, so it's settled before health.py calls it stuck (48 hours)
# Value spots: the market gives the side 30-80%, and the model is VALUE_MIN_EDGE to VALUE_MAX_EDGE above
# the price (a bigger gap against a liquid market is almost always news the ratings can't see: an
# injury, a withdrawal). Tested against the cheaper exchange with $25+ offered (depth.choose).
VALUE_MIN_PRICE, VALUE_MAX_PRICE = 0.30, 0.80
VALUE_MIN_EDGE, VALUE_MAX_EDGE = 0.08, 0.20
# Only match winners make the list: the totals model barely beats a coin flip on the backtest (log loss
# 0.67-0.69 at the middle line), so total games, spreads, set winners and exact scores are recorded and
# graded (the edge tracker shows how they'd have done) but never listed as Value.
VALUE_STATS = {"ml"}
# Top 25 Surest, the NHL and MLB rule: up to TOP_N sides the model gives T_MIN_PROB+ with a live price
# ($25+ offered), ranked by the model's chance, one per match market. Any market can make it.
TOP_N = 25
T_MIN_PROB = 0.90
STAT_TEXT = {"ml": "to win", "games": "total games", "spread": "game spread", "set": "set winner", "exact": "exact score"}


def parse_utc(s):
    try:
        t = datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def pick_locked(p, now=None):
    t = parse_utc(p.get("start"))
    return bool(p.get("lk")) or (t is not None and t <= (now or now_utc()))


def load_picks():
    try:
        with open(PICKS_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    cols = d.get("cols") or []
    return [dict(zip(cols, row)) for row in d.get("picks", [])]


def save_picks(picks):
    doc = {"gen": datetime.date.today().isoformat(), "model": {"elo": ELO, "hold": HOLD, "tau": TAU, "cal": CAL},
           "cols": PICK_COLS, "picks": [[p.get(c) for c in PICK_COLS] for p in picks]}
    with open(PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)


def sides_for(m, pm, ev, book):
    """Every priced side of one match: [{stat, line, side, pid, prob, pp, pd, kp, kd, _ps, _kt}].
    m: the upcoming ESPN match (with names), pm: price_match() from player A's view, ev: its Kalshi
    event, book: its Polymarket US market and book. Match winner and spread sides are "over" (the
    player named wins / covers); total games are over or under."""
    a, b = m["p1"], m["p2"]
    out = []
    # match winner
    for pid, other, prob in ((a, b, pm["win"]), (b, a, 1 - pm["win"])):
        s = {"stat": "ml", "line": 0.0, "side": "over", "pid": pid, "oid": other, "prob": prob}
        if book and book.get("bk"):
            bk, is_long = book["bk"], same_player(book["long"], m["names"][pid])
            import depth
            ok = depth.side_ok(book["slug"], "over" if is_long else "under")
            px = bk.get("ask") if is_long else (None if bk.get("bid") is None else 1 - bk["bid"])
            if ok and px is not None and 0.02 < px < 0.98:
                s.update(pp=round(px, 3), pd=bk.get("over" if is_long else "under"), _ps=book["slug"])
        for k in (ev or {}).get("ml") or []:
            if same_player(k["name"], m["names"][pid]) and k["ok"] and k["yes"] is not None:
                s.update(kp=round(k["yes"], 3), kd=k["yd"], _kt=k["ticker"])
        out.append(s)
    # total games: both sides of each line
    for k in (ev or {}).get("games") or []:
        if not k["ok"]:
            continue
        po = over_chance(pm["games"], k["line"], m["tour"])
        for side, prob, px, usd in (("over", po, k["yes"], k["yd"]), ("under", 1 - po, k["no"], k["nd"])):
            if px is not None:
                out.append({"stat": "games", "line": k["line"], "side": side, "pid": a, "oid": b, "prob": prob,
                            "kp": round(px, 3), "kd": usd, "_kt": k["ticker"]})
    # game spread: "X -L" Yes = X covers -L; No = the other player covers +L
    for k in (ev or {}).get("spread") or []:
        if not k["ok"]:
            continue
        x = a if same_player(k["name"], m["names"][a]) else b if same_player(k["name"], m["names"][b]) else None
        if x is None:
            continue
        y = b if x == a else a
        cov_x = cover_chance(pm["spread"] if x == a else {-d: q for d, q in pm["spread"].items()}, k["line"])
        for pid, other, line, prob, px, usd in ((x, y, k["line"], cov_x, k["yes"], k["yd"]),
                                                (y, x, -k["line"], 1 - cov_x, k["no"], k["nd"])):
            if px is not None:
                out.append({"stat": "spread", "line": line, "side": "over", "pid": pid, "oid": other, "prob": prob,
                            "kp": round(px, 3), "kd": usd, "_kt": k["ticker"]})
    # set winner: "X wins set k" Yes (each player has their own market)
    for k in (ev or {}).get("set") or []:
        x = a if same_player(k["name"], m["names"][a]) else b if same_player(k["name"], m["names"][b]) else None
        n = int(k["line"])
        if x is None or not k["ok"] or k["yes"] is None or not 1 <= n <= m["bo"]:
            continue
        prob = pm["set"][n - 1] if x == a else set_lost(pm, n, m["bo"])
        out.append({"stat": "set", "line": float(n), "side": "over", "pid": x, "oid": b if x == a else a, "prob": prob,
                    "kp": round(k["yes"], 3), "kd": k["yd"], "_kt": k["ticker"]})
    # exact score in sets: "X wins 2-1" Yes
    for k in (ev or {}).get("exact") or []:
        x = a if same_player(k["name"], m["names"][a]) else b if same_player(k["name"], m["names"][b]) else None
        if x is None or not k["ok"] or k["yes"] is None:
            continue
        w, l = int(k["line"]), round(k["line"] % 1 * 10)
        prob = pm["exact"].get((w, l) if x == a else (l, w), 0.0)
        out.append({"stat": "exact", "line": k["line"], "side": "over", "pid": x, "oid": b if x == a else a, "prob": prob,
                    "kp": round(k["yes"], 3), "kd": k["yd"], "_kt": k["ticker"]})
    for s in out:
        s["prob"] = round(min(P_MAX, max(1 - P_MAX, s["prob"])), 4)
    return out


def set_lost(pm, n, bo):
    """B's chance of winning set n: the set is played and A doesn't win it."""
    need = bo // 2 + 1
    if n <= need:
        played = 1.0
    else:   # set n is played unless someone has `need` sets after n - 1 of them
        played = 1.0 - sum(q for (sa, sb), q in pm["exact"].items() if sa + sb < n)
    return max(0.0, played - pm["set"][n - 1])


def pick_key(p):
    return (str(p.get("mid")), p.get("stat"), float(p.get("line") or 0), p.get("side"), str(p.get("pid")))


def value_ok(p):
    pr = p.get("price")
    return (pr is not None and not p.get("th") and p.get("stat") in VALUE_STATS and VALUE_MIN_PRICE <= pr <= VALUE_MAX_PRICE
            and VALUE_MIN_EDGE <= p["prob"] - pr <= VALUE_MAX_EDGE)


def top_ok(p):
    return p.get("price") is not None and not p.get("th") and p["prob"] >= T_MIN_PROB


def market_key(p):
    """One side per match market: a match's winner, each total-games line, each spread line (both
    players' sides of one spread line are the same market), each set; each exact score is its own."""
    if p["stat"] == "exact":
        return (str(p["mid"]), "exact", str(p["pid"]), float(p["line"]))
    return (str(p["mid"]), p["stat"], abs(float(p["line"])) if p["stat"] == "spread" else float(p["line"]))


def assign_lists(picks, now=None):
    """Value ("V") and Top 25 Surest ("T") on pending, unlocked picks. One side per match market per
    list (Value: the bigger edge; Top 25: the higher chance). A locked pick keeps its lists, and its
    Top 25 place counts toward the 25."""
    open_ = [p for p in picks if p.get("res") is None and not pick_locked(p, now)]
    held = sum(1 for p in picks if p.get("res") is None and pick_locked(p, now) and "T" in (p.get("lists") or ""))
    for p in open_:
        p["lists"] = ""
    best_v, best_t = {}, {}
    for p in open_:
        k = market_key(p)
        if value_ok(p) and (k not in best_v or p["prob"] - p["price"] > best_v[k]["prob"] - best_v[k]["price"]):
            best_v[k] = p
        if top_ok(p) and (k not in best_t or p["prob"] > best_t[k]["prob"]):
            best_t[k] = p
    for p in best_v.values():
        p["lists"] = "V"
    for p in sorted(best_t.values(), key=lambda p: -p["prob"])[:max(0, TOP_N - held)]:
        p["lists"] = "T" + p["lists"]


def grade(p, by_mid, today, gone=(), now=None):
    """hit / miss from the final score; a retirement settles the match winner (whoever advanced, as
    Polymarket and Kalshi settle it) and voids every other market ("dnp"). A match ESPN shows over with no
    result (a walkover) is void at once; one with no result VOID_AFTER_HOURS after its start (or, with no
    start, VOID_AFTER_DAYS after its date) is void. Returns True when it changed."""
    r = by_mid.get(str(p.get("mid")))
    if r is None:
        t = parse_utc(p.get("start"))
        late = (now - t > datetime.timedelta(hours=VOID_AFTER_HOURS)) if (t and now) else \
            (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(p["date"])).days > VOID_AFTER_DAYS
        if str(p.get("mid")) in gone or late:
            p["res"], p["actual"] = "dnp", None
            return True
        return False
    sets, a_won = r[9], r[8] == 1
    p_is_a = str(p["pid"]) == str(r[6])
    mine = [(x, y) if p_is_a else (y, x) for x, y in sets]
    p["score"] = " ".join(f"{x}-{y}" for x, y in mine)
    if p["stat"] == "ml":
        won = a_won == p_is_a
        p["actual"], p["res"] = int(won), "hit" if won else "miss"
        return True
    if r[10] != "F":
        p["res"], p["actual"] = "dnp", None
        return True
    if p["stat"] == "set":
        n = int(p["line"])
        p["actual"] = int(len(mine) >= n and mine[n - 1][0] > mine[n - 1][1])
        p["res"] = "hit" if p["actual"] else "miss"
    elif p["stat"] == "exact":
        sw, sl = sum(x > y for x, y in mine), sum(y > x for x, y in mine)
        p["actual"] = sw + sl / 10
        p["res"] = "hit" if (sw, sl) == (int(p["line"]), round(float(p["line"]) % 1 * 10)) else "miss"
    elif p["stat"] == "games":
        tot = sum(x + y for x, y in sets)
        p["actual"] = tot
        over = tot > float(p["line"])
        p["res"] = "hit" if over == (p["side"] == "over") else "miss"
    else:
        margin = sum(x - y for x, y in mine)
        p["actual"] = margin
        p["res"] = "hit" if margin + float(p["line"]) > 0 else "miss"
    return True


def record(picks):
    import depth
    out = {}
    for p in picks:
        if p.get("res") not in ("hit", "miss"):
            continue
        for tag in ("A" + (p.get("lists") or "")):     # "A": every graded pick (the edge tracker's all-tennis)
            r = out.setdefault(tag, {"n": 0, "hit": 0, "priced": 0, "units": 0.0})
            r["n"] += 1
            r["hit"] += p["res"] == "hit"
            if p.get("price") and depth.real_price(p):
                r["priced"] += 1
                r["units"] += (1.0 / p["price"] - 1) if p["res"] == "hit" else -1
    for r in out.values():
        r["units"] = round(r["units"], 2)
    return out


def update_picks(picks, upcoming, R, km, pm_list, books, by_mid, now, gone=()):
    """Grade, then refresh or record every priced side of every upcoming match that isn't locked."""
    import depth
    today = (now - datetime.timedelta(hours=5)).date().isoformat()
    graded = sum(grade(p, by_mid, today, gone, now) for p in picks if p.get("res") is None)
    have = {pick_key(p): p for p in picks}
    added = 0
    for m in upcoming:
        if m.get("hold"):
            continue
        if m.get("locked"):
            # locked by an earlier start than the one its picks carry (Polymarket's, or a placeholder's day):
            # its pending picks lock now, as published, so their lists stop changing
            for p in picks:
                if str(p.get("mid")) == m["mid"] and p.get("res") is None and not p.get("lk"):
                    p["lk"] = now.strftime("%Y-%m-%dT%H:%MZ")
            continue
        ev = m.get("_kx")
        book = m.get("_pm")
        if not ev and not book:
            continue
        for s in sides_for(m, m["_price"], ev, book):
            key = (m["mid"], s["stat"], float(s["line"]), s["side"], str(s["pid"]))
            p = have.get(key)
            if p is None:
                p = {"src": "live", "gid": f"{m['tour']}-{m['mid']}", "mid": m["mid"], "date": today, "tour": m["tour"],
                     "event": m["event"], "round": m["round"], "surface": m["surface"], "bo": m["bo"],
                     "pid": s["pid"], "player": m["names"][s["pid"]], "oid": s["oid"], "opp": m["names"][s["oid"]],
                     "stat": s["stat"], "line": s["line"], "side": s["side"], "res": None, "mv": MODEL_V, "lists": ""}
                picks.append(p)
                have[key] = p
                added += 1
            elif p.get("res") is not None or pick_locked(p, now):
                continue
            prev = (p.get("price"), p.get("vn"), p.get("th"))
            p.update(prob=s["prob"], start=m["start"], elo=round(m["elo"][s["pid"]]), oelo=round(m["elo"][s["oid"]]),
                     pp=s.get("pp"), pd=s.get("pd"), kp=s.get("kp"), kd=s.get("kd"))
            p["price"], p["vn"], p["th"] = prev
            depth.choose(p)
            if p.get("price") is not None:
                if p.get("px0") is None:
                    p["px0"] = p["price"]
                p["pxc"] = p["price"]
    # a pending side no exchange lists any more loses its prices (it can't be bought at the last one seen)
    seen = {(m["mid"], s["stat"], float(s["line"]), s["side"], str(s["pid"]))
            for m in upcoming if not m.get("locked") and not m.get("hold") and (m.get("_kx") or m.get("_pm"))
            for s in sides_for(m, m["_price"], m.get("_kx"), m.get("_pm"))}
    read = {m["mid"] for m in upcoming if not m.get("locked") and not m.get("hold")}
    for p in picks:
        if p.get("res") is None and str(p["mid"]) in read and not pick_locked(p, now) and pick_key(p) not in seen:
            p.update(pp=None, pd=None, kp=None, kd=None)
            depth.choose(p)
    assign_lists(picks, now)
    locked = 0
    for p in picks:
        t = parse_utc(p.get("start"))
        if p.get("res") is None and not p.get("lk") and t and now < t <= now + datetime.timedelta(minutes=LOCK_MIN):
            p["lk"] = now.strftime("%Y-%m-%dT%H:%MZ")
            locked += 1
    return graded, added, locked


# ---------------------------------------------------------------- the page's data
def player_rows(rows, names, R, recent=15):
    """[{id, n (name), t (tour), elo, surf {hard, clay, grass}, m (matches), w (wins), g [last matches]}]
    for every player with a match in the last year; g rows: [date, opp id, opp name, won, score, event, surface, round]."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    log, tour = {}, {}
    for r in rows:
        for me, op, won in ((r[6], r[7], r[8] == 1), (r[7], r[6], r[8] == 2)):
            tour[me] = r[1]
            sets = [(x, y) if me == r[6] else (y, x) for x, y in r[9]]
            score = " ".join(f"{x}-{y}" for x, y in sets) + (" ret." if r[10] == "R" else "")
            log.setdefault(me, []).append([r[0], op, names.get(op, ""), int(won), score, r[2], r[3], r[5]])
    st = ELO["start"]
    out = []
    for pid, g in log.items():
        if g[-1][0] < cutoff or R["n"].get(pid, 0) < MIN_MATCHES:
            continue
        yr = [x for x in g if x[0] >= cutoff]
        out.append({"id": pid, "n": names.get(pid, ""), "t": tour[pid], "elo": round(R["o"].get(pid, st)),
                    "surf": {s: round(R["s"][s].get(pid, st)) for s in ("hard", "clay", "grass")},
                    "m": len(yr), "w": sum(x[3] for x in yr), "g": g[-recent:]})
    return out


def rank_of(players):
    """{id: rank} by blended rating within each tour (the model's own ranking, not the ATP/WTA one)."""
    out = {}
    for t in TOURS:
        for i, p in enumerate(sorted((p for p in players if p["t"] == t), key=lambda p: -p["elo"]), 1):
            out[p["id"]] = i
    return out


def match_card(m, pm):
    """One upcoming match for the page: chances and the exchange prices for each market."""
    a, b = m["p1"], m["p2"]
    games = pm["games"]
    exp = sum(g * q for g, q in games.items())
    marg = sum(d * q for d, q in pm["spread"].items())
    card = {"mid": m["mid"], "tour": m["tour"], "event": m["event"], "round": m["round"], "surface": m["surface"],
            "bo": m["bo"], "start": m["start"], "a": a, "b": b, "an": m["names"][a], "bn": m["names"][b],
            "ae": round(m["elo"][a]), "be": round(m["elo"][b]), "win": round(pm["win"], 4),
            "exp": round(exp, 1), "marg": round(marg, 1), "locked": bool(m.get("locked")),
            "gd": {str(g): round(q, 4) for g, q in sorted(games.items()) if q >= 0.002},
            "sd": {str(d): round(q, 4) for d, q in sorted(pm["spread"].items()) if q >= 0.002}}
    return card


def main():
    import depth
    now = now_utc()
    today = (now - datetime.timedelta(hours=5)).date()
    res = load_results(today)
    rows, names = res["matches"], res["names"]
    print(f"  tennis results: {len(rows)} matches, {len(names)} players, {len(res['upcoming'])} upcoming")
    R = rate(rows)
    by_mid = {r[11]: r for r in rows}
    horizon = now + datetime.timedelta(days=2)
    upcoming = []
    for u in res["upcoming"]:
        t = parse_utc(u["start"])
        if not t or t > horizon or t < now - datetime.timedelta(hours=12):
            continue
        if min(R["n"].get(u["p1"], 0), R["n"].get(u["p2"], 0)) < MIN_MATCHES:
            continue
        u["names"] = {u["p1"]: names.get(u["p1"], ""), u["p2"]: names.get(u["p2"], "")}
        u["elo"] = {p: (1 - ELO["surfW"]) * R["o"].get(p, ELO["start"]) + ELO["surfW"] * R["s"][u["surface"]].get(p, ELO["start"])
                    for p in (u["p1"], u["p2"])}
        u["_price"] = price_match(win_chance(R, u["p1"], u["p2"], u["surface"], u["tour"]), u["tour"], u["surface"], u["bo"])
        upcoming.append(u)
    km = fetch_kalshi()
    pms = fetch_polymarket(today)
    want = []
    for u in upcoming:
        u["_kx"] = kalshi_for(km, *u["names"].values())
        for pmk in pms:
            if pmk["tour"] == u["tour"] and {pkey(pmk["long"]), pkey(pmk["short"])} == {pkey(n) for n in u["names"].values()} or \
               pmk["tour"] == u["tour"] and {short_key(pmk["long"]), short_key(pmk["short"])} == {short_key(n) for n in u["names"].values()}:
                u["_pm"] = dict(pmk)
                break
        # The start: ESPN's, or Polymarket's when it's earlier or ESPN only has a placeholder (an unscheduled
        # match gets 05:00 UTC, hours after an Asian session's real start). A placeholder with no Polymarket
        # time counts as started once its UTC day has begun, so nothing is recorded or relisted mid-match.
        pt = parse_utc((u.get("_pm") or {}).get("start"))
        if pt and (not u.get("tv", True) or pt < parse_utc(u["start"])):
            u["start"] = pt.strftime("%Y-%m-%dT%H:%MZ")
        st = parse_utc(u["start"])
        u["locked"] = st <= now + datetime.timedelta(minutes=LOCK_MIN) or \
            (not u.get("tv", True) and not pt and now >= st.replace(hour=0, minute=0))
        if u.get("_pm") and not u["locked"]:
            want.append(u["_pm"]["slug"])
    books = pm_books(want) if want else {}
    for u in upcoming:
        if u.get("_pm"):
            u["_pm"]["bk"] = books.get(u["_pm"]["slug"])
    priced = sum(1 for u in upcoming if u.get("_kx") or u.get("_pm"))
    print(f"  markets: {priced} of {len(upcoming)} upcoming matches priced "
          f"({sum(1 for u in upcoming if u.get('_pm'))} on Polymarket US, {sum(1 for u in upcoming if u.get('_kx'))} on Kalshi)")
    picks = load_picks()
    if not res["complete"]:
        print("  tennis history: incomplete this run (time limit or ESPN errors) — grading only, no new picks")
        for u in upcoming:
            u["hold"] = True            # update_picks then neither records, refreshes nor locks any side
    graded, added, locked = update_picks(picks, upcoming, R, km, pms, books, by_mid, now, res["gone"])
    save_picks(picks)
    print(f"  {PICKS_FILE}: {len(picks)} pick(s), graded {graded}, added {added}, locked {locked}, "
          f"{sum(1 for p in picks if p.get('res') is None and 'V' in (p.get('lists') or ''))} value spot(s) pending")
    players = player_rows(rows, names, R)
    db = {"gen": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sport": "tennis", "thru": rows[-1][0] if rows else None,
          "model": {"elo": ELO, "hold": HOLD, "tau": TAU, "cal": CAL, "pMax": P_MAX, "minMatches": MIN_MATCHES},
          "matches": sorted((match_card(u, u["_price"]) for u in upcoming), key=lambda c: c["start"] or ""),
          "record": record(picks), "rank": rank_of(players), "players": players,
          "us": {u["mid"]: u["_pm"]["slug"] for u in upcoming if u.get("_pm") and not u["locked"]}}
    payload = json.dumps(db, separators=(",", ":"), ensure_ascii=False)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"  {DATA_FILE}: {len(db['matches'])} matches, {len(players)} players, {len(payload)} bytes")
    if os.path.exists(TEMPLATE):
        with open(TEMPLATE, encoding="utf-8") as f:
            template = f.read()
        if "__TENNISDATA__" not in template:
            print(f"  WARNING: {TEMPLATE} missing __TENNISDATA__ placeholder — not writing {PAGE}")
        else:
            with open(PAGE, "w", encoding="utf-8") as f:
                f.write(template.replace("__TENNISDATA__", payload))
            print(f"  {PAGE}: written")


if __name__ == "__main__":
    if sys.argv[1:2] == ["backtest"]:
        run_backtest(load_results(datetime.date.today(), read=False)["matches"])
        sys.exit(0)
    try:
        main()
    except Exception as e:  # noqa: BLE001 — never fails the deploy (update_pass.sh)
        import traceback
        traceback.print_exc()
        print(f"Tennis build failed: {type(e).__name__}: {e}")

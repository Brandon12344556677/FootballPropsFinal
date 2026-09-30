#!/usr/bin/env python3
"""
Prop Streak Lab — MLB data builder (sibling of build_nba.py / build_nhl.py).

Pulls box scores from ESPN's public baseball API into a growing local store,
newest games first and capped per run, so the first few hourly runs backfill the
recent regular season and later runs only add each day's finals. Batters carry
hits / total bases / runs / RBIs / homers / steals / walks / strikeouts; pitchers
carry strikeouts / outs / hits, earned runs and walks allowed. Total bases come
from the play-by-play (the box line has hits and homers but not doubles or
triples) and steals from the game roster.

Python 3 standard library only. Run: python build_mlb.py

Outputs
  mlb_stats.json  the raw accumulated player box-score rows (source of truth)
  mlb.json        the compact dataset the MLB page runs on
  mlb_picks.json  every MLB pick the site has made, graded as games finish
  mlb.html        mlb_template.html with mlb.json baked in (the MLB page)

The probability model here mirrors the block marked "MODEL" in mlb_template.html.
Change both or neither. Everything that touches the network is wrapped so a bad
ESPN or Polymarket response degrades to "no new data" instead of failing the build.
"""
import json, math, os, re, sys, time, datetime, unicodedata, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

TODAY = datetime.date.today()
ET_TODAY = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)).date().isoformat()
UA = {"User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}

# site.web.api serves from CI (unlike the Akamai-blocked site.api host). Its
# scoreboard honors ?dates=YYYYMMDD, and the summary carries the box score, the
# rosters (steals) and the play-by-play (doubles/triples) in one response.
ESPN_SB = "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={gid}"

MLB_TEAMS = {"ARI", "ATH", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET", "HOU",
             "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "PHI", "PIT", "SD", "SEA",
             "SF", "STL", "TB", "TEX", "TOR", "WSH"}

STATS_FILE = "mlb_stats.json"
PICKS_FILE = "mlb_picks.json"
DATA_FILE = "mlb.json"
TEMPLATE = "mlb_template.html"
PAGE = "mlb.html"

# Previously-unseen games fetched per run (newest first). ~10 games/s from CI, so
# BUDGET_SEC is the real limit: the first run backfills the whole window.
MAX_NEW_GAMES = 1500
WINDOW_DAYS = 80        # how far back the backfill reaches: ~16 starts for a rotation arm
KEEP_DAYS = 150         # store rows older than this (vs the newest row) are pruned
# Hard wall-clock budget for the ESPN ingestion; the `done`-date cache means the
# backfill resumes cheaply next run.
BUDGET_SEC = 230
_START = time.time()

# ---------------------------------------------------------------------------
# Row layout — the MLB page reads game rows by index. Keep in sync with
# mlb_template.html.
#   0 season  1 date(YYYY-MM-DD, ESPN's UTC date)  2 opp  3 type(REG/PST)
#   4 h  5 tb  6 r  7 rbi  8 hr  9 sb  10 bb  11 so(batter strikeouts)  12 ab
#   13 k(pitcher strikeouts)  14 outs  15 ha(hits allowed)  16 er  17 pbb(walks allowed)
#   18 home(1/0)  19 bat(0 none, 1 off the bench, 2 lineup starter)
#   20 pit(0 none, 1 relief, 2 started)  21 game total (or null)  22 team spread (or null)
# ---------------------------------------------------------------------------
IDX = {"h": 4, "tb": 5, "r": 6, "rbi": 7, "hr": 8, "sb": 9, "bb": 10, "so": 11, "ab": 12,
       "k": 13, "outs": 14, "ha": 15, "er": 16, "pbb": 17}
ROW_STATS = list(IDX)
PITCH_STATS = {"k", "outs", "ha", "er", "pbb"}

# ---------------------------------------------------------------------------
# MODEL — mirrored in mlb_template.html (block marked MODEL). Keep identical.
# Same weighted-KDE-over-recent-values engine as the other sports; every MLB stat
# is a count on its own scale, so the smoothing floor is per-stat.
# ---------------------------------------------------------------------------
MODEL = {"halfLife": 6.0, "maxGames": 20, "priorK": 0.5, "bwConst": 0.9, "z": 1.2816}
BW_FLOOR = {"h": 0.5, "tb": 0.8, "hrr": 0.8, "r": 0.5, "rbi": 0.5, "hr": 0.35, "sb": 0.35,
            "bb": 0.5, "so": 0.5, "k": 1.0, "outs": 2.0, "ha": 1.0, "er": 0.8, "pbb": 0.6}
# Opponent adjustment: the player's distribution is scaled by
# (opponent's per-game number / league average)^gamma, clamped. For hitting stats
# that's what the opposing staff allows; for pitching stats it's what the opposing
# lineup does (strikes out, gets hits, walks, scores). In a postseason game pitching
# stats are also scaled by pstPitch: starters get pulled earlier in October than the
# regular-season starts the model learns from, so every per-start count runs lower.
CTX = {"gamma": 0.45, "clampLo": 0.6, "clampHi": 1.6, "pstPitch": 0.9}


def _erf(x):
    s = 1.0 if x >= 0 else -1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return s * y


def ncdf(x):
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def model_prob(values, line, floor, scale=1.0):
    """values oldest -> newest; floor is the per-stat bandwidth floor; scale
    multiplies every value (opponent adjustment). Mirror of the JS version."""
    v = [x * scale for x in values[-MODEL["maxGames"]:]]
    n = len(v)
    if n == 0:
        return None
    hl = MODEL["halfLife"]
    w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]
    W = sum(w)
    W2 = sum(x * x for x in w)
    neff = W * W / W2
    mean = sum(wi * x for wi, x in zip(w, v)) / W
    var = sum(wi * (x - mean) ** 2 for wi, x in zip(w, v)) / W
    sd = math.sqrt(max(var, 0.0))
    h = max(MODEL["bwConst"] * sd * neff ** (-0.2), floor)

    def F(t):
        return sum(wi * ncdf((t - x) / h) for wi, x in zip(w, v)) / W

    lo_edge = math.floor(line) + 0.5
    hi_edge = math.ceil(line) - 0.5
    over_raw = 1.0 - F(lo_edge)
    under_raw = F(hi_edge)
    push = max(0.0, 1.0 - over_raw - under_raw)
    tot = over_raw + under_raw
    pc = over_raw / tot if tot > 0 else 0.5
    k = MODEL["priorK"]
    p = (neff * pc + k * 0.5) / (neff + k)
    nq = neff + k
    z = MODEL["z"]
    z2 = z * z
    c = (p + z2 / (2 * nq)) / (1 + z2 / nq)
    hw = z * math.sqrt(p * (1 - p) / nq + z2 / (4 * nq * nq)) / (1 + z2 / nq)
    return {"over": p, "under": 1.0 - p, "push": push, "lo": max(0.0, c - hw), "hi": min(1.0, c + hw),
            "neff": neff, "mean": mean, "sd": sd, "h": h, "n": n, "scale": scale}


def median(a):
    if not a:
        return 0
    s = sorted(a)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def seed_line(values):
    """Realistic line for a stat: median of the last 10, rounded to the .5 below the
    nearest whole number (so a 2-hit median seeds 1.5 hits). Mirrored in the page."""
    last = values[-10:]
    if not last:
        return 0.5
    med = median(last)
    seed = (math.floor(med + 0.5) - 0.5) if med >= 1.5 else 0.5
    return max(0.5, seed)


def grade_result(actual, line, side):
    if actual == line:
        return "push"
    if side == "over":
        return "hit" if actual > line else "miss"
    return "hit" if actual < line else "miss"


def stat_get(row, sk):
    if sk == "hrr":
        return row[4] + row[6] + row[7]
    return row[IDX[sk]] if sk in IDX else 0


def stat_values(rows, sk):
    """The games a stat is read from, oldest -> newest: pitching stats from starts
    (any outing while an arm has fewer than 3), hitting stats from lineup starts (any
    game at the plate while a hitter has fewer than 5). Keeps a starter's line from
    being dragged down by a relief inning, and a regular's by a pinch-hit at-bat.
    Mirrored in the page's valuesOf()."""
    if sk in PITCH_STATS:
        use = [r for r in rows if r[20] == 2]
        if len(use) < 3:
            use = [r for r in rows if r[20] >= 1]
    else:
        use = [r for r in rows if r[19] == 2]
        if len(use) < 5:
            use = [r for r in rows if r[19] >= 1]
    return [stat_get(r, sk) for r in use]


# ---------------------------------------------------------------------------
# Fetch + parse helpers
# ---------------------------------------------------------------------------
def http_get(url, timeout=25, tries=2):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            err = e
            code = getattr(e, "code", None)
            if code in (403, 404):     # blocked/not-found won't recover on retry
                break
            if i < tries - 1:
                time.sleep(1.5)
    raise err


def over_budget():
    return (time.time() - _START) > BUDGET_SEC


def get_json(url):
    return json.loads(http_get(url))


def team_code(t):
    return (t or "").upper()


def pkey(s):
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    for ch in ".'`-":
        s = s.replace(ch, "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def num(v):
    if v in (None, "", "--"):
        return 0
    try:
        f = round(float(v), 1)
    except (ValueError, TypeError):
        return 0
    return int(f) if float(f).is_integer() else f


def fnum(v):
    try:
        return float(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def ip_outs(v):
    """ESPN innings pitched '5.2' (5 innings + 2 outs) -> 17 outs."""
    m = re.match(r"\s*(\d+)(?:\.(\d))?", str(v or ""))
    return int(m.group(1)) * 3 + int(m.group(2) or 0) if m else 0


def parse_utc(s):
    """ESPN's '2026-09-29T23:00Z' / Polymarket's '...T23:00:00Z' -> aware UTC datetime, or None."""
    try:
        t = datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# ESPN box scores
# ---------------------------------------------------------------------------
def scan_dates():
    """Dates to backfill, newest first."""
    return [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS + 1)]


def sb_events(date_iso):
    sb = get_json(f"{ESPN_SB}?dates={date_iso.replace('-', '')}")
    return sb.get("events") or []


def event_teams(comp):
    cs = comp.get("competitors") or []
    home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
    away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
    return home, away


def parse_box(summ, season, date_iso, stype, home, away):
    """One ESPN summary -> a stat row per player who batted or pitched. A two-way
    player's batting and pitching lines share one row."""
    # Doubles and triples per batter from the play-by-play (the box line only has H and HR).
    xb = {}
    for pl in summ.get("plays") or []:
        t = ((pl.get("type") or {}).get("text") or "").strip().lower()
        kind = 0 if t in ("double", "ground rule double") else 1 if t == "triple" else None
        if kind is None:
            continue
        bat = next((str((pp.get("athlete") or {}).get("id") or "") for pp in pl.get("participants") or []
                    if pp.get("type") == "batter"), "")
        if bat:
            xb.setdefault(bat, [0, 0])[kind] += 1
    steals = {}
    for ro in summ.get("rosters") or []:
        for e in ro.get("roster") or []:
            pid = str((e.get("athlete") or {}).get("id") or "")
            for s in e.get("stats") or []:
                if s.get("name") == "stolenBases":
                    steals[pid] = num(s.get("value", s.get("displayValue")))
    rows = {}
    for tb in (summ.get("boxscore") or {}).get("players") or []:
        team = team_code((tb.get("team") or {}).get("abbreviation"))
        opp = away if team == home else home
        for cat in tb.get("statistics") or []:
            kind = (cat.get("type") or "").lower()
            if kind not in ("batting", "pitching"):
                continue
            keys = [str(k) for k in (cat.get("keys") or [])]
            for ath in cat.get("athletes") or []:
                if ath.get("didNotPlay"):
                    continue
                info = ath.get("athlete") or {}
                disp = (info.get("displayName") or "").strip()
                pid = str(info.get("id") or "")
                st = ath.get("stats") or []
                if not disp or not pid or not st:
                    continue
                d = dict(zip(keys, st))
                pos = ((info.get("position") or {}).get("abbreviation") or (ath.get("position") or {}).get("abbreviation") or "").upper()
                r = rows.get(pid)
                if r is None:
                    r = rows[pid] = {"pid": pid, "name": disp, "pos": pos, "team": team, "opp": opp,
                                     "season": season, "date": date_iso, "type": stype,
                                     "home": 1 if team == home else 0, "bat": 0, "pit": 0}
                    for k in ROW_STATS:
                        r[k] = 0
                if kind == "batting":
                    h, hr = num(d.get("hits")), num(d.get("homeRuns"))
                    dbl, tpl = xb.get(pid, [0, 0])
                    extra = max(0, h - hr)                  # doubles + triples can't exceed non-HR hits
                    dbl, tpl = min(dbl, extra), min(tpl, max(0, extra - dbl))
                    r.update(bat=2 if ath.get("starter") else 1, ab=num(d.get("atBats")), h=h,
                             r=num(d.get("runs")), rbi=num(d.get("RBIs")), hr=hr, bb=num(d.get("walks")),
                             so=num(d.get("strikeouts")), tb=h + dbl + 2 * tpl + 3 * hr, sb=steals.get(pid, 0))
                    if pos and pos not in ("PH", "PR"):
                        r["pos"] = pos
                else:
                    r.update(pit=2 if ath.get("starter") else 1, outs=ip_outs(d.get("fullInnings.partInnings")),
                             k=num(d.get("strikeouts")), ha=num(d.get("hits")), er=num(d.get("earnedRuns")),
                             pbb=num(d.get("walks")))
                    if not r["bat"] and pos:
                        r["pos"] = pos
    return list(rows.values())


def game_rows(summ, gid):
    """Rows for a finished regular-season or postseason game; [] for a game to skip
    for good (spring training, All-Star); None while it isn't final yet."""
    header = summ.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    home, away = event_teams(comp)
    st = (header.get("season") or {}).get("type")
    if st not in (2, 3) or home not in MLB_TEAMS or away not in MLB_TEAMS:
        return []
    date_g = (comp.get("date") or "")[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}$", date_g):
        return []
    season = int((header.get("season") or {}).get("year") or date_g[:4])
    rows = parse_box(summ, season, date_g, "PST" if st == 3 else "REG", home, away)
    for r in rows:
        r["gid"] = gid
    return rows


def fetch_summary(gid):
    try:
        return gid, get_json(ESPN_SUMMARY.format(gid=gid))
    except Exception as e:  # noqa: BLE001
        print(f"    box {gid}: skipped ({e})")
        return gid, None


def fetch_new_games(store):
    """Fetch box scores for completed games not yet in the store, newest-first,
    capped at MAX_NEW_GAMES and BUDGET_SEC. A date safely in the past whose games
    are all captured goes in store['done'] so later runs don't re-scan it."""
    seen = set(store.get("seen", []))
    done = set(store.get("done", []))
    added = 0
    settle = TODAY - datetime.timedelta(days=2)   # dates newer than this may still gain games
    for date_iso in scan_dates():
        if added >= MAX_NEW_GAMES or over_budget():
            break
        if date_iso in done:
            continue
        try:
            evs = sb_events(date_iso)
        except Exception as e:  # noqa: BLE001
            print(f"    scoreboard {date_iso}: skipped ({e})")
            continue
        complete_date = True
        todo = []
        for ev in evs:
            gid = str(ev.get("id") or "")
            if not gid or gid in seen:
                continue
            comp = (ev.get("competitions") or [{}])[0]
            if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                complete_date = False            # still to play (or postponed): look again later
                continue
            todo.append(gid)
        room = MAX_NEW_GAMES - added
        if len(todo) > room:
            todo, complete_date = todo[:room], False
        with ThreadPoolExecutor(max_workers=4) as ex:
            got = list(ex.map(fetch_summary, todo))
        for gid, summ in got:
            if summ is None:
                complete_date = False
                continue
            rows = game_rows(summ, gid)
            if rows is None:
                complete_date = False
                continue
            store["rows"].extend(rows)
            seen.add(gid)
            if rows:
                added += 1
        if complete_date and datetime.date.fromisoformat(date_iso) < settle:
            done.add(date_iso)
    store["seen"] = sorted(seen)
    store["done"] = sorted(done)
    return added


# ---------------------------------------------------------------------------
# Today's slate (for the board) — started and completed games are left out.
# ---------------------------------------------------------------------------
# Games ESPN shows as under way or over, as (frozenset of the two team codes, UTC
# date) — the date matters because a playoff series plays the same matchup on back-
# to-back days, and last night's final mustn't block today's game. No new pick is
# recorded for these, so none is ever made at an in-game price.
STARTED = set()
# Every game on the scoreboard, started or not, as (away, home, UTC start). Copied onto
# its picks by stamp_starts(), since the scoreboard only covers one day.
SB_GAMES = []


def fetch_slate():
    """Today's games (ET) plus whatever ESPN's default scoreboard shows, which can
    still be last night's late games — those are only used to spot games under way."""
    evs, ids = [], set()
    for url in (ESPN_SB, f"{ESPN_SB}?dates={ET_TODAY.replace('-', '')}"):
        try:
            for ev in get_json(url).get("events") or []:
                if ev.get("id") not in ids:
                    ids.add(ev.get("id"))
                    evs.append(ev)
        except Exception as e:  # noqa: BLE001
            print(f"    slate: {url[-20:]} skipped ({e})")
    games = []
    for ev in evs:
        comp = (ev.get("competitions") or [{}])[0]
        status = ((comp.get("status") or {}).get("type") or {})
        home, away = event_teams(comp)
        if home not in MLB_TEAMS or away not in MLB_TEAMS:
            continue
        start = ev.get("date") or ""
        if start:
            SB_GAMES.append((away, home, start))
        if status.get("completed") or status.get("state", "pre") != "pre":
            STARTED.add((frozenset((away, home)), start[:10]))
            continue
        total = spread = None
        odds = comp.get("odds") or []
        if odds:
            o = odds[0]
            total = o.get("overUnder")
            sp = o.get("spread")
            if sp is not None:
                try:
                    spread = -float(sp)   # ESPN spread is the home line (neg = home fav); store + = favored
                except (TypeError, ValueError):
                    spread = None
        probables, pnames = {}, {}
        for c in comp.get("competitors") or []:
            t = team_code((c.get("team") or {}).get("abbreviation"))
            for pr in c.get("probables") or []:
                ath = pr.get("athlete") or {}
                aid = str(ath.get("id") or pr.get("playerId") or "")
                if aid:
                    probables[t] = aid
                    pnames[t] = ath.get("displayName") or ath.get("fullName") or ""
                    break
        tm = ""
        m = re.search(r"T(\d{2}):(\d{2})", start)
        if m:
            hh = (int(m.group(1)) - 4) % 24    # UTC -> ET (in-season, ~UTC-4)
            tm = f"{hh:02d}:{m.group(2)}"
        games.append({"away": away, "home": home, "date": start[:10], "time": tm, "start": start,
                      "total": total, "spread": spread, "final": False,
                      "pst": (ev.get("season") or {}).get("type") == 3,
                      "probables": probables, "pnames": pnames})
    games.sort(key=lambda g: (g["date"], g["time"]))
    return games


def stamp_starts(picks):
    """Save the scoreboard's start time on each pending pick for that game (same two
    teams, date within a day)."""
    for p in picks:
        if p.get("res") is not None or p.get("start"):
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$", p.get("gid") or "")
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        for away, home, start in SB_GAMES:
            t = parse_utc(start)
            if t and (away, home) == (m.group(2), m.group(3)) and abs((t.date() - d).days) <= 1:
                p["start"] = start
                break


def pick_started(p):
    """True once the pick's game is under way or over. A pick with no start time
    falls back to its date: one dated before today (ET) has started."""
    t = parse_utc(p.get("start"))
    if t:
        return t <= datetime.datetime.now(datetime.timezone.utc)
    return (p.get("date") or "") < ET_TODAY


# ---------------------------------------------------------------------------
# Polymarket US (the CFTC exchange at polymarket.us): public gateway, no key,
# 20 req/s per IP. MLB player props are "at least N" ladders — "Will Ben Rice
# record at least 2 total bases" = over 1.5 — and live prices come from each
# market's BBO.
# ---------------------------------------------------------------------------
POLYUS_EVENTS = ("https://gateway.polymarket.us/v1/events?tagSlug=mlb&active=true&closed=false"
                 "&startDateMin={a}T00:00:00Z&startDateMax={b}T00:00:00Z&limit=100")
POLYUS_EVENT = "https://gateway.polymarket.us/v1/events/slug/{slug}"
POLYUS_BBO = "https://gateway.polymarket.us/v1/markets/{slug}/bbo"
US_SLUG = re.compile(r"^mlb-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})$")
US_Q = re.compile(r"^Will (.+?) record at least (\d+) ", re.I)
# sportsMarketType suffix (after "baseball_player_") -> our stat key
SMT_STAT = {"hits": "h", "total_bases": "tb", "hits_runs_rbis": "hrr", "rbis": "rbi", "runs": "r",
            "home_runs": "hr", "stolen_bases": "sb", "walks": "bb", "strikeouts": "k", "outs": "outs",
            "hits_allowed": "ha", "earned_runs_allowed": "er", "walks_allowed": "pbb"}
# Highest "at least N" rung priced per stat — the rest are long shots, and every rung is a BBO call.
US_MAX_N = {"h": 3, "tb": 4, "hrr": 5, "rbi": 3, "r": 2, "hr": 1, "sb": 1, "bb": 2,
            "k": 12, "outs": 21, "ha": 9, "er": 5, "pbb": 5}
# Polymarket US team codes that differ from ESPN's
POLY_TEAM = {"cws": "CHW", "chw": "CHW", "was": "WSH", "oak": "ATH", "az": "ARI",
             "tbr": "TB", "kcr": "KC", "sfg": "SF", "sdp": "SD", "ana": "LAA"}


def poly_team(tok):
    tok = (tok or "").lower()
    return POLY_TEAM.get(tok, tok.upper())


def _px(v):
    return fnum(v.get("value")) if isinstance(v, dict) else None


def fetch_markets_us(players_by_key):
    """Polymarket US MLB player props for games that haven't started, each market
    already parsed (key 'pm'). Only players we model are priced. Non-fatal."""
    a = (TODAY - datetime.timedelta(days=1)).isoformat()
    b = (TODAY + datetime.timedelta(days=4)).isoformat()
    try:
        data = json.loads(http_get(POLYUS_EVENTS.format(a=a, b=b), timeout=60))
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket US: skipped ({e})")
        return []
    events = (data.get("events") if isinstance(data, dict) else None) or []
    now = datetime.datetime.now(datetime.timezone.utc)
    games, todo = [], []
    for ev in events:
        m = US_SLUG.match(ev.get("slug", "") or "")
        if not m:
            continue
        start = ev.get("startTime") or ev.get("startDate") or ""
        st = parse_utc(start)
        if st is None or st <= now:
            continue            # under way: its prices are in-game, not pre-game
        mkts = ev.get("markets")
        if mkts is None:
            try:
                mkts = (json.loads(http_get(POLYUS_EVENT.format(slug=ev["slug"]))).get("event") or {}).get("markets")
            except Exception:  # noqa: BLE001
                mkts = []
        g = {"slug": ev["slug"], "away": poly_team(m.group(1)), "home": poly_team(m.group(2)),
             "date": m.group(3), "start": start, "markets": [],
             "pst": bool(re.match(r"Game \d+:", ev.get("title") or ""))}   # "Game 2: BOS Red Sox vs. NY Yankees"
        for mk in mkts or []:
            smt = mk.get("sportsMarketType") or ""
            if not smt.startswith("baseball_player_") or mk.get("closed"):
                continue
            sk = SMT_STAT.get(smt[len("baseball_player_"):])
            qm = US_Q.match(mk.get("question") or "")
            n = fnum(mk.get("line"))
            if not sk or not qm or n is None or n > US_MAX_N.get(sk, 3):
                continue
            name = qm.group(1).strip()
            pl = players_by_key.get(pkey(name))
            if not pl or len(stat_values(pl["g"], sk)) < 3:
                continue
            todo.append((g, mk.get("slug"), name, sk, n - 0.5))
        games.append(g)

    def bbo(item):
        time.sleep(0.35)          # 6 workers x ~3/s stays under the 20 req/s limit
        try:
            return item, json.loads(http_get(POLYUS_BBO.format(slug=item[1]))).get("marketData") or {}
        except Exception:  # noqa: BLE001
            return item, None

    def ok(p):
        return p is not None and 0.02 < p < 0.98

    with ThreadPoolExecutor(max_workers=6) as ex:
        for (g, _slug, name, sk, line), md in ex.map(bbo, todo):
            if not md:
                continue
            ask, bid = _px(md.get("bestAsk")), _px(md.get("bestBid"))
            over = ask if ok(ask) else None                     # buy Yes = over
            under = (1 - bid) if bid is not None and ok(1 - bid) else None   # buy No = under
            spread = (ask - bid) if ask is not None and bid is not None else None
            tradeable = (over is not None or under is not None) and (spread is None or spread <= 0.15)
            g["markets"].append({"pm": {"player": name, "sk": sk, "line": line,
                                        "over": over, "under": under, "tradeable": tradeable}})
    games = [g for g in games if g["markets"]]
    print(f"  polymarket US: {len(games)} MLB game(s), {sum(len(g['markets']) for g in games)} priced player props")
    return games


# ---------------------------------------------------------------------------
# Build players / defense from the accumulated store
# ---------------------------------------------------------------------------
def build_players(rows):
    by = {}
    for r in rows:
        game = [r["season"], r["date"], r["opp"], r["type"]] + [r.get(k, 0) for k in ROW_STATS] + \
               [r["home"], r.get("bat", 0), r.get("pit", 0), r.get("total"), r.get("spread")]
        p = by.setdefault(r["pid"], {"rows": [], "pos": [], "meta": r})
        p["rows"].append((r["date"], game))
        p["pos"].append((r["date"], r.get("pos") or ""))
        if r["date"] >= p["meta"]["date"]:
            p["meta"] = r
    out = []
    for pid, p in by.items():
        games = [g for _, g in sorted(p["rows"], key=lambda x: x[0])]
        recent = [ps for _, ps in sorted(p["pos"])[-15:] if ps and ps not in ("PH", "PR")]
        pos = Counter(recent).most_common(1)[0][0] if recent else (p["meta"].get("pos") or "MLB")
        out.append({"id": pid, "n": p["meta"]["name"], "p": pos, "t": p["meta"]["team"], "g": games})
    out.sort(key=lambda x: x["n"])
    return out


DEF_STATS = ["h", "tb", "hrr", "r", "hr", "bb", "so", "k", "ha", "er", "pbb"]


def row_val(r, sk):
    return r["h"] + r["r"] + r["rbi"] if sk == "hrr" else (r.get(sk) or 0)


def build_defense(rows, cur_season):
    """Per-team, per-stat per-game numbers against that team, blended toward the
    current season, ranked (1 = the most). A row's `opp` is the team it came
    against, so hitting stats sum to what that staff allows and pitching stats to
    what that lineup does. def[team]['MLB'][stat] = {a, r, n}."""
    per = {}
    for r in rows:
        opp = r["opp"]
        if not opp:
            continue
        e = per.setdefault(opp, {}).setdefault(r["season"], {"games": set(), "sums": {}})
        e["games"].add(r["gid"])
        for sk in DEF_STATS:
            e["sums"][sk] = e["sums"].get(sk, 0) + row_val(r, sk)
    PRIOR = 20.0
    allowed = {}
    gmax = 0
    for team, seasons in per.items():
        cur = seasons.get(cur_season, {"games": set(), "sums": {}})
        prev = seasons.get(cur_season - 1, {"games": set(), "sums": {}})
        gc, gp = len(cur["games"]), len(prev["games"])
        gmax = max(gmax, gc)
        for sk in DEF_STATS:
            pa = (prev["sums"].get(sk, 0) / gp) if gp else None
            if gc == 0 and pa is None:
                continue
            if pa is None:
                a = cur["sums"].get(sk, 0) / gc
            elif gc == 0:
                a = pa
            else:
                a = (cur["sums"].get(sk, 0) + PRIOR * pa) / (gc + PRIOR)
            allowed.setdefault(team, {})[sk] = a
    defense, avg = {}, {}
    for sk in DEF_STATS:
        vals = [(t, allowed[t][sk]) for t in allowed if sk in allowed[t]]
        if not vals:
            continue
        vals.sort(key=lambda x: x[1], reverse=True)
        for i, (t, v) in enumerate(vals):
            defense.setdefault(t, {}).setdefault("MLB", {})[sk] = {"a": round(v, 2), "r": i + 1, "n": len(vals)}
        avg[sk] = round(sum(v for _, v in vals) / len(vals), 2)
    return defense, {"MLB": avg}, gmax


# Matchup number used for each prop (None = no opponent adjustment: steals depend on
# the catcher/pitcher more than the team, and outs on the starter's leash).
DEF_FOR = {"h": "h", "tb": "tb", "hrr": "hrr", "r": "r", "rbi": "r", "hr": "hr", "sb": None,
           "bb": "bb", "so": "so", "k": "k", "outs": None, "ha": "ha", "er": "er", "pbb": "pbb"}


def def_ratio(defense, defavg, opp, sk):
    ds = DEF_FOR.get(sk)
    if not ds or not opp:
        return None
    a = defense.get(opp, {}).get("MLB", {}).get(ds, {}).get("a")
    L = defavg.get("MLB", {}).get(ds)
    return (a / L) if (a is not None and L) else None


def context_scale(def_r, sk, pst):
    dfs = def_r ** CTX["gamma"] if (def_r and def_r > 0) else 1.0
    if pst and sk in PITCH_STATS:
        dfs *= CTX["pstPitch"]
    return min(CTX["clampHi"], max(CTX["clampLo"], dfs))


# ---------------------------------------------------------------------------
# Picks (board + market + grading + calibration)
# ---------------------------------------------------------------------------
PICK_COLS = ["src", "gid", "season", "date", "pid", "player", "pos", "team", "opp",
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj", "start"]
BAT_BOARD = ["h", "tb", "hrr"]
PIT_BOARD = ["k", "outs"]
TOP_N = 25
T_MIN_PROB = 0.90      # Top 25 Surest: the model has to give it 90%+ (and it needs a live price)
VALUE_MIN_NEFF = 6.0
# Value rules mirror build.py (NFL) so every sport's lists mean the same.
VALUE_N = 200           # a safety cap only. At 50 it bound in busy weeks (NFL week 3: 27 picks that
                        # cleared the rule went unrecorded), so the record now holds every pick that clears it
VALUE_MIN_PRICE = 0.30  # the market has to give it at least 30%
VALUE_MIN_EDGE = 0.15   # and the model has to be 15+ points higher


def value_qualifies(prob, price):
    """prob and price are fractions; price is what you'd pay for this side."""
    return price is not None and price >= VALUE_MIN_PRICE and prob - price >= VALUE_MIN_EDGE


def load_picks():
    try:
        with open(PICKS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    cols = d.get("cols") or []
    return [dict(zip(cols, row)) for row in d.get("picks", [])]


def side_prob(mp):
    if mp["over"] >= 0.5:
        return "over", mp["over"], mp["lo"], mp["hi"]
    return "under", mp["under"], 1 - mp["hi"], 1 - mp["lo"]


def make_pick(pl, gid, date, team, opp, sk, line, mp, scale, start, prices=None):
    side, prob, lo, hi = side_prob(mp)
    price = None
    if prices and prices.get("tradeable"):
        price = prices["over"] if side == "over" else prices["under"]
    return {"src": "live", "gid": gid, "season": pl["g"][-1][0], "date": date,
            "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
            "stat": sk, "line": line, "side": side,
            "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
            "neff": round(mp["neff"], 1), "price": round(price, 3) if price is not None else None,
            "lists": "", "rec": f"{sk} {side} {line}", "actual": None, "res": None,
            "adj": round(scale, 3), "start": start or None}


def refresh_price(p, pm):
    """A pending pick whose game hasn't started keeps the market's current price for its
    side (None once that market stops being tradeable), like NFL's pre-kickoff refresh —
    so "has a live market" for Top 25 Surest means now, not when the pick was recorded."""
    if p.get("res") is None and not pick_started(p):
        px = (pm["over"] if p["side"] == "over" else pm["under"]) if pm.get("tradeable") else None
        p["price"] = round(px, 3) if px is not None else None


def build_market_picks(picks, poly_games, players_by_key, espn_slate, defense, defavg):
    """Priced picks from Polymarket US MLB markets, matched to players by name. Each
    is modeled at the market's line so Value spots can compare model vs price."""
    have = {(p["pid"], p["date"], p["stat"], p["line"]): p for p in picks}
    added = 0
    for g in poly_games:
        eg = next((x for x in espn_slate if {x["away"], x["home"]} == {g["away"], g["home"]}), None)
        # ESPN's orientation and UTC date, so the pick grades against the box score
        away, home = (eg["away"], eg["home"]) if eg else (g["away"], g["home"])
        st = parse_utc(g.get("start"))
        date = eg["date"] if eg else (st.date().isoformat() if st else g["date"])
        start = (eg or {}).get("start") or g.get("start")
        pst = (eg or g).get("pst")
        if (frozenset((away, home)), date) in STARTED:
            continue            # already started or over: its price is in-game, not pre-game
        gid = f"{date}-{away}-{home}"
        for m in g.get("markets", []):
            pm = m.get("pm")
            if not pm:
                continue
            sk = pm["sk"]
            pl = players_by_key.get(pkey(pm["player"]))
            if not pl:
                continue
            team = pl["t"]
            opp = home if team == away else (away if team == home else None)
            if opp is None:
                continue        # the player's last team isn't in this game (traded / wrong match)
            key = (pl["id"], date, sk, pm["line"])
            if key in have:
                refresh_price(have[key], pm)
                continue
            vals = stat_values(pl["g"], sk)
            if len(vals) < 3:
                continue
            scale = context_scale(def_ratio(defense, defavg, opp, sk), sk, pst)
            mp = model_prob(vals, pm["line"], BW_FLOOR.get(sk, 1.0), scale)
            if not mp:
                continue
            picks.append(make_pick(pl, gid, date, team, opp, sk, pm["line"], mp, scale, start, pm))
            have[key] = picks[-1]
            added += 1
    return added


def build_board_picks(picks, slate, players_by_team, by_pid, defense, defavg):
    """For each game on today's slate: hits / total bases / H+R+RBI for every hitter
    who's been starting lately, and strikeouts / outs for the two probable starters.
    One pick per (player, stat) at the site's seeded line, the model's side."""
    have = {(p["pid"], p["date"], p["stat"]) for p in picks}
    added = 0
    for g in slate:
        gid = f"{g['date']}-{g['away']}-{g['home']}"
        for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
            roster = players_by_team.get(team, [])
            last = max((pl["g"][-1][1] for pl in roster if pl["g"]), default=None)
            cutoff = (datetime.date.fromisoformat(last) - datetime.timedelta(days=7)).isoformat() if last else ""
            cands = []
            for pl in roster:
                starts = [r for r in pl["g"] if r[19] == 2]
                if len(starts) >= 5 and starts[-1][1] >= cutoff:
                    cands += [(pl, sk) for sk in BAT_BOARD]
            sp = by_pid.get((g.get("probables") or {}).get(team))
            if sp and sum(1 for r in sp["g"] if r[20] == 2) >= 3:
                cands += [(sp, sk) for sk in PIT_BOARD]
            for pl, sk in cands:
                if (pl["id"], g["date"], sk) in have:
                    continue
                vals = stat_values(pl["g"], sk)
                line = seed_line(vals)
                scale = context_scale(def_ratio(defense, defavg, opp, sk), sk, g.get("pst"))
                mp = model_prob(vals, line, BW_FLOOR.get(sk, 1.0), scale)
                if not mp or mp["neff"] < VALUE_MIN_NEFF:
                    continue
                picks.append(make_pick(pl, gid, g["date"], team, opp, sk, line, mp, scale, g.get("start")))
                have.add((pl["id"], g["date"], sk))
                added += 1
    return added


def box_games(rows):
    """Every game whose box score is in the store, as (ESPN UTC date, away, home)."""
    out = set()
    for r in rows:
        home, away = (r["team"], r["opp"]) if r.get("home") else (r["opp"], r["team"])
        out.add((r["date"], away, home))
    return out


def pick_box_game(p, games):
    """The pick's game as it sits in the store — (date, away, home) — or None until its
    box score is in. A playoff series plays the same matchup on back-to-back days, so
    the date has to be exact: the saved start time's UTC date (ESPN's row date), else
    the gid date. Never a neighbouring day, which would be yesterday's game."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$", p.get("gid") or "")
    if not m:
        return None
    gd, away, home = m.groups()
    t = parse_utc(p.get("start"))
    key = (t.date().isoformat() if t else gd, away, home)
    return key if key in games else None


def grade_picks(picks, by_pid, games):
    """Grade pending picks once their game's box score is in the store. A player with no
    row in that game didn't play (bench, scratched starter), so the pick is voided as
    'dnp' rather than staying pending forever. Returns (graded, dnp)."""
    n = dnp = 0
    for p in picks:
        if p.get("res") is not None or not pick_started(p):
            continue
        g = pick_box_game(p, games)
        if g is None:
            continue       # not final yet (or not ingested)
        date, away, home = g
        pl = by_pid.get(p["pid"])
        row = next((r for r in pl["g"] if r[1] == date and r[2] in (away, home)), None) if pl else None
        if row is None:
            p["res"], p["actual"] = "dnp", None
            dnp += 1
            continue
        actual = stat_get(row, p["stat"])
        p["actual"] = actual
        p["res"] = grade_result(actual, p["line"], p["side"])
        n += 1
    return n, dnp


def assign_lists(picks):
    """T = 'Top 25 Surest': up to 25 props the model gives 90%+ that have a live
    Polymarket price, ranked by model chance. V = 'Value' — the market prices it at 30c
    or more and the model puts it 15+ points higher, ranked by that edge. Both keep one
    line per player-prop. Prices are fractions here. Only picks whose game hasn't
    started are (re)tagged: once it starts they keep the lists they had at first pitch
    until graded, so the live record by list counts exactly what the page showed pre-game."""
    pending = [p for p in picks if p.get("res") is None and not pick_started(p)]
    for p in pending:
        p["lists"] = ""

    def one_per_prop(items):
        """Best line only per player, stat and game: Polymarket lists 1+/2+/3+ ladders,
        and four rungs of one pitcher's outs are one opinion, not four picks."""
        seen, out = set(), []
        for p in items:
            k = (p["pid"], p["stat"], p["gid"])
            if k not in seen:
                seen.add(k)
                out.append(p)
        return out

    # Top 25 Surest: only props the model gives 90%+ that have a live Polymarket price,
    # up to 25 — so a thin slate shows fewer, or none.
    ranked = one_per_prop(sorted((p for p in pending if p["prob"] >= T_MIN_PROB and p.get("price") is not None),
                                 key=lambda p: (-p["prob"], -p["neff"])))
    for p in ranked[:TOP_N]:
        p["lists"] += "T"
    vals = [p for p in pending
            if p.get("price") is not None and p["neff"] >= VALUE_MIN_NEFF
            and value_qualifies(p["prob"], p["price"])]
    for p in one_per_prop(sorted(vals, key=lambda p: -(p["prob"] - p["price"])))[:VALUE_N]:
        p["lists"] += "V"


def fit_temperature(picks):
    data = []
    for p in picks:
        if p.get("res") in ("hit", "miss") and p.get("prob") is not None:
            pr = min(0.999, max(0.001, float(p["prob"])))
            data.append((math.log(pr / (1 - pr)), 1.0 if p["res"] == "hit" else 0.0))
    if len(data) < 400:
        return 1.0

    def loss(T):
        s = 30.0 * (T - 1.0) ** 2
        for lg, y in data:
            q = min(0.9999, max(0.0001, 1.0 / (1.0 + math.exp(-lg / T))))
            s -= y * math.log(q) + (1 - y) * math.log(1 - q)
        return s

    best_T, best_L, T = 1.0, None, 0.70
    while T <= 2.001:
        L = loss(T)
        if best_L is None or L < best_L:
            best_L, best_T = L, T
        T += 0.02
    return round(min(2.0, max(0.7, best_T)), 3)


def live_record(picks):
    out = {}
    for p in picks:
        if p.get("res") not in ("hit", "miss"):
            continue
        for tag in p.get("lists", ""):
            r = out.setdefault(tag, {"n": 0, "hit": 0, "priced": 0, "units": 0.0})
            r["n"] += 1
            if p["res"] == "hit":
                r["hit"] += 1
            # 1 unit on every priced pick; prices are fractions, so a win pays 1/price - 1.
            if p.get("price"):
                r["priced"] += 1
                r["units"] += (1.0 / p["price"] - 1) if p["res"] == "hit" else -1
    for r in out.values():
        r["units"] = round(r["units"], 2)
    return out


def save_picks(picks):
    keep = [p for p in picks if p.get("res") is not None or p.get("src") == "live"]
    doc = {"gen": TODAY.isoformat(), "model": MODEL, "cols": PICK_COLS,
           "picks": [[p.get(c) for c in PICK_COLS] for p in keep]}
    with open(PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    graded = sum(1 for p in keep if p.get("res") in ("hit", "miss", "push"))
    dnp = sum(1 for p in keep if p.get("res") == "dnp")
    return f"{len(keep)} pick(s), {graded} graded, {dnp} DNP"


# ---------------------------------------------------------------------------
def load_store():
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("seen", [])
        s.setdefault("done", [])
        s.setdefault("rows", [])
        return s
    except (OSError, ValueError):
        return {"gen": None, "seen": [], "done": [], "rows": []}


def prune_store(store):
    """Drop rows more than KEEP_DAYS older than the newest one (relative, so the
    offseason doesn't empty the store)."""
    newest = max((r["date"] for r in store["rows"]), default=None)
    if not newest:
        return
    cut = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    store["rows"] = [r for r in store["rows"] if r["date"] >= cut]


def main():
    cur_season = TODAY.year
    print(f"MLB build — season {cur_season}, {TODAY.isoformat()}")

    store = load_store()
    before = len(store.get("seen", []))
    try:
        added = fetch_new_games(store)
    except Exception as e:  # noqa: BLE001
        print(f"  ESPN ingestion failed ({e}); using existing store only")
        added = 0
    prune_store(store)
    store["gen"] = TODAY.isoformat()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  store: +{added} games this run, {len(store['seen'])} total ({before} before), "
          f"{len(store['rows'])} rows, {time.time() - _START:.0f}s")

    try:
        slate = fetch_slate()
    except Exception as e:  # noqa: BLE001
        print(f"  slate: skipped ({e})")
        slate = []
    print(f"  slate: {len(slate)} upcoming game(s), {len(STARTED)} under way or final")

    players = build_players(store["rows"])
    by_pid = {p["id"]: p for p in players}
    players_by_team = {}
    players_by_key = {}
    for p in players:
        players_by_team.setdefault(p["t"], []).append(p)
        players_by_key.setdefault(pkey(p["n"]), p)
    defense, defavg, dgames = build_defense(store["rows"], cur_season)

    try:
        poly_games = fetch_markets_us(players_by_key)
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket US: skipped ({e})")
        poly_games = []

    picks = load_picks()
    graded, dnp = grade_picks(picks, by_pid, box_games(store["rows"]))
    try:
        mkt_added = build_market_picks(picks, poly_games, players_by_key, slate, defense, defavg)
    except Exception as e:  # noqa: BLE001
        print(f"  market picks: skipped ({e})")
        mkt_added = 0
    added_picks = build_board_picks(picks, slate, players_by_team, by_pid, defense, defavg)
    stamp_starts(picks)
    assign_lists(picks)
    print(f"  picks: graded {graded}, {dnp} DNP, +{mkt_added} priced (Polymarket), +{added_picks} board")
    try:
        cal_t = fit_temperature(picks)
    except Exception as e:  # noqa: BLE001
        print(f"  calibration: skipped ({e})")
        cal_t = 1.0
    print(f"  calibration temperature: T={cal_t}")
    summary = save_picks(picks)
    print(f"  {PICKS_FILE}: {summary}")

    seasons_used = sorted({r["season"] for r in store["rows"]}, reverse=True)
    thru = max((r["date"] for r in store["rows"]), default=None)
    db = {
        "gen": TODAY.isoformat(),
        "sport": "mlb",
        "season": cur_season,
        "seasons": seasons_used,
        "thru": thru,
        "defGames": dgames,
        "week": {"season": cur_season, "games": slate},
        "defense": defense,
        "defAvg": defavg,
        "calT": cal_t,
        "record": live_record(picks),
        "players": players,
    }
    payload = json.dumps(db, separators=(",", ":"), ensure_ascii=False)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"  {DATA_FILE}: {len(players)} players, {len(payload)} bytes")

    if os.path.exists(TEMPLATE):
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            template = f.read()
        if "__MLBDATA__" not in template:
            print(f"  WARNING: {TEMPLATE} missing __MLBDATA__ placeholder — not writing {PAGE}")
        else:
            with open(PAGE, "w", encoding="utf-8") as f:
                f.write(template.replace("__MLBDATA__", payload))
            print(f"  {PAGE}: written")
    else:
        print(f"  {TEMPLATE} not found — skipping {PAGE}")


if __name__ == "__main__":
    sys.exit(main())

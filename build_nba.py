#!/usr/bin/env python3
"""
Prop Streak Lab — NBA data builder (sibling of build.py for the NFL site).

There is no nflverse-style bulk source for the NBA, so this pulls player box
scores straight from ESPN's public API (the same endpoints build.py already uses
to fill fresh NFL games) and accumulates them into a growing local store. Each
run only fetches games it hasn't seen yet — capped per run — so the store
self-builds over a few nightly runs and then stays cheap to keep current.

Python 3 standard library only. Run: python build_nba.py

Outputs
  nba_stats.json  the raw accumulated player box-score rows (source of truth)
  nba.json        the compact dataset the NBA page runs on
  nba_picks.json  every NBA pick the site has made, graded as games finish
  nba.html        nba_template.html with nba.json baked in (the NBA page)

The probability model here mirrors the block marked "MODEL" in nba_template.html.
Change both or neither. Everything that touches the network is wrapped so a bad
ESPN response degrades to "no new data" instead of failing the build.
"""
import json, math, os, re, sys, time, datetime, unicodedata, urllib.request

TODAY = datetime.date.today()
UA = {"User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}

# ESPN blocks site.api.espn.com from data-center IPs (Akamai 403), but two hosts
# still serve NBA data from CI: the core API (honors a date -> game ids) and the
# cdn "core" boxscore (full player stats by game id). The cdn scoreboard ignores
# the date param, so it's only used for the current/upcoming slate.
ESPN_CORE_EVENTS = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events?dates={date}&limit=100"
ESPN_CDN_BOX = "https://cdn.espn.com/core/nba/boxscore?xhr=1&gameId={gid}"
ESPN_CDN_SB = "https://cdn.espn.com/core/nba/scoreboard?xhr=1"

# Polymarket NBA player-prop markets (auto-activates when the season posts them;
# off-season it simply finds nothing and the board stays model-only). Mirrors the
# NFL setup in build.py. The exact NBA slug/team format can only be confirmed once
# markets exist, so team matching accepts abbreviations, cities, or nicknames.
POLY_SLATE = ("https://gamma-api.polymarket.com/events"
              "?closed=false&tag_slug=nba&limit=500&order=startDate&ascending=false")
POLY_EVENT = "https://gamma-api.polymarket.com/events/slug/{slug}"
POLY_SLUG = re.compile(r"^nba-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})-player-props$")
Q_RE = re.compile(r"^(.*?):\s*(.+?)\s+O/U\s+([\d.]+)", re.I)
# Market question text -> our stat key. Order matters (combos and threes first).
MKT_STAT_NBA = [
    (re.compile(r"pts\s*\+\s*reb\s*\+\s*ast|points\s*\+\s*rebounds\s*\+\s*assists|\bpra\b", re.I), "pra"),
    (re.compile(r"pts\s*\+\s*reb|points\s*\+\s*rebounds", re.I), "pr"),
    (re.compile(r"pts\s*\+\s*ast|points\s*\+\s*assists", re.I), "pa"),
    (re.compile(r"reb\s*\+\s*ast|rebounds\s*\+\s*assists", re.I), "ra"),
    (re.compile(r"three|3-?point|3pm|3s\b|treys", re.I), "tpm"),
    (re.compile(r"rebounds?", re.I), "reb"),
    (re.compile(r"assists?", re.I), "ast"),
    (re.compile(r"steals?", re.I), "stl"),
    (re.compile(r"blocks?", re.I), "blk"),
    (re.compile(r"turnovers?", re.I), "to"),
    (re.compile(r"points?", re.I), "pts"),
]
# Team nickname / city -> ESPN abbreviation, so Polymarket slugs match ESPN games
# whether they use "lakers", "losangeles", or "lal".
NBA_TEAMS = {
    "hawks": "ATL", "atlanta": "ATL", "celtics": "BOS", "boston": "BOS",
    "nets": "BKN", "brooklyn": "BKN", "hornets": "CHA", "charlotte": "CHA",
    "bulls": "CHI", "chicago": "CHI", "cavaliers": "CLE", "cavs": "CLE", "cleveland": "CLE",
    "mavericks": "DAL", "mavs": "DAL", "dallas": "DAL", "nuggets": "DEN", "denver": "DEN",
    "pistons": "DET", "detroit": "DET", "warriors": "GSW", "goldenstate": "GSW",
    "rockets": "HOU", "houston": "HOU", "pacers": "IND", "indiana": "IND",
    "clippers": "LAC", "kings": "SAC", "sacramento": "SAC", "lakers": "LAL",
    "grizzlies": "MEM", "memphis": "MEM", "heat": "MIA", "miami": "MIA",
    "bucks": "MIL", "milwaukee": "MIL", "timberwolves": "MIN", "wolves": "MIN", "minnesota": "MIN",
    "pelicans": "NOP", "neworleans": "NOP", "knicks": "NYK", "newyork": "NYK",
    "thunder": "OKC", "oklahomacity": "OKC", "magic": "ORL", "orlando": "ORL",
    "76ers": "PHI", "sixers": "PHI", "philadelphia": "PHI", "suns": "PHX", "phoenix": "PHX",
    "trailblazers": "POR", "blazers": "POR", "portland": "POR", "spurs": "SAS", "sanantonio": "SAS",
    "raptors": "TOR", "toronto": "TOR", "jazz": "UTA", "utah": "UTA",
    "wizards": "WAS", "washington": "WAS",
}


def poly_team(tok):
    tok = (tok or "").lower()
    return NBA_TEAMS.get(tok, tok.upper())

STATS_FILE = "nba_stats.json"
PICKS_FILE = "nba_picks.json"
DATA_FILE = "nba.json"
TEMPLATE = "nba_template.html"
PAGE = "nba.html"

# How many previously-unseen games to fetch box scores for in a single run. The
# store fills newest-first, so the freshest games land first and older games
# backfill over subsequent runs. Keeps any one Action run bounded.
MAX_NEW_GAMES = 140
CANDIDATE_SEASONS = 2          # this season + the previous one
# Hard wall-clock budget for the whole ESPN ingestion. ESPN throttles a data-center
# IP that hammers it, so a run stops fetching once this elapses and saves what it
# has — the `done`-date cache means the backfill resumes cheaply next run.
BUDGET_SEC = 210
_START = time.time()

# ---------------------------------------------------------------------------
# Row layout — the NBA page reads game rows by index. Keep in sync with
# nba_template.html.
#   0 season  1 date(YYYY-MM-DD)  2 opp  3 type(REG/PST)
#   4 pts 5 reb 6 ast 7 tpm(3PM) 8 stl 9 blk 10 to 11 min
#   12 fgm 13 fga 14 ftm 15 fta  16 home(1/0)  17 started(1/0)
#   18 game total (Vegas, or null)  19 team spread (+ = favored, or null)
# ---------------------------------------------------------------------------
STAT_ORDER = ["pts", "reb", "ast", "tpm", "stl", "blk", "to", "min", "fgm", "fga", "ftm", "fta"]

# ---------------------------------------------------------------------------
# MODEL — mirrored in nba_template.html (block marked MODEL). Keep identical.
# Same weighted-KDE-over-recent-values engine as the NFL model, but every NBA
# stat is a count on its own scale, so the smoothing floor is per-stat rather
# than one number for "yards" vs "count".
# ---------------------------------------------------------------------------
MODEL = {"halfLife": 6.0, "maxGames": 20, "priorK": 0.5, "bwConst": 0.9, "z": 1.2816}
# Minimum smoothing bandwidth per stat (roughly a third of a typical game-to-game swing).
BW_FLOOR = {"pts": 3.0, "reb": 1.2, "ast": 1.0, "tpm": 0.7, "stl": 0.5, "blk": 0.5,
            "to": 0.7, "min": 3.0, "fgm": 1.4, "fga": 2.0, "ftm": 1.2, "fta": 1.4,
            "pra": 4.0, "pr": 3.4, "pa": 3.4, "ra": 1.6}
# Game-context adjustment (one family for the NBA): the player's distribution is
# scaled by (this game's implied team points / their usual implied points)^betaPts
# times (opponent's allowed-per-game / league average)^gamma. Clamped.
CTX = {"betaPts": 0.30, "gamma": 0.45, "clampLo": 0.6, "clampHi": 1.6}


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
    multiplies every value (game-context adjustment). Mirror of the JS version."""
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
    """Realistic line for a stat: median of the last 10, rounded to nearest .5
    below the whole number. Mirrored in the front-end."""
    last = values[-10:]
    if not last:
        return 0.5
    med = median(last)
    seed = (math.floor(med + 0.5) - 0.5) if med >= 3 else 0.5
    return max(0.5, seed)


def grade_result(actual, line, side):
    if actual == line:
        return "push"
    if side == "over":
        return "hit" if actual > line else "miss"
    return "hit" if actual < line else "miss"


# ---------------------------------------------------------------------------
# Fetch + parse helpers
# ---------------------------------------------------------------------------
def http_get(url, timeout=20, tries=2):
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
    if v in (None, ""):
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


def _jsonish(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _ma(s):
    """Parse ESPN 'made-attempted' cells like '10-19' -> (10, 19)."""
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", str(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def mkt_stat_key(txt):
    for rx, k in MKT_STAT_NBA:
        if rx.search(txt or ""):
            return k
    return None


def parse_market(m):
    """One Polymarket O/U market -> dict, or None. Prices are what you'd PAY per side."""
    q = m.get("question") or m.get("groupItemTitle") or ""
    mm = Q_RE.match(q)
    if not mm:
        return None
    player, stat_text = mm.group(1).strip(), mm.group(2).strip()
    if re.search(r"\bvs\b", player, re.I):
        return None
    outs = _jsonish(m.get("outcomes")) or []
    prices = _jsonish(m.get("outcomePrices")) or []
    io_ = next((i for i, o in enumerate(outs) if re.search(r"over", str(o), re.I)), -1)
    try:
        mid = float(prices[io_]) if 0 <= io_ < len(prices) else None
    except (TypeError, ValueError):
        mid = None
    bid, ask = fnum(m.get("bestBid")), fnum(m.get("bestAsk"))
    if bid is not None and ask is not None and io_ == 1:
        bid, ask = 1 - ask, 1 - bid
    spread = fnum(m.get("spread"))
    if spread is None and bid is not None and ask is not None:
        spread = round(ask - bid, 3)
    liq = fnum(m.get("liquidityNum")) or 0.0
    tight = spread is not None and spread <= 0.15
    deep = liq >= 300 and spread is not None and spread <= 0.60
    tradeable = tight or deep
    over_buy = ask if ask is not None else mid
    under_buy = (1 - bid) if bid is not None else (1 - mid if mid is not None else None)

    def ok(p):
        return p is not None and 0.02 < p < 0.98

    if not (ok(over_buy) and ok(under_buy)):
        tradeable = False
    line = fnum(m.get("line"))
    if line is None:
        line = float(mm.group(3))
    return {"player": player, "statText": stat_text, "line": line,
            "over": over_buy if ok(over_buy) else None, "under": under_buy if ok(under_buy) else None,
            "tradeable": tradeable}


def fetch_markets():
    """Polymarket NBA player-prop events in a [-1,+10] day window, with markets.
    Non-fatal; returns [] off-season or if the API/format doesn't match."""
    try:
        events = json.loads(http_get(POLY_SLATE))
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket: skipped ({e})")
        return []
    games = []
    for ev in events if isinstance(events, list) else []:
        slug = ev.get("slug", "")
        m = POLY_SLUG.match(slug)
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(3))
        except ValueError:
            continue
        if not (TODAY - datetime.timedelta(days=1) <= d <= TODAY + datetime.timedelta(days=10)):
            continue
        games.append({"slug": slug, "away": poly_team(m.group(1)), "home": poly_team(m.group(2)), "date": m.group(3)})
    if not games:
        print("  polymarket: no NBA player-prop events yet (off-season or format differs)")
        return []
    print(f"  polymarket: {len(games)} NBA player-prop event(s)")
    for g in games:
        try:
            g["markets"] = json.loads(http_get(POLY_EVENT.format(slug=g["slug"]))).get("markets", [])
        except Exception as e:  # noqa: BLE001
            print(f"    event {g['slug']}: skipped ({e})")
            g["markets"] = []
    return games


def season_year(d):
    """NBA season label = the calendar year the season tipped off (Oct)."""
    return d.year if d.month >= 9 else d.year - 1


# ---------------------------------------------------------------------------
# ESPN scoreboard + box scores
# ---------------------------------------------------------------------------
def scan_dates(season):
    """Every date (newest first) in the NBA window for a season (the tip-off year)."""
    start = datetime.date(season, 10, 1)
    end = min(TODAY, datetime.date(season + 1, 7, 15))
    out = []
    d = end
    while d >= start:
        out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out


def core_event_ids(date_iso):
    """Game ids on a date, via the core API (which honors the date param)."""
    data = get_json(ESPN_CORE_EVENTS.format(date=date_iso.replace("-", "")))
    ids = []
    for it in data.get("items", []) or []:
        m = re.search(r"/events/(\d+)", it.get("$ref", "") or "")
        if m:
            ids.append(m.group(1))
    return ids


def header_meta(gpj):
    """From a cdn boxscore's gamepackageJSON header: (completed, home, away, date, type)."""
    header = gpj.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    status = ((comp.get("status") or {}).get("type") or {})
    completed = bool(status.get("completed"))
    cs = comp.get("competitors") or []
    home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
    away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
    date_g = (comp.get("date") or "")[:10]
    stype = "PST" if (header.get("season") or {}).get("type") == 3 else "REG"
    return completed, home, away, date_g, stype


def parse_box(box, season, date_iso, stype, home, away):
    """One cdn boxscore dict -> stat row dicts for every player who logged minutes."""
    rows = []
    for tb in (box or {}).get("players") or []:
        team = team_code((tb.get("team") or {}).get("abbreviation"))
        opp = away if team == home else home
        for cat in tb.get("statistics") or []:
            labels = [str(l).upper() for l in (cat.get("labels") or [])]
            for ath in cat.get("athletes") or []:
                if ath.get("didNotPlay"):
                    continue
                info = ath.get("athlete") or {}
                disp = (info.get("displayName") or "").strip()
                pid = str(info.get("id") or "")
                if not disp or not pid:
                    continue
                st = ath.get("stats") or []
                if not st:
                    continue
                d = {labels[i]: st[i] for i in range(min(len(labels), len(st)))}
                fgm, fga = _ma(d.get("FG"))
                tpm, _tpa = _ma(d.get("3PT"))
                ftm, fta = _ma(d.get("FT"))
                pos = ((info.get("position") or {}).get("abbreviation") or "").upper()
                rows.append({
                    "pid": pid, "name": disp, "pos": pos or "NBA", "team": team, "opp": opp,
                    "season": season, "date": date_iso, "type": stype,
                    "home": 1 if team == home else 0,
                    "started": 1 if ath.get("starter") else 0,
                    "min": num(d.get("MIN")), "pts": num(d.get("PTS")),
                    "reb": num(d.get("REB")), "ast": num(d.get("AST")),
                    "tpm": tpm, "stl": num(d.get("STL")), "blk": num(d.get("BLK")),
                    "to": num(d.get("TO")), "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
                })
    return rows


def fetch_new_games(store):
    """Fetch box scores for completed games not yet in the store, newest-first,
    capped at MAX_NEW_GAMES. A date safely in the past whose games are all captured
    is remembered in store['done'] so later runs don't re-scan it — keeping nightly
    runs cheap once the backfill is complete. Returns the number of games added."""
    seen = set(store.get("seen", []))
    done = set(store.get("done", []))
    added = 0
    interrupted = False
    cur = season_year(TODAY)
    seasons = [cur - i for i in range(CANDIDATE_SEASONS)]
    settle = TODAY - datetime.timedelta(days=2)   # dates newer than this may still gain games
    for season in seasons:
        if added >= MAX_NEW_GAMES or over_budget():
            interrupted = True
            break
        for date_iso in scan_dates(season):
            if added >= MAX_NEW_GAMES or over_budget():
                interrupted = True
                break
            if date_iso in done:
                continue
            try:
                ids = core_event_ids(date_iso)
            except Exception as e:  # noqa: BLE001
                print(f"    events {date_iso}: skipped ({e})")
                continue
            complete_date = True
            for gid in ids:
                gid = str(gid)
                if not gid or gid in seen:
                    continue
                if added >= MAX_NEW_GAMES or over_budget():
                    complete_date = False        # ran out of budget before finishing this date
                    break
                try:
                    bx = get_json(ESPN_CDN_BOX.format(gid=gid))
                except Exception as e:  # noqa: BLE001
                    print(f"    box {gid}: skipped ({e})")
                    complete_date = False
                    continue
                gpj = bx.get("gamepackageJSON") or {}
                completed, home, away, date_g, stype = header_meta(gpj)
                if not completed:
                    complete_date = False        # a game that day isn't final yet
                    continue
                if not home or not away:
                    continue
                if not re.match(r"\d{4}-\d{2}-\d{2}", date_g or ""):
                    date_g = date_iso
                rows = parse_box(gpj.get("boxscore") or {}, season, date_g, stype, home, away)
                if not rows:
                    continue
                for r in rows:
                    r["gid"] = gid
                store["rows"].extend(rows)
                seen.add(gid)
                added += 1
            # A past date we fully captured never needs re-scanning (empty days too).
            try:
                dd = datetime.date.fromisoformat(date_iso)
            except ValueError:
                dd = TODAY
            if complete_date and dd < settle:
                done.add(date_iso)
    store["seen"] = sorted(seen)
    store["done"] = sorted(done)
    return added


# ---------------------------------------------------------------------------
# Tonight's / upcoming slate (for the board) — completed games are ignored here.
# ---------------------------------------------------------------------------
def fetch_slate():
    """The current/upcoming board (the cdn scoreboard returns today's games; it
    ignores a date param, which is fine — the NBA page shows tonight's slate)."""
    games = []
    try:
        sb = get_json(ESPN_CDN_SB)
    except Exception as e:  # noqa: BLE001
        print(f"    slate: skipped ({e})")
        return games
    events = ((sb.get("content") or {}).get("sbData") or {}).get("events", []) or []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        status = ((comp.get("status") or {}).get("type") or {})
        if status.get("completed"):
            continue
        cs = comp.get("competitors") or []
        home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
        away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
        if not home or not away:
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
        start = ev.get("date") or ""
        tm = ""
        m = re.search(r"T(\d{2}):(\d{2})", start)
        if m:
            hh = (int(m.group(1)) - 4) % 24    # UTC -> ET (in-season, ~UTC-4)
            tm = f"{hh:02d}:{m.group(2)}"
        games.append({"away": away, "home": home, "date": start[:10],
                      "time": tm, "total": total, "spread": spread, "final": False})
    games.sort(key=lambda g: (g["date"], g["time"]))
    return games


# ---------------------------------------------------------------------------
# Build players / defense from the accumulated store
# ---------------------------------------------------------------------------
def build_players(rows):
    by = {}
    for r in rows:
        total = r.get("total")
        spr = r.get("spread")
        game = [r["season"], r["date"], r["opp"], r["type"],
                r["pts"], r["reb"], r["ast"], r["tpm"], r["stl"], r["blk"], r["to"], r["min"],
                r["fgm"], r["fga"], r["ftm"], r["fta"], r["home"], r.get("started", 0),
                total, spr]
        p = by.setdefault(r["pid"], {"rows": [], "meta": r})
        p["rows"].append(game)
        p["meta"] = r
    out = []
    for pid, p in by.items():
        games = sorted(p["rows"], key=lambda g: (g[0], g[1]))
        meta = p["meta"]
        out.append({"id": pid, "n": meta["name"], "p": meta.get("pos") or "NBA",
                    "t": meta["team"], "g": games})
    out.sort(key=lambda x: x["n"])
    return out


DEF_STATS = ["pts", "reb", "ast", "tpm", "stl", "blk"]


def build_defense(rows, cur_season):
    """Per-team, per-stat opponent per-game allowed, blended toward the current
    season, ranked (1 = softest = allows the most). def[team]['NBA'][stat]={a,r,n}."""
    # team -> season -> {games:set, sums:{stat:total}}
    per = {}
    for r in rows:
        opp = r["opp"]
        if not opp:
            continue
        e = per.setdefault(opp, {}).setdefault(r["season"], {"games": set(), "sums": {}})
        e["games"].add(r["gid"])
        for sk in DEF_STATS:
            e["sums"][sk] = e["sums"].get(sk, 0) + (r.get(sk) or 0)
    PRIOR = 12.0
    allowed = {}
    gmax = 0
    for team, seasons in per.items():
        cur = seasons.get(cur_season, {"games": set(), "sums": {}})
        prev = seasons.get(cur_season - 1, {"games": set(), "sums": {}})
        gc = len(cur["games"])
        gp = len(prev["games"])
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
            defense.setdefault(t, {}).setdefault("NBA", {})[sk] = {"a": round(v, 1), "r": i + 1, "n": len(vals)}
        avg[sk] = round(sum(v for _, v in vals) / len(vals), 2)
    return defense, {"NBA": avg}, gmax


# defense proxy stat for each prop key
DEF_FOR = {"pts": "pts", "reb": "reb", "ast": "ast", "tpm": "tpm", "stl": "stl", "blk": "blk",
           "fgm": "pts", "fga": "pts", "ftm": "pts", "fta": "pts", "min": None,
           "pra": "pts", "pr": "pts", "pa": "pts", "ra": "reb", "to": None}


def def_ratio(defense, defavg, opp, sk):
    ds = DEF_FOR.get(sk)
    if not ds or not opp:
        return None
    t = defense.get(opp, {}).get("NBA", {})
    a = t.get(ds, {}).get("a")
    L = defavg.get("NBA", {}).get(ds)
    return (a / L) if (a is not None and L) else None


# ---------------------------------------------------------------------------
# Picks (board + grading + calibration)
# ---------------------------------------------------------------------------
PICK_COLS = ["src", "gid", "season", "date", "pid", "player", "pos", "team", "opp",
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj"]
BOARD_STATS = ["pts", "reb", "ast", "tpm", "pra"]
TOP_N = 25
VALUE_MIN_NEFF = 6.0


def stat_get(row, sk):
    idx = {"pts": 4, "reb": 5, "ast": 6, "tpm": 7, "stl": 8, "blk": 9, "to": 10, "min": 11,
           "fgm": 12, "fga": 13, "ftm": 14, "fta": 15}
    if sk in idx:
        return row[idx[sk]]
    if sk == "pra":
        return row[4] + row[5] + row[6]
    if sk == "pr":
        return row[4] + row[5]
    if sk == "pa":
        return row[4] + row[6]
    if sk == "ra":
        return row[5] + row[6]
    return 0


def hist_context(rows):
    r = rows[-MODEL["maxGames"]:]
    n = len(r)
    sp = wp = 0.0
    for i, g in enumerate(r):
        tot, spr = g[18], g[19]
        if tot is None or spr is None:
            continue
        w = 0.5 ** ((n - 1 - i) / MODEL["halfLife"])
        sp += w * (tot / 2 + spr / 2)
        wp += w
    return sp / wp if wp else None


def context_scale(hist_pts, game_pts, def_r):
    env = 1.0
    if hist_pts and game_pts and hist_pts > 0 and game_pts > 0:
        env *= (game_pts / hist_pts) ** CTX["betaPts"]
    dfs = def_r ** CTX["gamma"] if (def_r and def_r > 0) else 1.0
    return min(CTX["clampHi"], max(CTX["clampLo"], env * dfs))


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


def build_market_picks(picks, poly_games, players_by_key, espn_slate, defense, defavg):
    """Priced picks from Polymarket NBA markets, matched to players by name. Each
    is modeled at the market's line so Value spots can compare model vs price.
    Returns count added; no-op when there are no NBA markets (off-season)."""
    have = {(p["pid"], p["date"], p["stat"], p["line"]) for p in picks}
    added = 0
    for g in poly_games:
        eg = next((x for x in espn_slate if {x["away"], x["home"]} == {g["away"], g["home"]}), None)
        gid = f"{g['date']}-{g['away']}-{g['home']}"
        for m in g.get("markets", []):
            pm = parse_market(m)
            if not pm:
                continue
            sk = mkt_stat_key(pm["statText"])
            if not sk:
                continue
            pl = players_by_key.get(pkey(pm["player"]))
            if not pl or len(pl["g"]) < 5:
                continue
            team = pl["t"]
            opp = g["home"] if team == g["away"] else (g["away"] if team == g["home"] else None)
            if opp is None:
                continue
            key = (pl["id"], g["date"], sk, pm["line"])
            if key in have:
                continue
            rows = pl["g"]
            hp = hist_context(rows)
            gpts = None
            if eg and eg.get("total") is not None:
                sp = eg.get("spread") if team == eg["home"] else (-(eg["spread"]) if eg.get("spread") is not None else None)
                gpts = eg["total"] / 2 + (sp / 2 if sp is not None else 0)
            dr = def_ratio(defense, defavg, opp, sk)
            scale = context_scale(hp, gpts, dr)
            vals = [stat_get(r, sk) for r in rows]
            mp = model_prob(vals, pm["line"], BW_FLOOR.get(sk, 1.0), scale)
            if not mp:
                continue
            side, prob, lo, hi = side_prob(mp)
            price = (pm["over"] if side == "over" else pm["under"]) if pm.get("tradeable") else None
            picks.append({"src": "live", "gid": gid, "season": rows[-1][0], "date": g["date"],
                          "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                          "stat": sk, "line": pm["line"], "side": side,
                          "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                          "neff": round(mp["neff"], 1), "price": round(price, 3) if price is not None else None,
                          "lists": "", "rec": f"{sk} {side} {pm['line']}", "actual": None, "res": None,
                          "adj": round(scale, 3)})
            have.add(key)
            added += 1
    return added


def build_board_picks(picks, slate, players_by_team, defense, defavg):
    """One pick per (player, board stat) for players on teams playing an upcoming
    game — the highest-confidence side. Deduped against already-recorded picks."""
    have = {(p["pid"], p["date"], p["stat"]) for p in picks}
    now_added = 0
    for g in slate:
        if g.get("final"):
            continue
        gid = f"{g['date']}-{g['away']}-{g['home']}"
        for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
            gpts = None
            if g.get("total") is not None:
                sp = g.get("spread") if team == g["home"] else (-(g["spread"]) if g.get("spread") is not None else None)
                gpts = g["total"] / 2 + (sp / 2 if sp is not None else 0)
            for pl in players_by_team.get(team, []):
                rows = pl["g"]
                if len(rows) < 5:
                    continue
                hp = hist_context(rows)
                for sk in BOARD_STATS:
                    if (pl["id"], g["date"], sk) in have:
                        continue
                    vals = [stat_get(r, sk) for r in rows]
                    line = seed_line(vals)
                    dr = def_ratio(defense, defavg, opp, sk)
                    scale = context_scale(hp, gpts, dr)
                    mp = model_prob(vals, line, BW_FLOOR.get(sk, 1.0), scale)
                    if not mp or mp["neff"] < VALUE_MIN_NEFF:
                        continue
                    side, prob, lo, hi = side_prob(mp)
                    picks.append({"src": "live", "gid": gid, "season": rows[-1][0], "date": g["date"],
                                  "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                                  "stat": sk, "line": line, "side": side,
                                  "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                                  "neff": round(mp["neff"], 1), "price": None, "lists": "",
                                  "rec": f"{sk} {side} {line}", "actual": None, "res": None,
                                  "adj": round(scale, 3)})
                    have.add((pl["id"], g["date"], sk))
                    now_added += 1
    return now_added


def grade_picks(picks, by_pid):
    n = 0
    for p in picks:
        if p.get("res") is not None:
            continue
        pl = by_pid.get(p["pid"])
        if not pl:
            continue
        row = next((r for r in pl["g"] if r[1] == p["date"]), None)
        if row is None:
            continue
        actual = stat_get(row, p["stat"])
        p["actual"] = actual
        p["res"] = grade_result(actual, p["line"], p["side"])
        n += 1
    return n


def assign_lists(picks):
    """T = 25 highest model chances. V = up to 25 best-value priced picks where even
    the low end of the model range beats the market price (empty until markets exist)."""
    for p in picks:
        p["lists"] = ""
    pending = [p for p in picks if p.get("res") is None]
    for p in sorted(pending, key=lambda p: (-p["prob"], -p["neff"]))[:TOP_N]:
        p["lists"] += "T"
    vals = []
    for p in pending:
        pr = p.get("price")
        if pr is None or p["neff"] < VALUE_MIN_NEFF:
            continue
        if p["lo"] > pr:
            vals.append((p["prob"] / pr - 1.0, p))
    for _, p in sorted(vals, key=lambda x: -x[0])[:TOP_N]:
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
            r = out.setdefault(tag, {"n": 0, "hit": 0})
            r["n"] += 1
            if p["res"] == "hit":
                r["hit"] += 1
    return out


def save_picks(picks):
    keep = [p for p in picks if p.get("res") is not None or p.get("src") == "live"]
    doc = {"gen": TODAY.isoformat(), "model": MODEL, "cols": PICK_COLS,
           "picks": [[p.get(c) for c in PICK_COLS] for p in keep]}
    with open(PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    graded = sum(1 for p in keep if p.get("res") in ("hit", "miss", "push"))
    return f"{len(keep)} pick(s), {graded} graded"


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


def prune_store(store, cur_season):
    keep_seasons = {cur_season - i for i in range(CANDIDATE_SEASONS)}
    store["rows"] = [r for r in store["rows"] if r.get("season") in keep_seasons]


def _keys(d):
    return list(d.keys()) if isinstance(d, dict) else f"<{type(d).__name__}>"


def _cdn_events(dstr):
    sb = get_json(f"https://cdn.espn.com/core/nba/scoreboard?xhr=1&dates={dstr}")
    return ((sb.get("content") or {}).get("sbData") or {}).get("events", [])


def probe():
    """Decide the data source: does cdn honor dates, and where are box scores?"""
    print("  --- data-source probe ---")
    try:
        for dstr in ("20251225", "20260110"):
            evs = _cdn_events(dstr)
            first = evs[0] if evs else {}
            comp = (first.get("competitions") or [{}])[0]
            comp_state = (comp.get("status") or {}).get("type", {})
            print(f"    CDN sb dates={dstr}: {len(evs)} events; first date={first.get('date')} "
                  f"completed={comp_state.get('completed')} id={first.get('id')}")
    except Exception as e:  # noqa: BLE001
        print(f"    CDN sb ERROR: {e}")
    # core API (honors dates) -> pull a real completed game id, then try cdn boxscore
    try:
        core = get_json("https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events?dates=20251225")
        items = core.get("items", [])
        print(f"    CORE events dates=20251225: count={core.get('count')} items={len(items)}")
        ref = (items[0] or {}).get("$ref", "") if items else ""
        gid = re.search(r"/events/(\d+)", ref)
        gid = gid.group(1) if gid else None
        print(f"    CORE first event id={gid} ref={ref[:80]}")
        if gid:
            bx = get_json(f"https://cdn.espn.com/core/nba/boxscore?xhr=1&gameId={gid}")
            gpj = bx.get("gamepackageJSON") or {}
            box = gpj.get("boxscore", {})
            players = box.get("players", [])
            print(f"    CDN box gid={gid}: boxscore keys={_keys(box)} players_teams={len(players)}")
            if players:
                tb = players[0]
                stcats = tb.get("statistics") or []
                print(f"    CDN box team0={(tb.get('team') or {}).get('abbreviation')} cats={len(stcats)}")
                if stcats:
                    c0 = stcats[0]
                    print(f"    CDN box labels={c0.get('labels')}")
                    ath = (c0.get('athletes') or [])
                    if ath:
                        a0 = ath[0]
                        print(f"    CDN box athlete={(a0.get('athlete') or {}).get('displayName')} "
                              f"id={(a0.get('athlete') or {}).get('id')} stats={a0.get('stats')} "
                              f"starter={a0.get('starter')} dnp={a0.get('didNotPlay')}")
            # also: does the scheduled date on this event look like Dec 25?
            print(f"    CDN box header date={(gpj.get('header') or {}).get('competitions',[{}])[0].get('date') if gpj.get('header') else '?'}")
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"    CORE/BOX ERROR: {e}\n{traceback.format_exc()[:400]}")
    print("  --- end probe ---")


def main():
    cur_season = season_year(TODAY)
    print(f"NBA build — season {cur_season}, {TODAY.isoformat()}")
    if os.environ.get("NBA_PROBE"):
        probe()

    store = load_store()
    before = len(store.get("seen", []))
    try:
        added = fetch_new_games(store)
    except Exception as e:  # noqa: BLE001
        print(f"  ESPN ingestion failed ({e}); using existing store only")
        added = 0
    prune_store(store, cur_season)
    store["gen"] = TODAY.isoformat()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  store: +{added} games this run, {len(store['seen'])} total ({before} before), {len(store['rows'])} rows")

    # attach Vegas total/spread from the slate to any store rows for those games?
    # (historical rows have no odds; that's fine — context falls back to defense.)
    try:
        slate = fetch_slate()
    except Exception as e:  # noqa: BLE001
        print(f"  slate: skipped ({e})")
        slate = []
    print(f"  slate: {len(slate)} upcoming game(s)")

    players = build_players(store["rows"])
    by_pid = {p["id"]: p for p in players}
    players_by_team = {}
    players_by_key = {}
    for p in players:
        players_by_team.setdefault(p["t"], []).append(p)
        players_by_key.setdefault(pkey(p["n"]), p)
    defense, defavg, dgames = build_defense(store["rows"], cur_season)

    # Polymarket NBA markets (auto-activates in-season; no-op off-season).
    try:
        poly_games = fetch_markets()
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket: skipped ({e})")
        poly_games = []

    picks = load_picks()
    graded = grade_picks(picks, by_pid)
    try:
        mkt_added = build_market_picks(picks, poly_games, players_by_key, slate, defense, defavg)
    except Exception as e:  # noqa: BLE001
        print(f"  market picks: skipped ({e})")
        mkt_added = 0
    added_picks = build_board_picks(picks, slate, players_by_team, defense, defavg)
    assign_lists(picks)
    if mkt_added:
        print(f"  market picks: +{mkt_added} priced (Polymarket)")
    print(f"  picks: graded {graded}, added {added_picks} board pick(s)")
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
        "sport": "nba",
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
        if "__NBADATA__" not in template:
            print(f"  WARNING: {TEMPLATE} missing __NBADATA__ placeholder — not writing {PAGE}")
        else:
            with open(PAGE, "w", encoding="utf-8") as f:
                f.write(template.replace("__NBADATA__", payload))
            print(f"  {PAGE}: written")
    else:
        print(f"  {TEMPLATE} not found — skipping {PAGE}")


if __name__ == "__main__":
    main()

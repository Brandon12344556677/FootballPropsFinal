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
from concurrent.futures import ThreadPoolExecutor

import news   # pre-game news feeds, test mode
import kalshi  # Kalshi prices, side by side with Polymarket's
import depth   # enough money at the price? (thin-market filter)
import holds   # props that wait for injury news

TODAY = datetime.date.today()
ET_TODAY = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)).date().isoformat()
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
# Walk-forward backtest on the 2025-26 box scores (27,564 player games per stat, each
# predicted from earlier games only, scored on odd and on even days separately): 82 games
# at half-life 10 beat 20 at half-life 6 on every stat and both halves, and the floors
# below (threes 0.7 -> 0.17: the old one put 58% on overs that hit 54%). Log loss, old ->
# new: threes 0.5688 -> 0.5445, blocks 0.5741 -> 0.5586, rebounds 0.6053 -> 0.6002,
# assists 0.5986 -> 0.5956, points 0.6716 -> 0.6694, PRA 0.6672 -> 0.6653.
MODEL = {"halfLife": 10.0, "maxGames": 82, "priorK": 0.5, "bwConst": 0.9, "z": 1.2816}
MODEL_V = 2   # recorded on every pick ("mv"); calibration fits only this version's picks
# Minimum smoothing bandwidth per stat. FG/FT and minutes weren't refitted.
BW_FLOOR = {"pts": 4.0, "reb": 0.8, "ast": 0.75, "tpm": 0.17, "stl": 0.5, "blk": 0.35,
            "to": 0.7, "min": 3.0, "fgm": 1.4, "fga": 2.0, "ftm": 1.2, "fta": 1.4,
            "pra": 3.0, "pr": 3.4, "pa": 3.4, "ra": 1.6}
# Game-context adjustment (one family for the NBA): the player's distribution is
# scaled by (this game's implied team points / their usual implied points)^betaPts
# times (opponent's allowed-per-game / league average)^gamma. Clamped.
# gamma 0.65 (was 0.45) won on every stat and both halves, by 0.0002-0.0005. Also tested
# and not used: rest / back-to-backs, the opponent on a back-to-back, opponent pace and
# home court (none beat the model without them on both halves).
CTX = {"betaPts": 0.30, "gamma": 0.65, "minutes": 0.5, "clampLo": 0.6, "clampHi": 1.6}

# Per-stat calibration, fitted on the same walk-forward backtest: the chance's log-odds become
# a + b * log-odds. It removes a bias the smoothing leaves (most props read overs a few points
# high) and fixes over/under-confidence. Fitted at the seeded line and a line either side on
# one half of the data and scored on the other, both ways; only stats where that improved
# both halves are listed (the rest are left as they were).
CAL = {"pts": (-0.034, 1.135), "reb": (-0.028, 1.09), "ast": (-0.076, 1.088), "tpm": (-0.055, 0.962), "blk": (-0.252, 0.969), "stl": (-0.193, 0.965), "ra": (-0.016, 1.114), "to": (-0.147, 1.097)}
# Minutes: recent minutes / usual minutes (see minutes_ratio), to the power CTX["minutes"].
# On last season's stored games, fitting on one half of the dates and scoring the other
# (odd/even days, first/second half, each both ways) chose 0.5 every time and improved
# every time, and every board stat improved: log loss 0.6238 -> 0.6222 over 122,805
# props. Every pick also records "sh", its chance with the strength at MIN_TEST (0 =
# without minutes), and each build logs how the two compare on graded picks.
MIN_TEST = 0.0


def _erf(x):
    s = 1.0 if x >= 0 else -1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return s * y


def ncdf(x):
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def calibrate(p, cal):
    """A chance through a per-stat (a, b) from CAL: log-odds -> a + b * log-odds."""
    q = min(1 - 1e-4, max(1e-4, p))
    return 1.0 / (1.0 + math.exp(-(cal[0] + cal[1] * math.log(q / (1 - q)))))


P_MAX = 0.99    # no chance shown or used above 99% (or below 1%): nothing is certain


def model_prob(values, line, floor, scale=1.0, cal=None):
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
    if cal:
        p = calibrate(p, cal)
    p = min(P_MAX, max(1 - P_MAX, p))      # never 100% (or 0%): the site's ceiling is 99%
    nq = neff + k
    z = MODEL["z"]
    z2 = z * z
    c = (p + z2 / (2 * nq)) / (1 + z2 / nq)
    hw = z * math.sqrt(p * (1 - p) / nq + z2 / (4 * nq * nq)) / (1 + z2 / nq)
    return {"over": p, "under": 1.0 - p, "push": push, "lo": min(P_MAX, max(1 - P_MAX, c - hw)), "hi": max(1 - P_MAX, min(P_MAX, c + hw)),
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


def _tokens(m, io_):
    """The over and under outcome tokens of a global-book market, for its CLOB book (depth.py)."""
    toks = _jsonish(m.get("clobTokenIds")) or []
    if io_ not in (0, 1) or len(toks) != 2:
        return {}
    return {"over": toks[io_], "under": toks[1 - io_]}


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
            "tradeable": tradeable, "tok": _tokens(m, io_)}


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


def pick_season(date_iso):
    """The season a game on this date belongs to. Picks used to take the season of the
    player's last game, which before his first game of a new season is last season's."""
    return season_year(datetime.date.fromisoformat(date_iso))


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
    st = (header.get("season") or {}).get("type")
    stype = "PST" if st == 3 else ("PRE" if st == 1 else "REG")
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
                if stype == "PRE":     # preseason = starters rest, backups play: skip, but remember
                    store.setdefault("pre", []).append([date_g, away, home])   # it to drop its picks
                    seen.add(gid)
                    continue
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
# Tonight's / upcoming slate (for the board) — started and completed games are left out.
# ---------------------------------------------------------------------------
# Matchups (frozenset of the two team codes) that ESPN shows as under way or over.
# No new pick is recorded for these, so none is ever made at an in-game price.
STARTED = set()
# Every game on the scoreboard, started or not, as (away, home, UTC start). Copied onto
# its picks by stamp_starts(), since the scoreboard only covers one day.
SB_GAMES = []
# Preseason matchups on the scoreboard (frozenset of the two team codes): no pick, board or market.
PRESEASON = set()
# The same games as [UTC date, away, home], so picks already made on them are removed.
PRE_GAMES = []


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
        cs = comp.get("competitors") or []
        home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
        away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
        if not home or not away:
            continue
        start = ev.get("date") or ""
        if start:
            SB_GAMES.append((away, home, start))
        if (ev.get("season") or {}).get("type") == 1:
            PRESEASON.add(frozenset((away, home)))
            PRE_GAMES.append([start[:10], away, home])
            continue
        if status.get("completed") or status.get("state", "pre") != "pre":
            STARTED.add(frozenset((away, home)))
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
        tm = ""
        m = re.search(r"T(\d{2}):(\d{2})", start)
        if m:
            hh = (int(m.group(1)) - 4) % 24    # UTC -> ET (in-season, ~UTC-4)
            tm = f"{hh:02d}:{m.group(2)}"
        games.append({"away": away, "home": home, "date": start[:10],
                      "time": tm, "start": start, "total": total, "spread": spread, "final": False})
    games.sort(key=lambda g: (g["date"], g["time"]))
    return games


def parse_utc(s):
    """ESPN's '2026-09-29T23:00Z' -> an aware UTC datetime, or None."""
    try:
        t = datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def stamp_starts(picks):
    """Save the scoreboard's start time on each pending pick for that game (same two
    teams, date within a day: a gid carries ESPN's UTC date or Polymarket's ET date)."""
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
    """True once the pick's game is under way or over. Picks saved before start times
    were kept fall back to their date: one dated before today (ET) has started."""
    t = parse_utc(p.get("start"))
    if t:
        return t <= datetime.datetime.now(datetime.timezone.utc)
    return (p.get("date") or "") < ET_TODAY


# A pick locks when its game starts within LOCK_MIN minutes. The site updates about every
# 10 minutes, so that's 20-30 minutes before the start; from then on its lists, chance and
# price stay as published, and no new picks are added for the game.
LOCK_MIN = 30


def game_locked(start):
    """True when a game starting at `start` (ESPN's UTC time) is inside the lock window."""
    t = parse_utc(start)
    return bool(t) and t <= datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=LOCK_MIN)


def pick_locked(p):
    """Locked or started: either way its lists, chance and price no longer change."""
    return bool(p.get("lk")) or pick_started(p)


def lock_picks(picks):
    """Lock every pending pick whose game starts within LOCK_MIN minutes, as published this
    run; "lk" records when (UTC). Returns how many locked."""
    now = datetime.datetime.now(datetime.timezone.utc)
    n = 0
    for p in picks:
        t = parse_utc(p.get("start"))
        if p.get("res") is None and not p.get("lk") and t and now < t <= now + datetime.timedelta(minutes=LOCK_MIN):
            p["lk"] = now.strftime("%Y-%m-%dT%H:%MZ")
            n += 1
    return n


def refresh_price(p, pm):
    """A pending pick whose game hasn't started keeps the market's current price for its
    side (None once that market stops being tradeable), like the other sports' pre-game
    refresh — so the price shown, and the one closing line value ends on, is current."""
    if p.get("res") is None and not pick_locked(p):
        px = (pm["over"] if p["side"] == "over" else pm["under"]) if pm.get("tradeable") else None
        p["pp"] = round(px, 3) if px is not None else None
        p["pd"] = pm.get("od" if p["side"] == "over" else "ud") if px is not None else None
        p["_pt"] = (pm.get("tok") or {}).get(p["side"]) if px is not None else None   # global book token (depth.verify)
        depth.choose(p)        # the cheaper of Polymarket and Kalshi with $25+ offered


def regular_minutes(rows):
    """{team: {pid: average minutes}} for each team's regulars going into its next game:
    players who played in 3+ of the team's last 5 games, averaging 20+ minutes in them
    (the definition the injury backtest used, see news.py)."""
    games = {}
    for r in rows:
        games.setdefault(r["team"], {}).setdefault(r["date"], {})[r["pid"]] = r.get("min") or 0
    out = {}
    for team, by in games.items():
        cnt, tot = {}, {}
        for d in sorted(by)[-5:]:
            for pid, m in by[d].items():
                if m > 0:
                    cnt[pid] = cnt.get(pid, 0) + 1
                    tot[pid] = tot.get(pid, 0) + m
        out[team] = {pid: tot[pid] / cnt[pid] for pid in cnt if cnt[pid] >= 3 and tot[pid] / cnt[pid] >= 20}
    return out


def news_test(picks, by_pid, rows):
    """TEST MODE (news.py): on every pending pick whose game hasn't started, record the
    player's status on ESPN's injury report and "om", the usual minutes of his team's
    regulars listed Out, plus p2: the chance with the backtest's boost for those minutes
    (points, assists, threes, PRA). Nothing here changes a pick's chance or its lists."""
    inj = news.espn_injuries("basketball/nba")
    if inj is None:
        return
    by_name = {pkey(p["n"]): pid for pid, p in by_pid.items()}
    status = {}
    for x in inj:
        pid = x["id"] if x["id"] in by_pid else by_name.get(pkey(x["name"]))
        if pid:
            status[pid] = x["status"]
    usual = regular_minutes(rows)
    n = boosted = 0
    for p in picks:
        if p.get("src") != "live" or p.get("res") is not None or pick_started(p):
            continue
        om = sum(m for q, m in usual.get(p["team"], {}).items() if q != p["pid"] and news.is_out(status.get(q)))
        nw = {"st": status.get(p["pid"]), "om": round(om, 1)}
        pl = by_pid.get(p["pid"])
        # p2 only on picks this model version made, so it differs from prob by the news alone
        if p["stat"] in news.NBA_OUT_STATS and pl and p.get("adj") is not None and p.get("mv") == MODEL_V:
            scale = min(CTX["clampHi"], max(CTX["clampLo"], p["adj"] * (1 + news.NBA_OUT_BOOST * om / 48.0)))
            mp = model_prob([stat_get(r, p["stat"]) for r in pl["g"]], p["line"], BW_FLOOR.get(p["stat"], 1.0),
                            scale, CAL.get(p["stat"]))
            if mp:
                nw["p2"] = round(mp[p["side"]], 3)
                boosted += om > 0
        p["nw"] = nw
        n += 1
    print(f"  news test: recorded on {n} pending pick(s), {boosted} with regular teammates listed Out")
    news.report(picks, "NBA injuries")


def note_price(p):
    """Closing line value: px0 keeps the first price a pick was recorded at and pxc the last
    one seen before its game started (price itself goes None whenever a market stops trading)."""
    if p.get("price") is not None:
        if p.get("px0") is None:
            p["px0"] = p["price"]
        p["pxc"] = p["price"]


def clv_stats(ps, cents=100):
    """How the price of the side taken moved from a pick's first recording (px0) to the last
    price before its game (pxc), in cents. The market moving toward a pick (it got pricier)
    is the usual sign of a real edge, and it shows up long before a win/loss record does."""
    mv = [round((p["pxc"] - p["px0"]) * cents, 1) for p in ps
          if p.get("px0") is not None and p.get("pxc") is not None]
    return {"clvN": len(mv), "clvUp": sum(1 for m in mv if m >= 1), "clvDn": sum(1 for m in mv if m <= -1),
            "clv": round(sum(mv) / len(mv), 1) if mv else None}


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
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj", "start",
             "sh",    # sh: chance with the minutes strength at MIN_TEST, for comparison
             "px0", "pxc",   # px0/pxc: first and last pre-game price (closing line value)
             "mv",           # model version the chance came from (MODEL_V)
             "nw",           # pre-game news, test mode (news.py): {"st", "om", "p2"}
             "lk",           # when the pick locked (UTC; see lock_picks)
             "pp", "kp",     # this side's price on Polymarket and on Kalshi (None = not listed there)
             "pd", "kd",     # dollars offered within 2c of each (depth.py)
             "vn",           # which one "price" is: the cheaper with $25+ offered, "P" Polymarket, "K" Kalshi
             "th",           # 1 = thin: neither has $25 offered near its price, so no Value
             "hd"]           # what it waits on: injury news not settled yet (holds.py), so no lists
BOARD_STATS = ["pts", "reb", "ast", "tpm", "pra"]
TOP_N = 25
VALUE_MIN_NEFF = 6.0
# Value rules mirror build.py (NFL) so every sport's lists mean the same.
VALUE_N = 200           # a safety cap only. At 50 it bound in busy weeks (NFL week 3: 27 picks that
                        # cleared the rule went unrecorded), so the record now holds every pick that clears it
VALUE_MIN_PRICE = 0.30  # the market has to give it at least 30%
VALUE_MIN_EDGE = 0.15   # and the model has to be 15+ points higher


TOP_VERIFY = 80         # the surest priced props whose order books are read for Top 25
T_MAX_GAP = 0.20        # Top 25 skips a prop the model is 20+ points above the market on (NFL record: such gaps were mostly misses)


def could_list(p, t_floor=1.01):
    """A pending pick that a price could put on Top 25 Surest (its chance is t_floor or more: among
    the TOP_VERIFY surest priced) or Value, but whose depth isn't yet known to be enough
    (depth.verify reads the full book for these)."""
    if p.get("res") is not None or pick_locked(p) or not p.get("th"):
        return False
    return any(px is not None and (p["prob"] >= t_floor or
                                   (p["neff"] >= VALUE_MIN_NEFF and value_qualifies(p["prob"], px)))
               for px in (p.get("pp"), p.get("kp")))


def value_qualifies(prob, price):
    """prob and price are fractions; price is what you'd pay for this side."""
    return price is not None and price >= VALUE_MIN_PRICE and prob - price >= VALUE_MIN_EDGE


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


def context_scale(hist_pts, game_pts, def_r, minutes=None, strength=None):
    """minutes is minutes_ratio(rows) or None; strength overrides CTX["minutes"] (the test)."""
    env = 1.0
    if hist_pts and game_pts and hist_pts > 0 and game_pts > 0:
        env *= (game_pts / hist_pts) ** CTX["betaPts"]
    dfs = def_r ** CTX["gamma"] if (def_r and def_r > 0) else 1.0
    scale = min(CTX["clampHi"], max(CTX["clampLo"], env * dfs))
    k = CTX["minutes"] if strength is None else strength
    if minutes and k:
        scale = min(CTX["clampHi"], max(CTX["clampLo"], scale * minutes ** k))
    return scale


def minutes_ratio(rows):
    """Mean minutes of the last 3 games over the usual (recency-weighted, half-life 6,
    last 10), clamped to [0.5, 1.6]; None with fewer than 5 games or under 5 usual
    minutes. A player who just moved into (or out of) the rotation shows it here before
    the box-score averages catch up. Mirrored in nba_template.html."""
    m = [g[11] for g in rows[-10:] if g[11] is not None]
    if len(m) < 5:
        return None
    w = [0.5 ** ((len(m) - 1 - k) / 6.0) for k in range(len(m))]
    usual = sum(a * b for a, b in zip(m, w)) / sum(w)
    if usual < 5:
        return None
    return max(0.5, min(1.6, (sum(m[-3:]) / 3.0) / usual))


def test_prob(vals, line, sk, side, hp, gpts, dr, rows):
    """The recorded side's chance with the minutes strength at MIN_TEST (the "sh" column)."""
    u = minutes_ratio(rows)
    if not u:
        return None
    mp = model_prob(vals, line, BW_FLOOR.get(sk, 1.0), context_scale(hp, gpts, dr, u, MIN_TEST), CAL.get(sk))
    return round(mp[side], 3) if mp else None


def minutes_test_report(picks):
    """How the live model and the MIN_TEST version compare on graded picks so far."""
    rows = [(p["prob"], p["sh"], 1 if p["res"] == "hit" else 0) for p in picks
            if p.get("src") == "live" and p.get("res") in ("hit", "miss") and p.get("sh") is not None]
    if not rows:
        return "no graded picks with a minutes-test chance yet"
    def ll(i):
        tot = 0.0
        for r in rows:
            q = min(0.999, max(0.001, r[i]))
            tot -= math.log(q) if r[2] else math.log(1 - q)
        return tot / len(rows)
    alt = f"minutes at {MIN_TEST}" if MIN_TEST else "without minutes"
    return f"{len(rows)} graded: log loss live {ll(0):.4f} vs {alt} {ll(1):.4f} (lower is better)"


def load_picks():
    try:
        with open(PICKS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    cols = d.get("cols") or []
    picks = [dict(zip(cols, row)) for row in d.get("picks", [])]
    for p in picks:      # season from the game's date (older picks took the player's last game's)
        try:
            p["season"] = pick_season(p["date"])
        except (TypeError, ValueError):
            pass
    return picks


def side_prob(mp):
    if mp["over"] >= 0.5:
        return "over", mp["over"], mp["lo"], mp["hi"]
    return "under", mp["under"], 1 - mp["hi"], 1 - mp["lo"]


def build_market_picks(picks, poly_games, players_by_key, espn_slate, defense, defavg):
    """Priced picks from Polymarket NBA markets, matched to players by name. Each
    is modeled at the market's line so Value spots can compare model vs price.
    Returns count added; no-op when there are no NBA markets (off-season)."""
    have = {(p["pid"], p["date"], p["stat"], p["line"]): p for p in picks}
    added = 0
    for g in poly_games:
        eg = next((x for x in espn_slate if {x["away"], x["home"]} == {g["away"], g["home"]}), None)
        if frozenset((g["away"], g["home"])) in STARTED | PRESEASON:
            continue            # started or over (its price is in-game, not pre-game), or preseason
        if eg is None and g["date"] < ET_TODAY:
            continue            # an earlier day's game (off today's scoreboard) — long started
        if eg and game_locked(eg.get("start")):
            continue            # locked: its picks stay as published
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
                refresh_price(have[key], pm)
                continue
            rows = pl["g"]
            hp = hist_context(rows)
            gpts = None
            if eg and eg.get("total") is not None:
                sp = eg.get("spread") if team == eg["home"] else (-(eg["spread"]) if eg.get("spread") is not None else None)
                gpts = eg["total"] / 2 + (sp / 2 if sp is not None else 0)
            dr = def_ratio(defense, defavg, opp, sk)
            scale = context_scale(hp, gpts, dr, minutes_ratio(rows))
            vals = [stat_get(r, sk) for r in rows]
            mp = model_prob(vals, pm["line"], BW_FLOOR.get(sk, 1.0), scale, CAL.get(sk))
            if not mp:
                continue
            side, prob, lo, hi = side_prob(mp)
            sh = test_prob(vals, pm["line"], sk, side, hp, gpts, dr, rows)
            price = (pm["over"] if side == "over" else pm["under"]) if pm.get("tradeable") else None
            picks.append({"src": "live", "gid": gid, "season": pick_season(g["date"]), "date": g["date"],
                          "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                          "stat": sk, "line": pm["line"], "side": side,
                          "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                          "neff": round(mp["neff"], 1), "price": round(price, 3) if price is not None else None,
                          "pp": round(price, 3) if price is not None else None, "vn": "P" if price is not None else None,
                          "lists": "", "rec": f"{sk} {side} {pm['line']}", "actual": None, "res": None,
                          "adj": round(scale, 3), "sh": sh, "mv": MODEL_V})
            refresh_price(picks[-1], pm)     # pp/pd for its side, then the cheaper exchange with enough money
            have[key] = picks[-1]
            added += 1
    return added


def build_board_picks(picks, slate, players_by_team, defense, defavg):
    """One pick per (player, board stat) for players on teams playing an upcoming
    game — the highest-confidence side. Deduped against already-recorded picks."""
    # Same game at any line, a day either way: market picks carry Polymarket's ET date, a
    # day before the ESPN (UTC) date used here for a late game; an exact-date match
    # recorded those twice (the NHL page showed it).
    have = {}
    for p in picks:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$", str(p.get("gid") or ""))
        if m:
            have.setdefault((p["pid"], p["stat"], m.group(2), m.group(3)), set()).add(m.group(1))

    def recorded(pid, sk, g):
        d = datetime.date.fromisoformat(g["date"])
        return any(abs((datetime.date.fromisoformat(x) - d).days) <= 1
                   for x in have.get((pid, sk, g["away"], g["home"]), ()))
    now_added = 0
    for g in slate:
        if g.get("final") or game_locked(g.get("start")):
            continue            # final, or locked: no new picks
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
                    if recorded(pl["id"], sk, g):
                        continue
                    vals = [stat_get(r, sk) for r in rows]
                    line = seed_line(vals)
                    dr = def_ratio(defense, defavg, opp, sk)
                    scale = context_scale(hp, gpts, dr, minutes_ratio(rows))
                    mp = model_prob(vals, line, BW_FLOOR.get(sk, 1.0), scale, CAL.get(sk))
                    if not mp or mp["neff"] < VALUE_MIN_NEFF:
                        continue
                    side, prob, lo, hi = side_prob(mp)
                    sh = test_prob(vals, line, sk, side, hp, gpts, dr, rows)
                    picks.append({"src": "live", "gid": gid, "season": pick_season(g["date"]), "date": g["date"],
                                  "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                                  "stat": sk, "line": line, "side": side,
                                  "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                                  "neff": round(mp["neff"], 1), "price": None, "lists": "",
                                  "rec": f"{sk} {side} {line}", "actual": None, "res": None,
                                  "adj": round(scale, 3), "sh": sh, "mv": MODEL_V})
                    have.setdefault((pl["id"], sk, g["away"], g["home"]), set()).add(g["date"])
                    now_added += 1
    return now_added


def box_games(rows):
    """Every game whose box score is in the store, as (ESPN UTC date, away, home)."""
    out = set()
    for r in rows:
        home, away = (r["team"], r["opp"]) if r.get("home") else (r["opp"], r["team"])
        out.add((r["date"], away, home))
    return out


def pick_box_game(p, games):
    """The pick's game as it sits in the store — (date, away, home) — or None until its
    box score is in. Store dates are ESPN's UTC date, and so are most gids, but a market
    pick recorded while its game wasn't on the ESPN scoreboard carries Polymarket's ET
    date, a day early for a late game. So try the saved start time first, then the gid
    date and the day either side of it."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$", p.get("gid") or "")
    if not m:
        return None
    gd, away, home = m.groups()
    try:
        d = datetime.date.fromisoformat(gd)
    except ValueError:
        return None
    one = datetime.timedelta(days=1)
    t = parse_utc(p.get("start"))
    dates = ([t.date().isoformat()] if t else []) + [gd, (d + one).isoformat(), (d - one).isoformat()]
    return next(((x, away, home) for x in dates if (x, away, home) in games), None)


def grade_picks(picks, by_pid, games):
    """Grade pending picks once their game's box score is in the store. A player with no
    row in that game didn't dress (scratched, hurt, or traded since last season — board
    picks use the player's last-season team), so the pick is voided as 'dnp', like NFL,
    rather than staying pending forever. Returns (graded, dnp)."""
    n = dnp = 0
    for p in picks:
        if p.get("res") is not None:
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


def injury_holds(picks, by_pid, rows):
    """Props that wait for injury news (holds.py): off Top 25 Surest and Value while the player,
    or a teammate in his position group with a real role, is day-to-day on ESPN's report, until
    ESPN rules him out or drops the tag. Groups: guards, forwards, centers (a G-F is both). A real
    role: 20+ minutes a game over his last 5 games for his team. ESPN unreachable: the last run's
    holds stand."""
    inj = news.espn_injuries("basketball/nba")
    if inj is None:
        print("  holds: ESPN injury report unavailable, last run's holds kept")
        return
    people = {pid: (p["n"], p["t"], p["p"]) for pid, p in by_pid.items()}
    report = holds.match(inj, people, pkey)
    last = holds.last_games(rows)

    def role(pid):
        g = last.get(pid, (None, []))[1]
        return bool(g) and sum(r.get("min") or 0 for r in g) / len(g) >= 20

    n = holds.apply(picks, report, people, lambda pos: {c for c in "GFC" if c in (pos or "").upper()}, role,
                    lambda p: p.get("res") is None and not pick_locked(p))
    print(f"  holds: {n} pending pick(s) waiting on injury news (no Top 25 / Value); "
          f"{sum(1 for s in report.values() if holds.status(s) == 'unsure')} player(s) day-to-day")


def assign_lists(picks):
    """Mirrors build.py (NFL). T = the 25 highest model chances you can bet ('Top 25 Surest'), one line per player-prop.
    V = 'Value' — the market prices it at 30c or more and the model puts it 15+ points
    higher, ranked by that edge. Prices are fractions here. Only picks whose game hasn't
    started or locked are (re)tagged: once it starts they keep the lists they had at tip-off until
    graded, so the live record by list counts exactly what the page showed pre-game."""
    pending = [p for p in picks if p.get("res") is None and not pick_locked(p)]
    # Locked picks keep their Top 25 slots until their game starts, so the board never shows more than 25.
    held = sum(1 for p in picks if p.get("res") is None and p.get("lk") and not pick_started(p)
               and "T" in (p.get("lists") or ""))
    for p in pending:
        p["lists"] = ""
    pending = [p for p in pending if not p.get("hd")]     # waiting on injury news (holds.py): no lists
    # The model's widest gap over the price on any rung of a player-prop (one side), as on the NFL
    # board: over T_MAX_GAP on one rung, it's likely missing something about him (a role change the
    # market already priced), so no rung of that prop makes Top 25.
    widest = {}
    for p in pending:
        if p.get("price") is not None:
            k = (p["gid"], p["pid"], p["stat"], p.get("side"))
            widest[k] = max(widest.get(k, -1.0), p["prob"] - p["price"])
    # Top 25: only props you can bet -- a live price with $25+ offered near it (depth.py; not
    # thin) -- one line per player-prop (its surest rung), none the model is that far off on
    ranked = sorted((p for p in pending if p["prob"] >= 0.5 and p.get("price") is not None and not p.get("th")
                     and widest[(p["gid"], p["pid"], p["stat"], p.get("side"))] <= T_MAX_GAP + 1e-9),
                    key=lambda p: (-p["prob"], -p["neff"]))
    seen = set()
    for p in ranked:
        k = (p["gid"], p["pid"], p["stat"])
        if k in seen:
            continue
        if len(seen) >= TOP_N - held:
            break
        seen.add(k)
        p["lists"] += "T"
    vals = [((p["prob"] - p["price"]), p) for p in pending
            if p.get("price") is not None and not p.get("th") and p["neff"] >= VALUE_MIN_NEFF
            and value_qualifies(p["prob"], p["price"])]
    vals.sort(key=lambda x: -x[0])
    for _, p in vals[:VALUE_N]:
        p["lists"] += "V"


def fit_temperature(picks):
    data = []
    for p in picks:      # only picks made by this model version: older ones had other errors
        if p.get("res") in ("hit", "miss") and p.get("prob") is not None and p.get("mv") == MODEL_V:
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
    graded = [p for p in picks if p.get("res") in ("hit", "miss")]
    for tag, r in out.items():
        r["units"] = round(r["units"], 2)
        r.update(clv_stats([p for p in graded if tag in (p.get("lists") or "")]))
    out["clv"] = clv_stats(graded)      # every graded pick, listed or not
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


def prune_store(store, cur_season):
    keep_seasons = {cur_season - i for i in range(CANDIDATE_SEASONS)}
    store["rows"] = [r for r in store["rows"] if r.get("season") in keep_seasons]
    store["pre"] = [g for g in store.get("pre", []) if pick_season(g[0]) in keep_seasons]


def purge_preseason(store):
    """One-time: drop preseason games stored as regular season before header_meta knew
    ESPN's preseason type. Each October game's box-score header is re-read; the store is
    marked done once every check succeeded, else the rest are retried next run. The
    dropped games go in store['pre'] so their picks are removed too. Returns games dropped."""
    if store.get("pre_purged"):
        return 0
    games = {}
    for r in store["rows"]:
        if r.get("date", "")[5:7] == "10":
            home, away = (r["team"], r["opp"]) if r.get("home") else (r["opp"], r["team"])
            games[r["gid"]] = [r["date"], away, home]

    def stype(gid):
        if over_budget():
            return None
        try:
            return header_meta(get_json(ESPN_CDN_BOX.format(gid=gid)).get("gamepackageJSON") or {})[4]
        except Exception as e:  # noqa: BLE001
            print(f"    preseason check {gid}: skipped ({e})")
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        types = dict(zip(games, ex.map(stype, games)))
    pre = {gid for gid, t in types.items() if t == "PRE"}
    store["rows"] = [r for r in store["rows"] if r["gid"] not in pre]
    store.setdefault("pre", []).extend(games[gid] for gid in sorted(pre))
    if all(types.values()):
        store["pre_purged"] = True
    return len(pre)


def drop_preseason_picks(picks, pre):
    """Remove picks recorded on preseason games (before preseason was skipped): same
    teams as a preseason game, within a day of the pick's gid date (market picks carry
    Polymarket's ET date). Returns how many were removed."""
    pre_games = {tuple(g) for g in pre}

    def on_pre(p):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$", p.get("gid") or "")
        if not m:
            return False
        d = datetime.date.fromisoformat(m.group(1))
        return any(((d + datetime.timedelta(days=k)).isoformat(), m.group(2), m.group(3)) in pre_games
                   for k in (-1, 0, 1))

    keep = [p for p in picks if not on_pre(p)]
    n = len(picks) - len(keep)
    picks[:] = keep
    return n


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
    try:
        purged = purge_preseason(store)
        if purged:
            print(f"  store: dropped {purged} preseason game(s) stored as regular season")
    except Exception as e:  # noqa: BLE001
        print(f"  preseason purge: skipped ({e})")
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
    dropped = drop_preseason_picks(picks, store.get("pre", []) + PRE_GAMES)
    if dropped:
        print(f"  picks: removed {dropped} pick(s) on preseason games")
    graded, dnp = grade_picks(picks, by_pid, box_games(store["rows"]))
    try:
        mkt_added = build_market_picks(picks, poly_games, players_by_key, slate, defense, defavg)
    except Exception as e:  # noqa: BLE001
        print(f"  market picks: skipped ({e})")
        mkt_added = 0
    added_picks = build_board_picks(picks, slate, players_by_team, defense, defavg)
    stamp_starts(picks)
    try:
        kalshi_mkts = kalshi.fetch("nba", days=3)
    except Exception as e:  # noqa: BLE001
        print(f"  kalshi: skipped ({e})")
        kalshi_mkts = None
    nk = kalshi.apply(picks, kalshi_mkts, pkey, lambda p: not pick_locked(p))
    print(f"  kalshi: {nk} pending pick(s) priced on Kalshi too")
    surest = sorted((p["prob"] for p in picks if p.get("res") is None and not pick_locked(p)
                     and p.get("price") is not None and not p.get("hd")), reverse=True)[:TOP_VERIFY]
    t_floor = max(0.5, surest[-1]) if len(surest) == TOP_VERIFY else 0.5
    nb = depth.verify(picks, lambda p: could_list(p, t_floor))
    thin = sum(1 for p in picks if p.get("res") is None and not pick_locked(p) and p.get("th"))
    print(f"  depth: read {nb} more order book(s); {thin} pending pick(s) too thin for Value "
          f"(under ${depth.MIN_USD:.0f} offered within 2c)")
    try:
        injury_holds(picks, by_pid, store["rows"])
    except Exception as e:  # noqa: BLE001
        print(f"  holds: skipped ({e})")
    assign_lists(picks)
    for p in picks:
        if p.get("res") is None and not pick_locked(p):
            note_price(p)
    locked = lock_picks(picks)
    if locked:
        print(f"  picks: locked {locked} pick(s) whose game starts within {LOCK_MIN} minutes")
    try:
        news_test(picks, by_pid, store["rows"])
    except Exception as e:  # noqa: BLE001
        print(f"  news test: step unavailable ({e})")
    if mkt_added:
        print(f"  market picks: +{mkt_added} priced (Polymarket)")
    print(f"  picks: graded {graded}, {dnp} DNP, added {added_picks} board pick(s)")
    try:
        print(f"  minutes test: {minutes_test_report(picks)}")
    except Exception as e:  # noqa: BLE001
        print(f"  minutes test: report skipped ({e})")
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

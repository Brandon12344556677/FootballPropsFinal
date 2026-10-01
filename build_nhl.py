#!/usr/bin/env python3
"""
Prop Streak Lab — NHL data builder (sibling of build.py / build_nba.py).

Pulls player box scores straight from ESPN's public hockey API and accumulates
them into a growing local store. Each run only fetches games it hasn't seen yet
— capped per run — so the store self-builds over a few nightly runs and then
stays cheap to keep current. Skaters carry goals/assists/points/shots/blocks/
hits; goalies carry saves.

Python 3 standard library only. Run: python build_nhl.py

Outputs
  nhl_stats.json  the raw accumulated player box-score rows (source of truth)
  nhl.json        the compact dataset the NHL page runs on
  nhl_picks.json  every NHL pick the site has made, graded as games finish
  nhl.html        nhl_template.html with nhl.json baked in (the NHL page)

The probability model here mirrors the block marked "MODEL" in nhl_template.html.
Change both or neither. Everything that touches the network is wrapped so a bad
ESPN response degrades to "no new data" instead of failing the build.
"""
import json, math, os, re, sys, time, datetime, unicodedata, urllib.request

TODAY = datetime.date.today()
ET_TODAY = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)).date().isoformat()
UA = {"User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}

# ESPN blocks site.api.espn.com from data-center IPs (Akamai 403), but two hosts
# still serve NBA data from CI: the core API (honors a date -> game ids) and the
# cdn "core" boxscore (full player stats by game id). The cdn scoreboard ignores
# the date param, so it's only used for the current/upcoming slate.
ESPN_CORE_EVENTS = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events?dates={date}&limit=100"
# The cdn core boxscore that works for NBA 404s for NHL, so use the web summary
# API (a different host than the Akamai-blocked site.api). Its boxscore/header sit
# at the top level rather than under gamepackageJSON.
ESPN_CDN_BOX = "https://site.web.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={gid}"
ESPN_CDN_SB = "https://site.web.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"

# Polymarket NHL player-prop markets (auto-activates when the season posts them;
# off-season it simply finds nothing and the board stays model-only). Mirrors the
# NFL setup in build.py. The exact NHL slug/team format can only be confirmed once
# markets exist, so team matching accepts abbreviations, cities, or nicknames.
POLY_SLATE = ("https://gamma-api.polymarket.com/events"
              "?closed=false&tag_slug=nhl&limit=500&order=startDate&ascending=false")
POLY_EVENT = "https://gamma-api.polymarket.com/events/slug/{slug}"
POLY_SLUG = re.compile(r"^nhl-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})-player-props$")
Q_RE = re.compile(r"^(.*?):\s*(.+?)\s+O/U\s+([\d.]+)", re.I)
# Market question text -> our stat key. Order matters: "blocked shots" must be
# checked before the bare \bshots?\b in the shots-on-goal pattern, and power-play
# props map to None (skipped) so they aren't modeled as total points.
MKT_STAT_NHL = [
    (re.compile(r"power\s*play", re.I), None),
    (re.compile(r"blocked\s*shots?|\bblocks?\b", re.I), "blk"),
    (re.compile(r"shots?\s*on\s*goal|\bsog\b|\bshots?\b", re.I), "sog"),
    (re.compile(r"\bhits?\b", re.I), "hit"),
    (re.compile(r"\bsaves?\b", re.I), "sv"),
    (re.compile(r"\bassists?\b", re.I), "a"),
    (re.compile(r"\bgoals?\b", re.I), "g"),
    (re.compile(r"\bpoints?\b", re.I), "pts"),
]
# Team nickname / city -> ESPN abbreviation, so Polymarket slugs match ESPN games
# whether they use "oilers", "edmonton", or "edm".
NHL_TEAMS = {
    "ducks": "ANA", "anaheim": "ANA", "bruins": "BOS", "boston": "BOS",
    "sabres": "BUF", "buffalo": "BUF", "flames": "CGY", "calgary": "CGY",
    "hurricanes": "CAR", "canes": "CAR", "carolina": "CAR", "blackhawks": "CHI", "chicago": "CHI",
    "avalanche": "COL", "avs": "COL", "colorado": "COL", "bluejackets": "CBJ", "columbus": "CBJ",
    "stars": "DAL", "dallas": "DAL", "redwings": "DET", "detroit": "DET",
    "oilers": "EDM", "edmonton": "EDM", "panthers": "FLA", "florida": "FLA",
    "kings": "LA", "losangeles": "LA", "wild": "MIN", "minnesota": "MIN",
    "canadiens": "MTL", "habs": "MTL", "montreal": "MTL", "predators": "NSH", "preds": "NSH", "nashville": "NSH",
    "devils": "NJ", "newjersey": "NJ", "islanders": "NYI", "isles": "NYI",
    "rangers": "NYR", "newyork": "NYR", "senators": "OTT", "sens": "OTT", "ottawa": "OTT",
    "flyers": "PHI", "philadelphia": "PHI", "penguins": "PIT", "pens": "PIT", "pittsburgh": "PIT",
    "sharks": "SJ", "sanjose": "SJ", "kraken": "SEA", "seattle": "SEA",
    "blues": "STL", "stlouis": "STL", "lightning": "TB", "bolts": "TB", "tampabay": "TB", "tampa": "TB",
    "mapleleafs": "TOR", "leafs": "TOR", "toronto": "TOR", "utah": "UTAH", "mammoth": "UTAH", "hockeyclub": "UTAH",
    "canucks": "VAN", "vancouver": "VAN", "goldenknights": "VGK", "knights": "VGK", "vegas": "VGK", "lasvegas": "VGK",
    "capitals": "WSH", "caps": "WSH", "washington": "WSH", "jets": "WPG", "winnipeg": "WPG",
    # Polymarket's own slug codes that differ from ESPN's (seen 2026-09-28)
    "cal": "CGY", "lak": "LA", "las": "VGK", "mon": "MTL",
    "veg": "VGK", "nas": "NSH",     # Polymarket US codes
}
# ESPN abbreviation -> Polymarket slug code (lowercase ESPN code unless listed).
POLY_CODE = {"CGY": "cal", "LA": "lak", "VGK": "las", "MTL": "mon"}


def poly_team(tok):
    tok = (tok or "").lower()
    return NHL_TEAMS.get(tok, tok.upper())

STATS_FILE = "nhl_stats.json"
PICKS_FILE = "nhl_picks.json"
DATA_FILE = "nhl.json"
TEMPLATE = "nhl_template.html"
PAGE = "nhl.html"

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
# Row layout — the NHL page reads game rows by index. Keep in sync with
# nhl_template.html.
#   0 season  1 date(YYYY-MM-DD)  2 opp  3 type(REG/PST)
#   4 pts(G+A) 5 g(goals) 6 a(assists) 7 sog(shots on goal) 8 blk(blocked shots)
#   9 hit 10 sv(goalie saves) 11 toi(minutes)  12 home(1/0)  13 started(1/0)
#   14 game total (Vegas, or null)  15 team spread (+ = favored, or null)
# ---------------------------------------------------------------------------
STAT_ORDER = ["pts", "g", "a", "sog", "blk", "hit", "sv", "toi"]

# ---------------------------------------------------------------------------
# MODEL — mirrored in nhl_template.html (block marked MODEL). Keep identical.
# Same weighted-KDE-over-recent-values engine as the NFL/NBA model; every NHL
# stat is a count on its own scale, so the smoothing floor is per-stat.
# ---------------------------------------------------------------------------
# Walk-forward backtest on the 2025-26 box scores (46,659 skater games per stat, each
# predicted from earlier games only, scored on odd and on even days separately): a long
# memory beat the old 20 games / half-life 6 on every stat and both halves, and the old
# smoothing floors (0.5-0.6 for points, goals, assists) leaked chance across a 0.5 line,
# so a 15% goal scorer read 27%. With these, log loss: goals 0.455 -> 0.410, assists
# 0.558 -> 0.536, points 0.626 -> 0.609, shots 0.583 -> 0.577.
MODEL = {"halfLife": 30.0, "maxGames": 82, "priorK": 0.5, "bwConst": 0.9, "z": 1.2816}
MODEL_V = 2   # recorded on every pick ("mv"); calibration fits only this version's picks
# Minimum smoothing bandwidth per stat. Blocks/hits/saves/TOI weren't refitted.
BW_FLOOR = {"pts": 0.3, "g": 0.25, "a": 0.3, "sog": 1.0, "blk": 0.7, "hit": 1.0,
            "sv": 4.0, "toi": 3.0}
# Game-context adjustment: the player's distribution is scaled by
# (this game's implied team goals / their usual implied goals)^betaPts times
# (opponent's allowed-per-game / league average)^gamma. Clamped. For points, goals and
# assists also (recent ice time / usual)^toi (toi_ratio) and (1 + b2b) on the second
# night of a back-to-back: both small (log loss -0.0002 to -0.0005) but better on both
# halves; teams scored 4.9% fewer goals on back-to-backs last season.
CTX = {"betaPts": 0.30, "gamma": 0.45, "toi": 0.5, "b2b": -0.05, "clampLo": 0.6, "clampHi": 1.6}
USAGE_STATS = ("pts", "g", "a")

# Per-stat calibration, fitted on the same walk-forward backtest: the chance's log-odds become
# a + b * log-odds. It removes a bias the smoothing leaves (most props read overs a few points
# high) and fixes over/under-confidence. Fitted at the seeded line and a line either side on
# one half of the data and scored on the other, both ways; only stats where that improved
# both halves are listed (the rest are left as they were).
CAL = {"pts": (-0.226, 0.921), "g": (-0.37, 0.934), "a": (-0.321, 0.928), "sog": (-0.123, 1.24)}


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
    for rx, k in MKT_STAT_NHL:
        if rx.search(txt or ""):
            return k
    return None


def toi_min(v):
    """ESPN time-on-ice 'MM:SS' -> minutes as a float; passthrough for numbers."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if ":" in s:
        try:
            m, sec = s.split(":")[:2]
            return round(int(m) + int(sec) / 60.0, 1)
        except (ValueError, TypeError):
            return 0.0
    return num(s)


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


def fetch_markets(slate=None):
    """Polymarket NHL player-prop events in a [-1,+10] day window, with markets.
    Also probes each ESPN slate game's slug directly (the listing is capped and
    sorted newest-first, so near-term games can fall off it). Non-fatal."""
    try:
        events = json.loads(http_get(POLY_SLATE))
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket: listing skipped ({e})")
        events = []
    if not isinstance(events, list):
        events = []
    listed = {ev.get("slug", "") for ev in events if isinstance(ev, dict)}
    for g in slate or []:
        a = POLY_CODE.get(g["away"], g["away"].lower())
        h = POLY_CODE.get(g["home"], g["home"].lower())
        slug = f"nhl-{a}-{h}-{g['date']}-player-props"
        if slug in listed:
            continue
        try:
            ev = json.loads(http_get(POLY_EVENT.format(slug=slug), tries=1))
            if isinstance(ev, dict) and ev.get("slug") == slug:
                events.append(ev)
        except Exception:  # noqa: BLE001 — 404 until Polymarket posts that game's props
            pass
    games = []
    for ev in events:
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
        print("  polymarket: no NHL player-prop events yet (off-season or format differs)")
        return []
    print(f"  polymarket: {len(games)} NHL player-prop event(s)")
    for g in games:
        try:
            g["markets"] = json.loads(http_get(POLY_EVENT.format(slug=g["slug"]))).get("markets", [])
        except Exception as e:  # noqa: BLE001
            print(f"    event {g['slug']}: skipped ({e})")
            g["markets"] = []
    return games


# Polymarket US (the CFTC exchange at polymarket.us) has its own public gateway (no
# key, 20 req/s per IP). Its NHL player props are "at least N" ladders — "Sam
# Reinhart 2+ points" = over 1.5 — and live prices come from each market's BBO.
POLYUS_EVENTS = ("https://gateway.polymarket.us/v1/events?tagSlug=nhl&active=true&closed=false"
                 "&startDateMin={a}T00:00:00Z&startDateMax={b}T00:00:00Z&limit=100")
POLYUS_EVENT = "https://gateway.polymarket.us/v1/events/slug/{slug}"
POLYUS_BBO = "https://gateway.polymarket.us/v1/markets/{slug}/bbo"
US_SLUG = re.compile(r"^nhl-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})$")
US_TITLE = re.compile(r"^(.*?)\s+(\d+)\+\s")
US_MAX_N = 3            # price the 1+/2+/3+ rungs; higher ones are long shots


def _px(v):
    return fnum(v.get("value")) if isinstance(v, dict) else None


def fetch_markets_us(players_by_key):
    """Polymarket US NHL player props for games in [-1,+3] days, shaped like
    fetch_markets() output but with each market already parsed (key 'pm').
    Only players we model are priced, to keep the BBO calls down. Non-fatal."""
    a = (TODAY - datetime.timedelta(days=1)).isoformat()
    b = (TODAY + datetime.timedelta(days=4)).isoformat()
    try:
        data = json.loads(http_get(POLYUS_EVENTS.format(a=a, b=b), timeout=60))
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket US: skipped ({e})")
        return []
    events = (data.get("events") if isinstance(data, dict) else None) or []
    games, todo = [], []
    for ev in events:
        m = US_SLUG.match(ev.get("slug", "") or "")
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(3))
        except ValueError:
            continue
        if not (TODAY - datetime.timedelta(days=1) <= d <= TODAY + datetime.timedelta(days=3)):
            continue
        mkts = ev.get("markets")
        if mkts is None:
            try:
                mkts = (json.loads(http_get(POLYUS_EVENT.format(slug=ev["slug"]))).get("event") or {}).get("markets")
            except Exception:  # noqa: BLE001
                mkts = []
        g = {"slug": ev["slug"], "away": poly_team(m.group(1)), "home": poly_team(m.group(2)),
             "date": m.group(3), "markets": []}
        for mk in mkts or []:
            smt = mk.get("sportsMarketType") or ""
            if "_player_" not in smt or mk.get("closed"):
                continue
            stat_text = smt.split("_player_", 1)[1].replace("_", " ")
            tm = US_TITLE.match(mk.get("title") or "")
            n = fnum(mk.get("line"))
            if not mkt_stat_key(stat_text) or not tm or n is None or n > US_MAX_N:
                continue
            pl = players_by_key.get(pkey(tm.group(1)))
            if not pl or len(pl["g"]) < 5:
                continue
            todo.append((g, mk.get("slug"), tm.group(1).strip(), stat_text, n - 0.5))
        games.append(g)

    def bbo(item):
        time.sleep(0.35)          # 6 workers x ~3/s stays under the 20 req/s limit
        try:
            return item, json.loads(http_get(POLYUS_BBO.format(slug=item[1]))).get("marketData") or {}
        except Exception:  # noqa: BLE001
            return item, None

    def ok(p):
        return p is not None and 0.02 < p < 0.98

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:
        for (g, _slug, name, stat_text, line), md in ex.map(bbo, todo):
            if not md:
                continue
            ask, bid = _px(md.get("bestAsk")), _px(md.get("bestBid"))
            over = ask if ok(ask) else None                     # buy Yes = over
            under = (1 - bid) if bid is not None and ok(1 - bid) else None   # buy No = under
            spread = (ask - bid) if ask is not None and bid is not None else None
            tradeable = (over is not None or under is not None) and (spread is None or spread <= 0.15)
            g["markets"].append({"pm": {"player": name, "statText": stat_text, "line": line,
                                        "over": over, "under": under, "tradeable": tradeable}})
    games = [g for g in games if g["markets"]]
    print(f"  polymarket US: {len(games)} NHL game(s), {sum(len(g['markets']) for g in games)} priced player props")
    return games


def season_year(d):
    """NBA season label = the calendar year the season tipped off (Oct)."""
    return d.year if d.month >= 9 else d.year - 1


# ---------------------------------------------------------------------------
# ESPN scoreboard + box scores
# ---------------------------------------------------------------------------
def scan_dates(season):
    """Every date (newest first) in the NBA window for a season (the tip-off year)."""
    start = datetime.date(season, 9, 15)   # 2026-27 opened Sep 29; preseason games are skipped
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
    """One cdn boxscore dict -> stat row dicts for every player who logged ice time.
    Each ESPN statistics group carries its own `keys` (e.g. 'goals','shotsTotal',
    'saves') aligned to the athlete `stats` array; goalies are the group with
    'saves'. Read by key (fall back to the short label) so the mapping is exact."""
    rows = []
    for tb in (box or {}).get("players") or []:
        team = team_code((tb.get("team") or {}).get("abbreviation"))
        opp = away if team == home else home
        for cat in tb.get("statistics") or []:
            keys = [str(k) for k in (cat.get("keys") or [])]
            labels = [str(l).upper() for l in (cat.get("labels") or [])]
            is_goalie = "saves" in keys or "SV" in labels
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
                d = {}
                for i in range(len(st)):
                    if i < len(keys):
                        d[keys[i]] = st[i]
                    if i < len(labels):
                        d[labels[i]] = st[i]
                toi = toi_min(d.get("timeOnIce", d.get("TOI")))
                if is_goalie:
                    g = a = sog = blk = hit = 0.0
                    sv = num(d.get("saves", d.get("SV")))
                    pos = "G"
                else:
                    g = num(d.get("goals", d.get("G")))
                    a = num(d.get("assists", d.get("A")))
                    sog = num(d.get("shotsTotal", d.get("S")))
                    blk = num(d.get("blockedShots", d.get("BS")))
                    hit = num(d.get("hits", d.get("HT")))
                    sv = 0.0
                    pos = ((info.get("position") or {}).get("abbreviation") or "").upper() or "NHL"
                # A skater with no ice time and an empty line is a healthy scratch.
                if not is_goalie and toi == 0 and (g + a + sog + blk + hit) == 0:
                    continue
                rows.append({
                    "pid": pid, "name": disp, "pos": pos, "team": team, "opp": opp,
                    "season": season, "date": date_iso, "type": stype,
                    "home": 1 if team == home else 0,
                    "started": 1 if toi > 0 else 0,
                    "pts": g + a, "g": g, "a": a, "sog": sog, "blk": blk, "hit": hit,
                    "sv": sv, "toi": toi,
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
                gpj = bx.get("gamepackageJSON") or bx    # summary API puts these at top level
                completed, home, away, date_g, stype = header_meta(gpj)
                if not completed:
                    complete_date = False        # a game that day isn't final yet
                    continue
                if not home or not away or stype == "PRE":   # preseason = backups; skip
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
# Tonight's / upcoming slate (for the board) — started and completed games are left out.
# ---------------------------------------------------------------------------
# Matchups (frozenset of the two team codes) that ESPN shows as under way or over.
# No new pick is recorded for these, so none is ever made at an in-game price.
STARTED = set()
# Every game on the scoreboard, started or not, as (away, home, UTC start). Copied onto
# its picks by stamp_starts(), since the scoreboard only covers one day.
SB_GAMES = []


def fetch_slate():
    """The current/upcoming board (the cdn scoreboard returns today's games; it
    ignores a date param, which is fine — the NBA page shows tonight's slate)."""
    games = []
    try:
        sb = get_json(ESPN_CDN_SB)
    except Exception as e:  # noqa: BLE001
        print(f"    slate: skipped ({e})")
        return games
    # site.web.api returns events at the top level; the cdn format wrapped them in content.sbData
    events = sb.get("events") or ((sb.get("content") or {}).get("sbData") or {}).get("events", []) or []
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


# ---------------------------------------------------------------------------
# Build players / defense from the accumulated store
# ---------------------------------------------------------------------------
def build_players(rows):
    by = {}
    for r in rows:
        total = r.get("total")
        spr = r.get("spread")
        game = [r["season"], r["date"], r["opp"], r["type"],
                r["pts"], r["g"], r["a"], r["sog"], r["blk"], r["hit"], r["sv"], r["toi"],
                r["home"], r.get("started", 0), total, spr]
        p = by.setdefault(r["pid"], {"rows": [], "meta": r})
        p["rows"].append(game)
        p["meta"] = r
    out = []
    for pid, p in by.items():
        games = sorted(p["rows"], key=lambda g: (g[0], g[1]))
        meta = p["meta"]
        out.append({"id": pid, "n": meta["name"], "p": meta.get("pos") or "NHL",
                    "t": meta["team"], "g": games})
    out.sort(key=lambda x: x["n"])
    return out


DEF_STATS = ["pts", "g", "sog"]


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
            defense.setdefault(t, {}).setdefault("NHL", {})[sk] = {"a": round(v, 1), "r": i + 1, "n": len(vals)}
        avg[sk] = round(sum(v for _, v in vals) / len(vals), 2)
    return defense, {"NHL": avg}, gmax


# defense proxy stat for each prop key (opponent's allowed-per-game). Saves/hits/
# blocks aren't a clean "allowed" quantity, so they take no matchup adjustment.
DEF_FOR = {"pts": "pts", "g": "g", "a": "pts", "sog": "sog", "ppp": "pts",
           "blk": None, "hit": None, "sv": None, "toi": None}


def def_ratio(defense, defavg, opp, sk):
    ds = DEF_FOR.get(sk)
    if not ds or not opp:
        return None
    t = defense.get(opp, {}).get("NHL", {})
    a = t.get(ds, {}).get("a")
    L = defavg.get("NHL", {}).get(ds)
    return (a / L) if (a is not None and L) else None


# ---------------------------------------------------------------------------
# Picks (board + grading + calibration)
# ---------------------------------------------------------------------------
PICK_COLS = ["src", "gid", "season", "date", "pid", "player", "pos", "team", "opp",
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj", "start",
             "px0", "pxc",   # px0/pxc: first and last pre-game price (closing line value)
             "mv"]           # model version the chance came from (MODEL_V)
BOARD_STATS = ["pts", "sog", "g"]
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


def stat_get(row, sk):
    idx = {"pts": 4, "g": 5, "a": 6, "sog": 7, "blk": 8, "hit": 9, "sv": 10, "toi": 11}
    return row[idx[sk]] if sk in idx else 0


def hist_context(rows):
    r = rows[-MODEL["maxGames"]:]
    n = len(r)
    sp = wp = 0.0
    for i, g in enumerate(r):
        tot, spr = g[14], g[15]
        if tot is None or spr is None:
            continue
        w = 0.5 ** ((n - 1 - i) / MODEL["halfLife"])
        sp += w * (tot / 2 + spr / 2)
        wp += w
    return sp / wp if wp else None


def context_scale(hist_pts, game_pts, def_r, toi=None, b2b=False):
    """toi is toi_ratio(rows) or None; b2b is True on the second night of a back-to-back.
    Pass both only for USAGE_STATS (see usage_args)."""
    env = 1.0
    if hist_pts and game_pts and hist_pts > 0 and game_pts > 0:
        env *= (game_pts / hist_pts) ** CTX["betaPts"]
    dfs = def_r ** CTX["gamma"] if (def_r and def_r > 0) else 1.0
    scale = min(CTX["clampHi"], max(CTX["clampLo"], env * dfs))
    if toi:
        scale = min(CTX["clampHi"], max(CTX["clampLo"], scale * toi ** CTX["toi"]))
    if b2b:
        scale = min(CTX["clampHi"], max(CTX["clampLo"], scale * (1 + CTX["b2b"])))
    return scale


def toi_ratio(rows):
    """Ice time of the last 2 games over the usual (recency-weighted, half-life 6, last 10),
    clamped to [0.5, 1.6]; None with fewer than 4 games or under 3 usual minutes. A skater
    moved up or down the lineup shows it in his minutes before his points catch up.
    Mirrored in nhl_template.html."""
    t = [r[11] or 0 for r in rows[-10:]]
    if len(t) < 4:
        return None
    w = [0.5 ** ((len(t) - 1 - k) / 6.0) for k in range(len(t))]
    usual = sum(a * b for a, b in zip(t, w)) / sum(w)
    if usual <= 3:
        return None
    return max(0.5, min(1.6, (t[-1] + t[-2]) / 2.0 / usual))


def usage_args(rows, sk, date_iso):
    """(toi, b2b) for context_scale: ice-time ratio and whether the player's last game was
    the day before this one. Neither applies to shots, blocks, hits or saves."""
    if sk not in USAGE_STATS or not rows:
        return None, False
    try:
        rest = (datetime.date.fromisoformat(date_iso) - datetime.date.fromisoformat(rows[-1][1])).days
    except (TypeError, ValueError):
        rest = None
    return toi_ratio(rows), rest is not None and 0 <= rest <= 1   # 0: a UTC date against an ET one


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


def refresh_price(p, pm):
    """A pending pick whose game hasn't started keeps the market's current price for its
    side (None once that market stops being tradeable), like NFL's pre-kickoff refresh —
    so "has a live market" for Top 25 Surest means now, not when the pick was recorded."""
    if p.get("res") is None and not pick_started(p):
        px = (pm["over"] if p["side"] == "over" else pm["under"]) if pm.get("tradeable") else None
        p["price"] = round(px, 3) if px is not None else None


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


GID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([A-Z]+)-([A-Z]+)$")


def same_game_index(picks):
    """{(pid, stat, line, away, home): [(date, pick), ...]} for finding a pick already
    recorded for the same game. The date in a gid can be Polymarket's ET date (recorded
    before ESPN listed the game) or ESPN's UTC date (after), a day apart for a late game,
    so matching allows a day either way."""
    out = {}
    for p in picks:
        m = GID_RE.match(str(p.get("gid") or ""))
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        out.setdefault((p["pid"], p["stat"], p["line"], m.group(2), m.group(3)), []).append((d, p))
    return out


def find_same_game(index, pid, sk, line, away, home, date_iso):
    d = datetime.date.fromisoformat(date_iso)
    return next((p for dd, p in index.get((pid, sk, line, away, home), []) if abs((dd - d).days) <= 1), None)


def drop_same_game_duplicates(picks):
    """Remove pending picks recorded twice for one game (once under each date), keeping the
    one whose gid date is the game's UTC date (ESPN's, as the store uses), else the newest.
    Graded picks are never touched. Returns how many were dropped."""
    drop = set()
    for group in same_game_index(p for p in picks if p.get("src") == "live" and p.get("res") is None).values():
        group.sort(key=lambda x: x[0])
        i = 0
        while i < len(group):
            j = i
            while j + 1 < len(group) and (group[j + 1][0] - group[i][0]).days <= 1:
                j += 1
            if j > i:
                run = [p for _, p in group[i:j + 1]]
                t = parse_utc(run[0].get("start"))
                utc = t.date().isoformat() if t else None
                keep = next((p for p in run if utc and p["gid"].startswith(utc)), run[-1])
                drop.update(id(p) for p in run if p is not keep)
            i = j + 1
    if drop:
        picks[:] = [p for p in picks if id(p) not in drop]
    return len(drop)


def build_market_picks(picks, poly_games, players_by_key, espn_slate, defense, defavg):
    """Priced picks from Polymarket NBA markets, matched to players by name. Each
    is modeled at the market's line so Value spots can compare model vs price.
    Returns count added; no-op when there are no NBA markets (off-season)."""
    have = same_game_index(picks)
    added = 0
    for g in poly_games:
        eg = next((x for x in espn_slate if {x["away"], x["home"]} == {g["away"], g["home"]}), None)
        if frozenset((g["away"], g["home"])) in STARTED:
            continue            # already started or over: its price is in-game, not pre-game
        if eg is None and g["date"] < ET_TODAY:
            continue            # an earlier day's game (off today's scoreboard) — long started
        # grade against ESPN's (UTC) date — slugs use the ET date, which differs for late games
        date = eg["date"] if eg else g["date"]
        gid = f"{date}-{g['away']}-{g['home']}"
        for m in g.get("markets", []):
            pm = m.get("pm") or parse_market(m)     # Polymarket US markets arrive pre-parsed
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
            ex = find_same_game(have, pl["id"], sk, pm["line"], g["away"], g["home"], date)
            if ex is not None:
                refresh_price(ex, pm)
                continue
            rows = pl["g"]
            hp = hist_context(rows)
            gpts = None
            if eg and eg.get("total") is not None:
                sp = eg.get("spread") if team == eg["home"] else (-(eg["spread"]) if eg.get("spread") is not None else None)
                gpts = eg["total"] / 2 + (sp / 2 if sp is not None else 0)
            dr = def_ratio(defense, defavg, opp, sk)
            scale = context_scale(hp, gpts, dr, *usage_args(rows, sk, date))
            vals = [stat_get(r, sk) for r in rows]
            mp = model_prob(vals, pm["line"], BW_FLOOR.get(sk, 1.0), scale, CAL.get(sk))
            if not mp:
                continue
            side, prob, lo, hi = side_prob(mp)
            price = (pm["over"] if side == "over" else pm["under"]) if pm.get("tradeable") else None
            picks.append({"src": "live", "gid": gid, "season": rows[-1][0], "date": date,
                          "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                          "stat": sk, "line": pm["line"], "side": side,
                          "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                          "neff": round(mp["neff"], 1), "price": round(price, 3) if price is not None else None,
                          "lists": "", "rec": f"{sk} {side} {pm['line']}", "actual": None, "res": None,
                          "adj": round(scale, 3), "mv": MODEL_V})
            have.setdefault((pl["id"], sk, pm["line"], g["away"], g["home"]), []).append(
                (datetime.date.fromisoformat(date), picks[-1]))
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
                if pl.get("p") == "G":      # goalies aren't scored on the skater board
                    continue
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
                    scale = context_scale(hp, gpts, dr, *usage_args(rows, sk, g["date"]))
                    mp = model_prob(vals, line, BW_FLOOR.get(sk, 1.0), scale, CAL.get(sk))
                    if not mp or mp["neff"] < VALUE_MIN_NEFF:
                        continue
                    side, prob, lo, hi = side_prob(mp)
                    picks.append({"src": "live", "gid": gid, "season": rows[-1][0], "date": g["date"],
                                  "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": team, "opp": opp,
                                  "stat": sk, "line": line, "side": side,
                                  "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                                  "neff": round(mp["neff"], 1), "price": None, "lists": "",
                                  "rec": f"{sk} {side} {line}", "actual": None, "res": None,
                                  "adj": round(scale, 3), "mv": MODEL_V})
                    have.add((pl["id"], g["date"], sk))
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


def assign_lists(picks):
    """T = 'Top 25 Surest': up to 25 props the model gives 90%+ that have a live
    Polymarket price, best line per player-prop, ranked by model chance (so a thin slate
    shows fewer, or none). V = 'Value' — the market prices it at 30c or more and the
    model puts it 15+ points higher, ranked by that edge. Prices are fractions here. Only
    picks whose game hasn't started are (re)tagged: once it starts they keep the lists
    they had at puck drop until graded, so the live record by list counts exactly what
    the page showed pre-game."""
    pending = [p for p in picks if p.get("res") is None and not pick_started(p)]
    for p in pending:
        p["lists"] = ""
    ranked = sorted((p for p in pending if p["prob"] >= T_MIN_PROB and p.get("price") is not None),
                    key=lambda p: (-p["prob"], -p["neff"]))
    seen, top = set(), []     # Polymarket US lists 1+/2+/3+ ladders: keep one rung per player-prop
    for p in ranked:
        k = (p["pid"], p["stat"], p["gid"])
        if k not in seen:
            seen.add(k)
            top.append(p)
    for p in top[:TOP_N]:
        p["lists"] += "T"
    vals = [((p["prob"] - p["price"]), p) for p in pending
            if p.get("price") is not None and p["neff"] >= VALUE_MIN_NEFF
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


def _keys(d):
    return list(d.keys()) if isinstance(d, dict) else f"<{type(d).__name__}>"


def _cdn_events(dstr):
    sb = get_json(f"https://cdn.espn.com/core/nhl/scoreboard?xhr=1&dates={dstr}")
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
        core = get_json("https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events?dates=20251225")
        items = core.get("items", [])
        print(f"    CORE events dates=20251225: count={core.get('count')} items={len(items)}")
        ref = (items[0] or {}).get("$ref", "") if items else ""
        gid = re.search(r"/events/(\d+)", ref)
        gid = gid.group(1) if gid else None
        print(f"    CORE first event id={gid} ref={ref[:80]}")
        if gid:
            bx = get_json(f"https://cdn.espn.com/core/nhl/boxscore?xhr=1&gameId={gid}")
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
    print(f"NHL build — season {cur_season}, {TODAY.isoformat()}")
    if os.environ.get("NHL_PROBE"):
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
        poly_games = fetch_markets(slate)
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket: skipped ({e})")
        poly_games = []
    try:
        poly_games += fetch_markets_us(players_by_key)
    except Exception as e:  # noqa: BLE001
        print(f"  polymarket US: skipped ({e})")

    picks = load_picks()
    dup = drop_same_game_duplicates(picks)
    if dup:
        print(f"  picks: dropped {dup} duplicate pick(s) recorded twice for one game")
    graded, dnp = grade_picks(picks, by_pid, box_games(store["rows"]))
    try:
        mkt_added = build_market_picks(picks, poly_games, players_by_key, slate, defense, defavg)
    except Exception as e:  # noqa: BLE001
        print(f"  market picks: skipped ({e})")
        mkt_added = 0
    added_picks = build_board_picks(picks, slate, players_by_team, defense, defavg)
    stamp_starts(picks)
    assign_lists(picks)
    for p in picks:
        if p.get("res") is None and not pick_started(p):
            note_price(p)
    if mkt_added:
        print(f"  market picks: +{mkt_added} priced (Polymarket)")
    print(f"  picks: graded {graded}, {dnp} DNP, added {added_picks} board pick(s)")
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
        "sport": "nhl",
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
        if "__NHLDATA__" not in template:
            print(f"  WARNING: {TEMPLATE} missing __NHLDATA__ placeholder — not writing {PAGE}")
        else:
            with open(PAGE, "w", encoding="utf-8") as f:
                f.write(template.replace("__NHLDATA__", payload))
            print(f"  {PAGE}: written")
    else:
        print(f"  {TEMPLATE} not found — skipping {PAGE}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Prop Streak Lab — data builder.

Downloads nflverse public data (weekly player stats, schedule, injury reports,
rosters), builds the compact dataset the site runs on, records and grades the
site's picks, and injects the dataset into template.html to produce nfl.html.

Python 3 standard library only — nothing to install. Run locally: python build.py

Outputs
  data.json   player game logs, this week's schedule, injuries, defense ranks
  nfl.html    template.html with data.json baked in (the NFL page; index.html is the static home page)
  slate.json  this week's Polymarket player-prop events (for the live board scan)
  picks.json  every pick the site has made (live + backtest), graded as games finish

The probability model here is mirrored line-for-line in template.html (the block
marked "MODEL"). tests/test_model.py checks the two agree. Change both or neither.
"""
import csv, io, json, math, os, re, sys, time, datetime, unicodedata, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

import news   # pre-game news feeds, test mode
import kalshi  # Kalshi prices, side by side with Polymarket's
import depth   # enough money at the price? (thin-market filter)
import holds   # props that wait for injury news

TODAY = datetime.date.today()


def season_year(d):
    """NFL season label. Sep-Feb games belong to the year the season started."""
    return d.year if d.month >= 8 else d.year - 1


SEASON = season_year(TODAY)
CANDIDATE_SEASONS = [SEASON - 2, SEASON - 1, SEASON]   # 3 seasons so "last 30" has depth

SKILL = {"QB", "RB", "WR", "TE", "FB"}
BASE = "https://github.com/nflverse/nflverse-data/releases/download/"
STATS_URL = BASE + "stats_player/stats_player_week_{year}.csv"
SCHED_URL = BASE + "schedules/games.csv"
INJ_URL = BASE + "injuries/injuries_{year}.csv"
ROSTER_URL = BASE + "rosters/roster_{year}.csv"
SNAPS_URL = BASE + "snap_counts/snap_counts_{year}.csv"
PLAYERS_URL = BASE + "players/players.csv"      # id crosswalk: snap counts use PFR ids
UA = {"User-Agent": "prop-streak-lab/2.0"}

# ESPN public box scores — a near-real-time fill for current-season games the
# schedule already shows final but that nflverse hasn't published weekly stats
# for yet (nflverse lags 1-2 days). Unofficial but stable and free. site.web.api,
# not site.api: ESPN's CDN refuses site.api from data-center IPs like GitHub's
# (HTTP 403), as the NBA/NHL/MLB builders found; site.web.api serves them.
ESPN_SB = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={season}&seasontype=2&week={week}"
ESPN_SUM = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event}"

# ---------------------------------------------------------------------------
# Game-row layout. The front-end reads rows by index — keep in sync with template.html.
#   0 season  1 week  2 opp  3 type(REG/POST)
#   4 pass_yds 5 pass_td 6 pass_att 7 pass_cmp 8 pass_int
#   9 rush_att 10 rush_yds 11 rush_td 12 rec 13 tgt 14 rec_yds 15 rec_td
#   16 home(1/0)  17 target_share (0-1)
#   18 Vegas total for that game (or null)  19 spread for the player's team (+ = favored, or null)
#   20 offensive snap share (0-1 or null; only on players with snap usage, see game_per)
# ---------------------------------------------------------------------------
STAT_COLS = ["passing_yards", "passing_tds", "attempts", "completions", "passing_interceptions",
             "carries", "rushing_yards", "rushing_tds",
             "receptions", "targets", "receiving_yards", "receiving_tds"]
REQUIRED = {"player_id", "player_display_name", "position", "season", "week", "season_type",
            "game_id", "team", "opponent_team", "target_share"} | set(STAT_COLS)
STAT_IDX = {"pass_yds": 4, "pass_td": 5, "pass_att": 6, "pass_cmp": 7, "pass_int": 8,
            "rush_att": 9, "rush_yds": 10, "rush_td": 11, "rec": 12, "tgt": 13, "rec_yds": 14, "rec_td": 15}
COMBO = {"rush_rec_yds": (10, 14), "pass_rush_yds": (4, 10), "scrim_td": (11, 15)}
COUNT_STATS = {"pass_td", "pass_att", "pass_cmp", "pass_int", "rush_att", "rush_td", "rec", "tgt", "rec_td", "scrim_td"}
STAT_KEYS = list(STAT_IDX) + list(COMBO)


def stat_value(key, row):
    if key in STAT_IDX:
        return row[STAT_IDX[key]]
    a, b = COMBO[key]
    return row[a] + row[b]


TD_STATS = {"rec_td", "rush_td", "scrim_td"}   # "anytime"-style TD props: their own smoothing floor


def stat_kind(key):
    return "td" if key in TD_STATS else "count" if key in COUNT_STATS else "yards"


# ---------------------------------------------------------------------------
# MODEL — mirrored in template.html. Keep both identical.
#
# Instead of a raw "hit 7 of last 10" frequency, the chance of clearing a line is
# estimated from the *distribution* of the player's recent values:
#   1. take up to the last 30 games, weight recent ones more (half-life 8 games);
#   2. smooth the weighted values with a Gaussian kernel (Silverman bandwidth, with
#      a floor so a run of identical values still has spread);
#   3. read P(over) / P(under) / P(push) off that smoothed distribution;
#   4. shrink toward 50/50 by half a pseudo-game, so tiny samples can't claim 100%;
#   5. attach an 80% Wilson interval sized by the *effective* sample (weights).
# ---------------------------------------------------------------------------
# Walk-forward backtest (2025 + 2026 so far: 33,000 player games over 13 props, each from
# earlier games only, scored on odd and on even weeks separately): 30 games at half-life 8
# beat 20 at half-life 6 pooled on both halves, and receiving / rushing / scrimmage TDs got
# their own floor, 0.25 (was the count floor, 0.35, which put 24-27% on TDs that happened
# 18-20% of the time): log loss -0.004 to -0.010 on both halves. Passing TDs keep 0.35
# (the lower floor was worse on one half). Re-scoring the 580 graded live picks with a
# Polymarket price: log loss 0.6557 -> 0.6545 (the market's own price: 0.6305).
MODEL = {"halfLife": 8.0, "maxGames": 30, "priorK": 0.5, "bwConst": 0.9, "bwFloorCount": 0.35, "bwFloorYards": 1.0,
         "bwFloorTd": 0.25, "z": 1.2816}
MODEL_V = 3   # recorded on every live pick ("mv"); calibration uses only this version's live picks

# Per-stat calibration, fitted on the same walk-forward backtest: the chance's log-odds become
# a + b * log-odds. It removes a bias the smoothing leaves (most props read overs a few points
# high) and fixes over/under-confidence. Fitted at the seeded line and a line either side on
# one half of the data and scored on the other, both ways; only stats where that improved
# both halves are listed (the rest are left as they were).
CAL = {"rec_yds": (-0.243, 1.014), "rec": (-0.142, 0.98), "rec_td": (-0.481, 0.906), "tgt": (-0.121, 1.002), "scrim_td": (-0.434, 0.914), "rush_yds": (-0.147, 1.15), "rush_att": (-0.116, 0.954), "rush_td": (-0.474, 0.884)}

# Game-context adjustment. The player's distribution is scaled by
#   (this game's implied team points / their usual implied points) ^ betaPts
#   * exp(betaSpr * (spread swing in TDs))          (favorites run more, underdogs pass more)
#   * (opponent's allowed-per-game / league average) ^ gamma
#   * (recent snap share / usual snap share) ^ usage   (see usage_shares; for non-passing stats
#     each past game is put on the recent share instead, see game_per)
# Strengths were fitted on the walk-forward backtest (tools/tune_context.py) and
# validated on held-out weeks. 0 = adjustment off. Clamped to [clampLo, clampHi].
# usage = 0.5 lowered held-out log-loss in every family and both week folds
# (all cases with snap data: 0.5960 -> 0.5924, n = 16,993).
CTX = {"betaPts": {"pass": 0.25, "rush": 0.25, "rec": 0.25},
       "betaSpr": {"pass": 0.0, "rush": 0.0, "rec": 0.0},
       "gamma": {"pass": 0.75, "rush": 0.25, "rec": 0.5},
       "usage": 0.5,
       "clampLo": 0.6, "clampHi": 1.6}


def _erf(x):
    # Abramowitz & Stegun 7.1.26 (|error| < 1.5e-7); identical implementation in JS.
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


def model_prob(values, line, kind, scale=1.0, cal=None, per=None):
    """values oldest -> newest; scale multiplies every value (game-context adjustment);
    per, if given, is one more factor per value (same length, see game_per).
    Returns dict with over/under/push probabilities, an 80% interval on P(over),
    the effective sample size and moments, or None."""
    vals = values[-MODEL["maxGames"]:]
    if per and len(per) == len(values):
        v = [x * scale * k for x, k in zip(vals, per[-MODEL["maxGames"]:])]
    else:
        v = [x * scale for x in vals]
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
    floor = MODEL["bwFloorTd"] if kind == "td" else MODEL["bwFloorCount"] if kind == "count" else MODEL["bwFloorYards"]
    h = max(MODEL["bwConst"] * sd * neff ** (-0.2), floor)

    def F(t):
        return sum(wi * ncdf((t - x) / h) for wi, x in zip(w, v)) / W

    lo_edge = math.floor(line) + 0.5      # == line for half-point lines
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


def stat_family(stat, pos):
    if stat in ("rush_rec_yds", "scrim_td"):        # combos: by the player's role
        return "rush" if pos in ("RB", "FB") else "rec"
    if stat.startswith("pass"):
        return "pass"
    if stat.startswith("rush"):
        return "rush"
    return "rec"


def def_stat_for(stat, pos):
    """Which defense-allowed stat proxies this prop (None = no defense adjustment)."""
    rb = pos in ("RB", "FB")
    m = {"pass_yds": "pass_yds", "pass_td": "pass_td", "pass_att": "pass_yds", "pass_cmp": "pass_yds",
         "pass_rush_yds": "pass_yds", "rush_yds": "rush_yds", "rush_att": "rush_yds", "rush_td": "rush_td",
         "rush_rec_yds": "rush_yds" if rb else "rec_yds", "rec": "rec", "rec_yds": "rec_yds", "tgt": "rec",
         "rec_td": "rec_td", "scrim_td": "rush_td" if rb else "rec_td"}
    return m.get(stat)


def hist_context(rows):
    """Recency-weighted mean implied team points and spread over the games the model uses."""
    r = rows[-MODEL["maxGames"]:]
    n = len(r)
    hl = MODEL["halfLife"]
    sp = ss = wp = 0.0
    for i, g in enumerate(r):
        tot, spr = g[18], g[19]
        if tot is None or spr is None:
            continue
        w = 0.5 ** ((n - 1 - i) / hl)
        sp += w * (tot / 2.0 + spr / 2.0)
        ss += w * spr
        wp += w
    return {"pts": sp / wp if wp else None, "spr": ss / wp if wp else None}


def context_scale(fam, hist, game_pts, game_spr, def_ratio, usage=None):
    """Multiplier for the player's distribution in this game. Missing inputs -> no change.
    usage is the snap-share ratio from usage_of(), or None."""
    env = 1.0
    if hist["pts"] and game_pts and hist["pts"] > 0 and game_pts > 0:
        env *= (game_pts / hist["pts"]) ** CTX["betaPts"][fam]
    if hist["spr"] is not None and game_spr is not None:
        env *= math.exp(CTX["betaSpr"][fam] * (game_spr - hist["spr"]) / 7.0)
    dfs = 1.0
    if def_ratio and def_ratio > 0:
        dfs = def_ratio ** CTX["gamma"][fam]
    scale = min(CTX["clampHi"], max(CTX["clampLo"], env * dfs))
    base = scale
    use = usage ** CTX["usage"] if usage else 1.0
    if use != 1.0:
        scale = min(CTX["clampHi"], max(CTX["clampLo"], scale * use))
    return {"scale": scale, "env": env, "def": dfs, "use": use, "base": base}


# ---------------------------------------------------------------------------
# Snap-share usage: a role change the box score is slow to show (a back who took
# over the starting job, a receiver returning from injury on a snap count).
# Recent = mean offensive snap share of the last 2 games with snap data; usual =
# recency-weighted share (half-life 6) over the last 8. Needs 4 known games.
# ---------------------------------------------------------------------------
SNAPS = {}   # (player id, season, week) -> offensive snap share 0..1; empty = adjustment off


def load_snaps(seasons):
    """nflverse snap counts keyed to the stats' player ids. Any failure -> {}."""
    ids = {}
    for r in fetch_csv(PLAYERS_URL, "players crosswalk") or []:
        if r.get("pfr_id") and r.get("gsis_id"):
            ids[r["pfr_id"]] = r["gsis_id"]
    out = {}
    if not ids:
        return out
    for y in seasons:
        for r in fetch_csv(SNAPS_URL.format(year=y), f"snaps {y}") or []:
            g = ids.get(r.get("pfr_player_id"))
            try:
                pct = float(r.get("offense_pct") or "nan")
                key = (g, int(r["season"]), int(r["week"]))
            except (TypeError, ValueError, KeyError):
                continue
            if g and pct == pct:
                out[key] = pct
    return out


def usage_shares(pid, prior):
    """[recent, usual] snap share before the next game, or None (too little snap data)."""
    sh = [SNAPS.get((pid, r[0], r[1])) for r in prior[-8:]]
    sh = [x for x in sh if x is not None]
    if len(sh) < 4:
        return None
    w = [0.5 ** ((len(sh) - 1 - k) / 6.0) for k in range(len(sh))]
    usual = sum(a * b for a, b in zip(sh, w)) / sum(w)
    if usual <= 0.05:
        return None
    return [round((sh[-1] + sh[-2]) / 2.0, 3), round(usual, 3)]


def usage_of(shares):
    """The usage ratio recent / usual, clamped to [0.5, 1.6]; None -> None. Mirrored in JS."""
    if not shares:
        return None
    return max(0.5, min(1.6, shares[0] / shares[1]))


def game_shares(pid, rows):
    """Each game's snap share (or None), aligned with rows."""
    return [SNAPS.get((pid, r[0], r[1])) for r in rows]


def game_per(scale, usage, recent, shares, fam):
    """Per-game factors for model_prob(per=...), or None.
    The plain usage cut scales every past game by (recent / usual) ^ usage, which counts
    the change twice for games already played at the new share: a receiver back from a
    hamstring on a 30% snap count had his 150- and 84-yard low-snap games cut by 29% again.
    Instead each game with a known share is put on the recent share itself:
    scale * (recent / its share) ^ usage / (recent / usual) ^ usage, clamped like the scale;
    games without snap data keep the plain scale. Passing stats keep the plain cut (a
    quarterback's partial games are injuries and blowouts, not a role), which also tested
    better. Walk-forward backtest, every non-passing case: log loss 0.55471 -> 0.55431
    (odd weeks), 0.55707 -> 0.55635 (even weeks); the graded live picks with a Polymarket
    price 0.6475 -> 0.6462. Mirrored in JS (gamePer)."""
    if not usage or not recent or not scale or fam == "pass":
        return None
    use = usage ** CTX["usage"]
    lo, hi = CTX["clampLo"], CTX["clampHi"]
    return [1.0 if s is None or s <= 0.05 else
            min(hi, max(lo, scale * max(0.5, min(1.6, recent / s)) ** CTX["usage"] / use)) / scale
            for s in shares]


def median(a):
    if not a:
        return 0
    s = sorted(a)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def seed_line(values):
    """The 'realistic' line the site seeds for a player/stat: median of the last 10,
    rounded to the nearest .5 below the whole number. Mirrored in the front-end."""
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
# Fetch helpers
# ---------------------------------------------------------------------------
def http_get(url, timeout=120, tries=3):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            err = e
            if getattr(e, "code", None) == 404:
                break
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise err


def fetch_csv(url, label):
    try:
        raw = http_get(url).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"  {label}: skipped ({e})")
        return None
    rows = list(csv.DictReader(io.StringIO(raw)))
    print(f"  {label}: {len(rows)} rows")
    return rows


def num(v):
    """Parse a stat cell to a number; blanks -> 0; whole numbers stay ints."""
    if v in (None, ""):
        return 0
    try:
        f = round(float(v), 1)
    except ValueError:
        return 0
    return int(f) if f.is_integer() else f


def fnum(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Schedule (nflverse games.csv): kickoff, Vegas lines, final scores
# ---------------------------------------------------------------------------
def load_schedule(seasons):
    rows = fetch_csv(SCHED_URL, "schedule") or []
    games = {}
    for r in rows:
        try:
            s = int(r.get("season") or 0)
            wk = int(r.get("week") or 0)
        except ValueError:
            continue
        if s not in seasons:
            continue
        final = (r.get("result") or "") != ""
        games[r["game_id"]] = {
            "id": r["game_id"], "season": s, "week": wk, "type": r.get("game_type") or "REG",
            "date": r.get("gameday") or "", "time": r.get("gametime") or "",
            "away": r.get("away_team") or "", "home": r.get("home_team") or "",
            "final": final,
            "as": num(r.get("away_score")) if final else None,
            "hs": num(r.get("home_score")) if final else None,
            "spread": fnum(r.get("spread_line")),   # positive = home favored
            "total": fnum(r.get("total_line")),
            "roof": r.get("roof") or "", "stadium": r.get("stadium") or "",   # for the weather test
        }
    return games


def current_week(sched, season):
    gs = [g for g in sched.values() if g["season"] == season]
    if not gs:
        return None
    pending = [g for g in gs if not g["final"]]
    return min(g["week"] for g in pending) if pending else max(g["week"] for g in gs)


# ---------------------------------------------------------------------------
# ESPN box scores (fresh fill for games nflverse hasn't posted yet)
# ---------------------------------------------------------------------------
def _espn_cell(d, *names):
    for n in names:
        if n in d:
            return d[n]
    return None


def espn_box_to_rows(summ, sg, season, week, stype, home, away, nfl_index):
    """One ESPN game summary -> nflverse-shaped stat rows, only for players we can
    match by name to an existing nflverse player (so ids/positions stay consistent)."""
    rows = []
    for tb in (summ.get("boxscore") or {}).get("players") or []:
        team = team_code((tb.get("team") or {}).get("abbreviation"))
        opp = away if team == home else home
        agg, team_targets = {}, 0
        for cat in tb.get("statistics") or []:
            name = (cat.get("name") or "").lower()
            if name not in ("passing", "rushing", "receiving"):
                continue
            labels = [str(l).upper() for l in (cat.get("labels") or [])]
            for ath in cat.get("athletes") or []:
                disp = ((ath.get("athlete") or {}).get("displayName") or "").strip()
                if not disp:
                    continue
                st = ath.get("stats") or []
                d = {labels[i]: st[i] for i in range(min(len(labels), len(st)))}
                e = agg.setdefault(pkey(disp), {"n": disp, "s": {}})
                if name == "passing":
                    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", str(_espn_cell(d, "C/ATT") or "0/0"))
                    e["s"]["completions"] = int(m.group(1)) if m else 0
                    e["s"]["attempts"] = int(m.group(2)) if m else 0
                    e["s"]["passing_yards"] = num(_espn_cell(d, "YDS"))
                    e["s"]["passing_tds"] = num(_espn_cell(d, "TD"))
                    e["s"]["passing_interceptions"] = num(_espn_cell(d, "INT"))
                elif name == "rushing":
                    e["s"]["carries"] = num(_espn_cell(d, "CAR"))
                    e["s"]["rushing_yards"] = num(_espn_cell(d, "YDS"))
                    e["s"]["rushing_tds"] = num(_espn_cell(d, "TD"))
                else:
                    tg = num(_espn_cell(d, "TGTS", "TAR"))
                    e["s"]["receptions"] = num(_espn_cell(d, "REC"))
                    e["s"]["targets"] = tg
                    e["s"]["receiving_yards"] = num(_espn_cell(d, "YDS"))
                    e["s"]["receiving_tds"] = num(_espn_cell(d, "TD"))
                    team_targets += tg if isinstance(tg, (int, float)) else 0
        for key, e in agg.items():
            idx = nfl_index.get(key)
            if not idx:
                continue                       # only established (name-matched) players
            pid, pos = idx
            s = e["s"]
            if any(isinstance(s.get(c), (int, float)) and not (-10 <= s.get(c) <= 700)
                   for c in ("passing_yards", "rushing_yards", "receiving_yards")):
                continue                       # drop obviously bad box-score values
            tgt = s.get("targets", 0) or 0
            row = {"player_id": pid, "player_display_name": e["n"], "position": pos,
                   "season": season, "week": week, "season_type": stype,
                   "game_id": sg["id"], "team": team, "opponent_team": opp,
                   "target_share": round(tgt / team_targets, 2) if team_targets else 0}
            for c in STAT_COLS:
                row[c] = s.get(c, 0)
            rows.append(row)
    return rows


def fetch_espn_recent(sched, stats_gids, nfl_index, season):
    """Stat rows for current-season REG games the schedule shows final but that are
    missing from the nflverse stats file. Mutates stats_gids with any game it fills."""
    missing = [g for g in sched.values()
               if g["season"] == season and g["final"] and g["type"] == "REG" and g["id"] not in stats_gids]
    if not missing:
        return []
    rows = []
    for wk in sorted({g["week"] for g in missing}):
        try:
            sb = json.loads(http_get(ESPN_SB.format(season=season, week=wk)))
        except Exception as e:  # noqa: BLE001
            print(f"    ESPN scoreboard wk{wk}: skipped ({e})")
            continue
        for ev in sb.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not (((comp.get("status") or {}).get("type") or {}).get("completed")):
                continue
            cs = comp.get("competitors") or []
            home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
            away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
            sg = next((g for g in missing if g["week"] == wk and {g["away"], g["home"]} == {home, away}), None)
            if not sg:
                continue
            try:
                summ = json.loads(http_get(ESPN_SUM.format(event=ev.get("id"))))
            except Exception as e:  # noqa: BLE001
                print(f"    ESPN box {ev.get('id')}: skipped ({e})")
                continue
            gr = espn_box_to_rows(summ, sg, season, wk, sg["type"], home, away, nfl_index)
            if gr:
                rows.extend(gr)
                stats_gids.add(sg["id"])
    return rows


TOP_CACHE_FILE = "top_cache.json"


def fetch_team_top(sched, season):
    """Average offensive time of possession (seconds per game) per team this season,
    from ESPN box scores -> {team: seconds}. Each game is fetched once and cached in
    top_cache.json, so a build only pulls games it hasn't seen. Fully wrapped: any
    failure just leaves that game out (worst case returns {} and no ToP is shown)."""
    def parse_mmss(s):
        m = re.match(r"\s*(\d+):(\d{1,2})", str(s or ""))
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None
    try:
        with open(TOP_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)          # gid -> {team: seconds}
    except (OSError, ValueError):
        cache = {}
    games = [g for g in sched.values() if g["season"] == season and g["final"] and g["type"] == "REG"]
    need = [g for g in games if g["id"] not in cache]
    by_week = {}
    for g in need:
        by_week.setdefault(g["week"], []).append(g)
    for wk in sorted(by_week):
        try:
            sb = json.loads(http_get(ESPN_SB.format(season=season, week=wk)))
        except Exception as e:  # noqa: BLE001
            print(f"    ESPN ToP scoreboard wk{wk}: skipped ({e})")
            continue
        for ev in sb.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not (((comp.get("status") or {}).get("type") or {}).get("completed")):
                continue
            cs = comp.get("competitors") or []
            home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
            away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
            sg = next((g for g in by_week[wk] if {g["away"], g["home"]} == {home, away}), None)
            if not sg:
                continue
            try:
                summ = json.loads(http_get(ESPN_SUM.format(event=ev.get("id"))))
            except Exception:  # noqa: BLE001
                continue
            tops = {}
            for tb in (summ.get("boxscore") or {}).get("teams") or []:
                team = team_code((tb.get("team") or {}).get("abbreviation"))
                for st in tb.get("statistics") or []:
                    if st.get("name") == "possessionTime":
                        sec = parse_mmss(st.get("displayValue"))
                        if team and sec:
                            tops[team] = sec
                        break
            if tops:
                cache[sg["id"]] = tops
    try:
        with open(TOP_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, separators=(",", ":"))
    except OSError:
        pass
    season_gids = {g["id"] for g in games}
    acc = {}
    for gid, tops in cache.items():
        if gid not in season_gids:
            continue
        for team, sec in tops.items():
            a = acc.setdefault(team, [0, 0])
            a[0] += sec
            a[1] += 1
    return {t: round(v[0] / v[1]) for t, v in acc.items() if v[1]}


# ---------------------------------------------------------------------------
# Injuries + rosters (current season)
# ---------------------------------------------------------------------------
def _short_practice(p):
    p = (p or "").lower()
    if p.startswith("did not"):
        return "DNP"
    if p.startswith("limited"):
        return "LP"
    if p.startswith("full"):
        return "FP"
    return ""


def load_injuries(season):
    rows = fetch_csv(INJ_URL.format(year=season), f"injuries {season}")
    if not rows:
        return {}
    weeks = [int(r["week"]) for r in rows if (r.get("week") or "").isdigit()]
    if not weeks:
        return {}
    latest = max(weeks)
    out = {}
    for r in rows:
        if not (r.get("week") or "").isdigit() or int(r["week"]) != latest:
            continue
        status = r.get("report_status") or ""
        prac = _short_practice(r.get("practice_status"))
        inj = r.get("report_primary_injury") or r.get("practice_primary_injury") or ""
        if not status and prac not in ("DNP", "LP"):
            continue
        out[r.get("gsis_id") or ""] = [status, inj, prac, latest]
    return out


def load_roster(season):
    rows = fetch_csv(ROSTER_URL.format(year=season), f"roster {season}") or []
    out = {}
    for r in rows:
        gid = r.get("gsis_id")
        if not gid:
            continue
        out[gid] = {"team": r.get("team") or "", "status": r.get("status") or "",
                    "pos": r.get("position") or "", "name": r.get("full_name") or "",
                    "rookie": (r.get("rookie_year") or "") == str(season)}
    return out


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
def build_players(all_rows, roster, injuries, sched):
    players = {}
    for r in all_rows:
        if r.get("position") not in SKILL:
            continue
        pid = r.get("player_id")
        if not pid:
            continue
        try:
            wk = int(r.get("week") or 0)
        except ValueError:
            wk = 0
        parts = (r.get("game_id") or "").split("_")
        home_team = parts[3] if len(parts) >= 4 else ""
        h = 1 if (r.get("team") and r.get("team") == home_team) else 0
        ts = fnum(r.get("target_share"))
        sg = sched.get(r.get("game_id") or "")
        total = sg["total"] if sg else None
        spr = None
        if sg and sg["spread"] is not None:
            spr = sg["spread"] if h else -sg["spread"]
        game = [int(r.get("season") or 0), wk, r.get("opponent_team") or "", r.get("season_type") or "REG"] \
            + [num(r.get(c)) for c in STAT_COLS] + [h, round(ts, 2) if ts is not None else 0, total, spr]
        p = players.setdefault(pid, {"rows": []})
        p["rows"].append(game)
        p["meta"] = r  # latest row wins for name/pos/team

    out = []
    for pid, p in players.items():
        games = sorted(p["rows"], key=lambda g: (g[0], g[1]))
        meta = p["meta"]
        team = meta.get("team") or ""
        entry = {"id": pid,
                 "n": meta.get("player_display_name") or meta.get("player_name") or "Unknown",
                 "p": meta.get("position") or "", "t": team, "g": games}
        ro = roster.get(pid)
        if ro:
            if ro["team"] and ro["status"] not in ("CUT", "RET") and ro["team"] != team:
                entry["lt"] = team          # last team in the game log
                entry["t"] = ro["team"]     # current team per roster
            if ro["status"] and ro["status"] != "ACT":
                entry["st"] = ro["status"]  # RES = injured reserve, CUT, DEV, ...
            if ro["rookie"]:
                entry["rk"] = 1
        if pid in injuries:
            entry["inj"] = injuries[pid]
        out.append(entry)

    # Active roster players with no game log yet (rookies, returning players) —
    # searchable, and the board scan can say "no history" instead of dropping them.
    for pid, ro in roster.items():
        if pid in players or ro["pos"] not in SKILL or ro["status"] != "ACT" or not ro["name"]:
            continue
        e = {"id": pid, "n": ro["name"], "p": ro["pos"], "t": ro["team"], "g": []}
        if ro["rookie"]:
            e["rk"] = 1
        if pid in injuries:
            e["inj"] = injuries[pid]
        out.append(e)

    out.sort(key=lambda x: x["n"])
    return out


# ---------------------------------------------------------------------------
# Next man up: a back or receiver ruled out this week leaves his carries (rushing) and
# targets (receiving) to the teammates who play.
#
# Who's out: ESPN's injury report (Out / injured reserve, listed all week), nflverse's official
# report (Out, posted late in the week) and the roster's reserve lists (injured reserve, PUP,
# NFI, suspended). Questionable and doubtful players aren't settled yet: see holds below.
#
# How: each active teammate's past games are rebuilt as if the out player had sat them too.
# In every game the out player played, the teammate gets a share of his volume: that game's
# split among the active players, pulled toward how the team actually split the work in
# games the out player missed (NMU_EMP per such game). The extra carries/targets come at the
# teammate's own yards, catches and touchdowns per carry or target, shrunk toward his
# position's (NMU_EFF_K). The additions ride along per game ("inj_add": "season-week" ->
# {game-row index: amount}) and the model reads the rebuilt rows (model_rows here, modelRows
# on the page). The old version multiplied every past game by one factor capped at 1.5,
# which left a backup taking over a starter's job (3-5x the carries) far too low.
# Strengths fitted on past seasons by tune_injury.py.
# ---------------------------------------------------------------------------
NMU = {"rush": {"pos": ("RB", "FB"), "vol": 9, "stats": (10, 11)},               # carries -> rush yds, rush TDs
       "rec": {"pos": ("WR", "TE", "RB", "FB"), "vol": 13, "stats": (12, 14, 15)}}  # targets -> catches, rec yds, rec TDs
# Backtest (tune_injury.py, 2025-26: every game a regular missed after playing the week before):
# who takes over is often a surprise, so a confident full hand-off scored worse than ignoring the
# injury. A quarter of a back's carries to his real backups scored best at realistic lines (heirs
# of a starter out, log loss 0.480 -> 0.472, both halves of the season); for receivers no hand-off
# helped (targets scatter), so it's off there.
NMU_LAMBDA = {"rush": 0.25, "rec": 0.0}   # share of a newly-out player's work handed to his heirs
NMU_EMP = 1.0         # weight of each game the out player missed, against the same-game split
NMU_EMP_GAMES = 4     # at most this many such games count
NMU_EFF_K = 20.0      # carries / targets of the position's average mixed into a player's per-carry rates
NMU_MIN_SHARE = 0.10  # an heir needs this share of his group's work in his last 3 games (no fullback takes a starter's carries)
# who inherits whose work: a back's carries go to backs; a receiver's targets to receivers and tight ends
NMU_HEIRS = {"rush": {"RB": ("RB",), "FB": ("RB",)},
             "rec": {"WR": ("WR", "TE"), "TE": ("TE", "WR"), "RB": ("RB",), "FB": ("RB",)}}
OUT_RE = re.compile(r"\bout\b|injured reserve|suspen|physically unable|\bpup\b|non-football", re.I)
OUT_ROSTER = {"RES", "PUP", "NFI", "SUS"}

# Holds (holds.py): until a questionable or doubtful player is settled (ESPN shows him Active or
# Out; on game day that's the inactives, 90 minutes before kickoff), every prop of his, and these
# props of his teammates, stay off Top 25 Surest and Value: his position -> {teammate's position:
# stat families that wait}. A quarterback's status moves the whole passing game.
HOLD_GROUP = {"QB": {"QB": ("pass", "rush", "rec"), "WR": ("rec",), "TE": ("rec",), "RB": ("rec",), "FB": ("rec",)},
              "RB": {"RB": ("rush", "rec"), "FB": ("rush", "rec")},
              "FB": {"RB": ("rush", "rec"), "FB": ("rush", "rec")},
              "WR": {"WR": ("rec",), "TE": ("rec",), "RB": ("rec",), "FB": ("rec",)},
              "TE": {"WR": ("rec",), "TE": ("rec",), "RB": ("rec",), "FB": ("rec",)}}
# A teammate holds others only with a real role: NMU_MIN_SHARE+ of his group's volume (pass
# attempts among quarterbacks, carries among backs, targets among receivers) in his last 3 games.
ROLE_VOL = {"QB": (6, ("QB",)), "RB": (9, ("RB", "FB")), "FB": (9, ("RB", "FB")),
            "WR": (13, ("WR", "TE", "RB", "FB")), "TE": (13, ("WR", "TE", "RB", "FB"))}
FAMILIES = ("pass", "rush", "rec")


def _inj_out(entry):
    inj = entry.get("inj")
    return bool(inj and OUT_RE.search(inj[0] or ""))


def _gkey(r):
    return (r[0], r[1], r[2])          # season, week, opponent: one game of one team


def _by_name(players):
    byname = {}
    for e in players:
        byname.setdefault(pkey(e["n"]), []).append(e)
    return byname


def injury_outs(players, espn=None):
    """ids of the players out this week (see above)."""
    byname = _by_name(players)
    out = {e["id"] for e in players if _inj_out(e) or e.get("st") in OUT_ROSTER}
    for x in espn or []:
        if OUT_RE.search(x.get("status") or ""):
            c = byname.get(pkey(x.get("name") or ""), [])
            if len(c) == 1:            # a name two players share is left alone
                out.add(c[0]["id"])
    return out


def injury_unsure(players, espn=None):
    """{id: "questionable" / "doubtful"}: the players who may not play. ESPN's report decides
    when it's available: it keeps updating through game day (Active once cleared, Out once ruled
    out). The official report (nflverse) only when ESPN can't be read."""
    if espn is None:
        return {e["id"]: holds.label(e["inj"][0]) for e in players
                if e.get("inj") and holds.status(e["inj"][0]) == "unsure"}
    byname, out = _by_name(players), {}
    for x in espn:
        if holds.status(x.get("status")) == "unsure":
            c = byname.get(pkey(x.get("name") or ""), [])
            if len(c) == 1:
                out[c[0]["id"]] = holds.label(x["status"])
    return out


def position_eff(players):
    """Per position, each stat per unit of its family's volume (league-wide): the prior the
    per-carry / per-target rates shrink toward."""
    tot = {}
    for e in players:
        for fam, cfg in NMU.items():
            if e["p"] not in cfg["pos"]:
                continue
            t = tot.setdefault((e["p"], fam), [0.0] * 16)
            for r in e["g"]:
                t[cfg["vol"]] += r[cfg["vol"]]
                for k in cfg["stats"]:
                    t[k] += r[k]
    return {key: {k: (t[k] / t[NMU[key[1]]["vol"]] if t[NMU[key[1]]["vol"]] else 0.0) for k in NMU[key[1]]["stats"]}
            for key, t in tot.items()}


def nmu_adds(members, out_ids, pos_eff, before=None, lam=None, w_emp=None):
    """members: one team's players ({"id", "p", "g"}); out_ids: the ones out. Returns
    {player id: {(season, week, opp): {row index: amount}}} for the active ones. before:
    (season, week) — only earlier games count (the backtest). lam / w_emp default to the fitted."""
    w_emp = NMU_EMP if w_emp is None else w_emp
    adds = {}
    for fam, cfg in NMU.items():
        fl = NMU_LAMBDA[fam] if lam is None else lam
        vi = cfg["vol"]
        outs = [m for m in members if m["id"] in out_ids and m["p"] in cfg["pos"]]
        acts = [m for m in members if m["id"] not in out_ids and m["p"] in cfg["pos"]]
        if not outs or not acts:
            continue
        rows = {m["id"]: {_gkey(r): r for r in m["g"] if before is None or (r[0], r[1]) < before}
                for m in outs + acts}
        # only players newly out (in one of the team's last 3 games): a longer absence is already
        # in his teammates' recent games
        recent = set(sorted({k for m in outs + acts for k in rows[m["id"]]})[-3:])
        outs = [o for o in outs if recent & set(rows[o["id"]])]
        if not outs or fl <= 0:
            continue
        everyone = outs + acts

        def share(a, keys):
            """a's share of the group's volume over these games."""
            num = sum(rows[a["id"]][k][vi] for k in keys if k in rows[a["id"]])
            den = sum(rows[b["id"]][k][vi] for k in keys for b in everyone if k in rows[b["id"]])
            return num / den if den > 0 else 0.0

        # only players with a real role inherit: NMU_MIN_SHARE+ of the work in their last 3 games
        role = {a["id"]: share(a, sorted(rows[a["id"]])[-3:]) for a in acts}
        # each active player's own rates per carry / target, shrunk toward his position's
        eff = {}
        for a in acts:
            g = sorted(rows[a["id"]].values(), key=lambda r: (r[0], r[1]))[-MODEL["maxGames"]:]
            v = sum(r[vi] for r in g)
            prior = pos_eff.get((a["p"], fam), {})
            eff[a["id"]] = {k: (sum(r[k] for r in g) + NMU_EFF_K * prior.get(k, 0.0)) / (v + NMU_EFF_K)
                            for k in cfg["stats"]}
        for o in outs:
            heirs = [a for a in acts if a["p"] in NMU_HEIRS[fam].get(o["p"], ()) and role[a["id"]] >= NMU_MIN_SHARE]
            if not heirs:
                continue
            played = {k for k, r in rows[o["id"]].items() if r[vi] > 0}
            # how the heirs split the work in their latest games without him (empirical)
            emp, n_emp = {}, 0
            gone = sorted({k for a in heirs for k in rows[a["id"]]} - set(rows[o["id"]]), reverse=True)[:NMU_EMP_GAMES]
            tot = sum(rows[a["id"]][k][vi] for k in gone for a in heirs if k in rows[a["id"]])
            if tot > 0:
                n_emp = len(gone)
                emp = {a["id"]: sum(rows[a["id"]][k][vi] for k in gone if k in rows[a["id"]]) / tot for a in heirs}
            for k in played:
                here = [a for a in heirs if k in rows[a["id"]]]
                if not here:
                    continue
                vac = rows[o["id"]][k][vi]
                tv = sum(rows[a["id"]][k][vi] for a in here)
                wn = w_emp * n_emp
                raw = {a["id"]: ((rows[a["id"]][k][vi] / tv if tv > 0 else 1.0 / len(here))
                                 + wn * emp.get(a["id"], 0.0)) / (1.0 + wn) for a in here}
                z = sum(raw.values()) or 1.0
                for a in here:
                    dv = fl * vac * raw[a["id"]] / z
                    if dv <= 0:
                        continue
                    add = adds.setdefault(a["id"], {}).setdefault(k, {})
                    add[vi] = add.get(vi, 0.0) + dv
                    for st, rate in eff[a["id"]].items():
                        add[st] = add.get(st, 0.0) + dv * rate
    return adds


def team_games(sched):
    """team -> {(season, week, opponent)}: its games from the schedule, keyed like _gkey."""
    out = {}
    for g in (sched or {}).values():
        out.setdefault(g["home"], set()).add((g["season"], g["week"], g["away"]))
        out.setdefault(g["away"], set()).add((g["season"], g["week"], g["home"]))
    return out


def team_holds(members, unsure, out_ids, games=None):
    """{player id: {family: [why, ...]}} for one team's players (see HOLD_GROUP): every family of
    a player who is out (he isn't playing) or unsure ({id: label}), and the HOLD_GROUP families of
    the teammates of an unsure player with a real role (ROLE_VOL). games: the team's games
    (team_games); shares count only those, so a player who hasn't played for the team yet has no
    role in it (None: every game counts)."""
    rows = {m["id"]: {_gkey(r): r for r in m["g"]} for m in members}

    def share(m):
        vi, pos = ROLE_VOL[m["p"]]
        grp = [b for b in members if b["p"] in pos]
        keys = sorted(k for k in rows[m["id"]] if games is None or k in games)[-3:]
        den = sum(rows[b["id"]][k][vi] for k in keys for b in grp if k in rows[b["id"]])
        return sum(rows[m["id"]][k][vi] for k in keys) / den if den > 0 else 0.0

    out = {}

    def hold(pid, fams, why):
        for f in fams:
            w = out.setdefault(pid, {}).setdefault(f, [])
            if why not in w:
                w.append(why)

    for m in members:
        if m["id"] in out_ids:
            hold(m["id"], FAMILIES, f"{m['n']} (out)")
        elif m["id"] in unsure:
            hold(m["id"], FAMILIES, f"{m['n']} ({unsure[m['id']]})")
    for u in members:
        if u["id"] not in unsure or u["p"] not in HOLD_GROUP or share(u) < NMU_MIN_SHARE:
            continue
        for a in members:
            fams = HOLD_GROUP[u["p"]].get(a["p"])
            if fams and a["id"] != u["id"] and a["id"] not in out_ids:
                hold(a["id"], fams, f"{u['n']} ({unsure[u['id']]})")
    return out


def compute_injury_boosts(players, espn=None, sched=None):
    """Next man up and holds for this week (see above), in place: entry['inj_add'] with the
    per-game additions and entry['inj_boost'] = {"rush"/"rec": recent volume with / without
    them, "why": who's out; "hold": [stat families waiting on news], "hw": on whom}. sched:
    load_schedule's games, to tell a team's games from a newcomer's games elsewhere. Returns
    (players out, players questionable or doubtful, teammates handed work, players held)."""
    outs = injury_outs(players, espn)
    unsure = {k: v for k, v in injury_unsure(players, espn).items() if k not in outs}
    pos_eff = position_eff(players)
    tg = team_games(sched)
    teams = {}
    for e in players:
        if e.get("t"):
            teams.setdefault(e["t"], []).append(e)
    adjusted = held = 0
    for team, members in teams.items():
        team_out = {m["id"] for m in members if m["id"] in outs}
        team_unsure = {m["id"]: unsure[m["id"]] for m in members if m["id"] in unsure}
        if not team_out and not team_unsure:
            continue
        out_ids = {m["id"] for m in members if m["id"] in team_out and m["p"] in ("RB", "FB", "WR", "TE")}
        adds = nmu_adds(members, out_ids, pos_eff) if out_ids else {}
        hl = team_holds(members, team_unsure, team_out, tg.get(team))
        info = {m["id"]: (m["n"], m["p"]) for m in members}
        for m in members:
            a, h = adds.get(m["id"]) or {}, hl.get(m["id"]) or {}
            if not a and not h:
                continue
            b = {}
            if a:
                m["inj_add"] = {f"{k[0]}-{k[1]}": {str(i): round(v, 2) for i, v in d.items()} for k, d in a.items()}
                recent = sorted(m["g"], key=lambda r: (r[0], r[1]))[-8:]
                for fam, cfg in NMU.items():
                    if not any(cfg["vol"] in d for d in a.values()):
                        continue
                    base = sum(r[cfg["vol"]] for r in recent)
                    extra = sum(a.get(_gkey(r), {}).get(cfg["vol"], 0.0) for r in recent)
                    b[fam] = round(1.0 + extra / base, 2) if base > 0 else 1.0   # set either way: inj_on reads it
                fams = set(b) & set(NMU)
                b["why"] = ", ".join(f"{info[o][0]} (out)" for o in sorted(out_ids, key=lambda x: info[x][0])
                                     if any(info[o][1] in NMU[f]["pos"] for f in fams))[:90]
                adjusted += 1
            if h:
                b["hold"] = sorted(h)
                b["hw"] = ", ".join(dict.fromkeys(w for f in sorted(h) for w in h[f]))[:120]
                held += 1
            m["inj_boost"] = b
    return len(outs), len(unsure), adjusted, held


def model_rows(pl):
    """The player's game rows as the model reads them: with next man up's additions, if any."""
    add = pl.get("inj_add")
    if not add:
        return pl["g"]
    out = []
    for r in pl["g"]:
        a = add.get(f"{r[0]}-{r[1]}")
        if a:
            r = list(r)
            for i, v in a.items():
                r[int(i)] += v
        out.append(r)
    return out


def inj_on(pl, sk):
    """Is next man up adjusting this player's stat family? (Then the snap-share usage
    adjustment stays off: the rebuilt games already carry the new role.)"""
    b = pl.get("inj_boost")
    return bool(b and b.get(stat_family(sk, pl["p"])))


def hold_reason(pl, sk):
    """What this prop waits on (team_holds), or None: a held prop stays off the lists."""
    b = pl.get("inj_boost")
    return b.get("hw") or "injury news" if b and stat_family(sk, pl["p"]) in (b.get("hold") or ()) else None


# ---------------------------------------------------------------------------
# Defense-vs-position: per-game allowed, blended across this season and last.
# Early in a season last year's numbers dominate; by mid-season this year's do.
# ---------------------------------------------------------------------------
POS_STAT = {
    "QB": ["pass_yds", "pass_td"],
    "RB": ["rush_yds", "rush_td", "rec", "rec_yds"],
    "WR": ["rec_yds", "rec", "rec_td"],
    "TE": ["rec_yds", "rec", "rec_td"],
}
STAT_TO_COL = {"pass_yds": "passing_yards", "pass_td": "passing_tds", "rush_yds": "rushing_yards",
               "rush_td": "rushing_tds", "rec_yds": "receiving_yards", "rec": "receptions", "rec_td": "receiving_tds"}
DEF_PRIOR_GAMES = 6.0   # last season counts like this many games of the current one


def build_def_timeline(all_rows, seasons):
    """Returns snapshot(season, before_week): per-game allowed by each defense to each
    position, using that season's games before `before_week` blended with the full
    previous season (DEF_PRIOR_GAMES of prior weight). Walk-forward safe for backtests."""
    per = {}  # (team, season) -> {week: {"games": set(), "sums": {}}}
    for r in all_rows:
        try:
            s_, wk = int(r.get("season") or 0), int(r.get("week") or 0)
        except ValueError:
            continue
        pos = r.get("position")
        dt = r.get("opponent_team")
        if pos not in POS_STAT or not dt:
            continue
        e = per.setdefault((dt, s_), {}).setdefault(wk, {"games": set(), "sums": {}})
        e["games"].add(r.get("game_id") or "")
        for sk in POS_STAT[pos]:
            key = pos + "|" + sk
            e["sums"][key] = e["sums"].get(key, 0) + num(r.get(STAT_TO_COL[sk]))
    teams = sorted({t for (t, _) in per})
    cache = {}

    def totals(team, season, before_week):
        games, sums = set(), {}
        for wk, e in per.get((team, season), {}).items():
            if wk < before_week:
                games |= e["games"]
                for k, v in e["sums"].items():
                    sums[k] = sums.get(k, 0) + v
        return len(games), sums

    def snapshot(season, before_week=99):
        key = (season, before_week)
        if key in cache:
            return cache[key]
        vals, gmax = {}, 0
        for t in teams:
            gc, sc = totals(t, season, before_week)
            gp, sp = totals(t, season - 1, 99)
            gmax = max(gmax, gc)
            for pos, stats in POS_STAT.items():
                for sk in stats:
                    k = pos + "|" + sk
                    pa = (sp.get(k, 0) / gp) if gp else None
                    if gc == 0 and pa is None:
                        continue
                    if pa is None:
                        a = sc.get(k, 0) / gc
                    elif gc == 0:
                        a = pa
                    else:
                        a = (sc.get(k, 0) + DEF_PRIOR_GAMES * pa) / (gc + DEF_PRIOR_GAMES)
                    vals.setdefault(t, {}).setdefault(pos, {})[sk] = a
        avg = {}
        for pos, stats in POS_STAT.items():
            for sk in stats:
                xs = [vals[t][pos][sk] for t in vals if pos in vals[t] and sk in vals[t][pos]]
                if xs:
                    avg.setdefault(pos, {})[sk] = sum(xs) / len(xs)
        cache[key] = {"teams": vals, "avg": avg, "games": gmax}
        return cache[key]

    return snapshot


def rank_defense(snap, season):
    """data.json form: def[team][pos][stat] = {a: per-game allowed, r: rank (1 = softest), n}."""
    defense = {}
    for pos, stats in POS_STAT.items():
        for sk in stats:
            vals = [(t, snap["teams"][t][pos][sk]) for t in snap["teams"]
                    if pos in snap["teams"][t] and sk in snap["teams"][t][pos]]
            vals.sort(key=lambda x: x[1], reverse=True)
            for i, (t, v) in enumerate(vals):
                defense.setdefault(t, {}).setdefault(pos, {})[sk] = {"a": round(v, 1), "r": i + 1, "n": len(vals)}
    avg = {pos: {sk: round(v, 2) for sk, v in d.items()} for pos, d in snap["avg"].items()}
    g = snap["games"]
    note = (f"{season} through {g} game{'s' if g != 1 else ''}, blended with {season - 1}" if g else f"{season - 1} season")
    return defense, avg, note


def def_ratio(snap, opp, pos, stat):
    """Opponent's allowed-per-game over the league average for the stat that proxies this prop."""
    dp = "RB" if pos == "FB" else pos
    ds = def_stat_for(stat, pos)
    if not ds or not opp:
        return None
    t = snap["teams"].get(opp, {}).get(dp, {})
    a, L = t.get(ds), snap["avg"].get(dp, {}).get(ds)
    return (a / L) if (a is not None and L) else None


# ---------------------------------------------------------------------------
# Polymarket slate (this week's player-prop events)
# ---------------------------------------------------------------------------
SLATE_URL = ("https://gamma-api.polymarket.com/events"
             "?closed=false&tag_slug=nfl&limit=500&order=startDate&ascending=false")
EVENT_URL = "https://gamma-api.polymarket.com/events/slug/{slug}"
SLUG_RE = re.compile(r"^nfl-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})-player-props$")
Q_RE = re.compile(r"^(.*?):\s*(.+?)\s+O/U\s+([\d.]+)", re.I)
TEAM_ALIAS = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LA"}
# Market text -> stat key. Order matters (combo before its parts). Mirrored in template.html.
MKT_STAT = [
    (re.compile(r"passing yards", re.I), "pass_yds"),
    (re.compile(r"passing touchdowns|pass(ing)? tds", re.I), "pass_td"),
    (re.compile(r"completions", re.I), "pass_cmp"),
    (re.compile(r"passing attempts|pass attempts", re.I), "pass_att"),
    (re.compile(r"interceptions", re.I), "pass_int"),
    (re.compile(r"rush.* \+ .*rec|scrimmage yards|rushing \+ receiving", re.I), "rush_rec_yds"),
    (re.compile(r"rushing yards", re.I), "rush_yds"),
    (re.compile(r"rushing attempts|carries", re.I), "rush_att"),
    (re.compile(r"rushing touchdowns|rushing tds", re.I), "rush_td"),
    (re.compile(r"receiving yards", re.I), "rec_yds"),
    (re.compile(r"receptions", re.I), "rec"),
    (re.compile(r"receiving touchdowns|receiving tds", re.I), "rec_td"),
]


def team_code(t):
    t = (t or "").upper()
    return TEAM_ALIAS.get(t, t)


def pkey(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    for ch in ".'`-":
        s = s.replace(ch, "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def mkt_stat_key(txt):
    for rx, k in MKT_STAT:
        if rx.search(txt):
            return k
    return None


def _jsonish(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def parse_market(m):
    """Read one Polymarket O/U market. Prices are what you'd PAY for each side:
    over = over ask, under = 1 - over bid (the spread is not free)."""
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
        mid = float(prices[io_]) if io_ >= 0 and io_ < len(prices) else None
    except (TypeError, ValueError):
        mid = None
    bid, ask = fnum(m.get("bestBid")), fnum(m.get("bestAsk"))
    # bestBid/bestAsk describe the first outcome; flip if Over is the second one.
    if bid is not None and ask is not None and io_ == 1:
        bid, ask = 1 - ask, 1 - bid
    spread = fnum(m.get("spread"))
    if spread is None and bid is not None and ask is not None:
        spread = round(ask - bid, 3)
    liq = fnum(m.get("liquidityNum")) or 0.0
    vol = fnum(m.get("volumeNum")) or 0.0
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
    return {"player": player, "statText": stat_text, "line": line, "mid": mid,
            "over": over_buy if ok(over_buy) else None, "under": under_buy if ok(under_buy) else None,
            "tradeable": tradeable, "spread": spread, "liq": liq, "vol": vol}


# ---------------------------------------------------------------------------
# Polymarket US prices. The global book the slate comes from is mostly one-sided
# for NFL props, so its Under price (derived as 1 - bestBid) runs far too rich and
# quietly keeps unders off the Value list. Polymarket US is the exchange the site
# links to and quotes both sides properly, so picks are priced there when it lists
# the same prop at the same line. One request per game prices every prop in it.
# Mirrors the live pricing the page does in pmusGame()/valuePrice().
# ---------------------------------------------------------------------------
PMUS_BASE = "https://gateway.polymarket.us"
PMUS_TEAM = {"LA": "lar"}        # nflverse code -> Polymarket US code; the rest lower-case
PMUS_STAT = {
    "football_player_passing_yards": "pass_yds",
    "football_player_passing_touchdowns": "pass_td",
    "football_player_passing_completions": "pass_cmp",
    "football_player_passing_attempts": "pass_att",
    "football_player_interceptions_thrown": "pass_int",
    "football_player_rushing_yards": "rush_yds",
    "football_player_rushing_attempts": "rush_att",
    "football_player_receiving_yards": "rec_yds",
    "football_player_receptions": "rec",
    "football_player_scrimmage_yards": "rush_rec_yds",
    "football_player_touchdowns": "scrim_td",
}


def pmus_event_slug(away, home, date):
    def code(t):
        return PMUS_TEAM.get(t, str(t).lower())
    return f"nfl-{code(away)}-{code(home)}-{date}"


def _pmus_quote(q):
    v = fnum((q or {}).get("value"))
    return v if (v is not None and 0 < v < 1) else None


def fetch_pmus_prices(slate_games, sched=None):
    """(player key, stat, line) -> {"over": cents, "under": cents}.
    What you would PAY: Over = best ask, Under = 1 - best bid. Polymarket US lists a
    prop as "N+", so its line N is the O/U line N - 0.5. Never fatal: a game that
    cannot be fetched simply keeps the global book's price.

    The slate dates Sunday-night and Monday-night games a day later than the schedule
    does (UTC vs ET), and Polymarket US slugs follow the schedule, so the matched
    schedule date is tried first and the slate date second."""
    out, games = {}, 0
    for g in slate_games:
        if not g.get("date") or not g.get("away") or not g.get("home"):
            continue
        dates = []
        sg = match_sched_game(g, sched) if sched else None
        if sg and sg.get("date"):
            dates.append(sg["date"])
        if g["date"] not in dates:
            dates.append(g["date"])
        ev = None
        for d in dates:
            try:
                raw = http_get(PMUS_BASE + "/v1/events/slug/"
                               + urllib.parse.quote(pmus_event_slug(g["away"], g["home"], d)),
                               timeout=45, tries=2)
                cand = (json.loads(raw) or {}).get("event") or {}
            except Exception:  # noqa: BLE001
                continue
            if cand.get("markets"):
                ev = cand
                break
        if ev is None:
            continue
        games += 1
        for m in ev.get("markets") or []:
            sk = PMUS_STAT.get(m.get("sportsMarketType"))
            who = ((m.get("subject") or {}).get("name")
                   or (m.get("metadata") or {}).get("playerName"))
            n = fnum(m.get("line"))
            if not sk or not who or n is None:
                continue
            if m.get("closed") or m.get("active") is False:
                continue
            if m.get("status") and m["status"] != "MARKET_STATUS_OPEN":
                continue
            bid, ask = _pmus_quote(m.get("bestBidQuote")), _pmus_quote(m.get("bestAskQuote"))
            over = ask
            under = (1 - bid) if bid is not None else None
            if over is None and under is None:
                continue
            out[(pkey(who), sk, round(n - 0.5, 1))] = {
                "over": int(round(over * 100)) if over is not None else None,
                "under": int(round(under * 100)) if under is not None else None,
                "slug": m.get("slug")}      # for its order book (depth.verify)
    return out, games


def fetch_slate():
    """Polymarket player-prop events in a [-1, +10] day window, with their markets."""
    events = json.loads(http_get(SLATE_URL))
    games = []
    for ev in events:
        m = SLUG_RE.match(ev.get("slug", ""))
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(3))
        except ValueError:
            continue
        if not (TODAY - datetime.timedelta(days=1) <= d <= TODAY + datetime.timedelta(days=10)):
            continue
        games.append({"slug": ev["slug"], "away": team_code(m.group(1)), "home": team_code(m.group(2)),
                      "date": m.group(3), "start": ev.get("startDate", ""), "title": ev.get("title", "")})
    games.sort(key=lambda g: (g["date"], g["slug"]))
    for g in games:
        try:
            ev = json.loads(http_get(EVENT_URL.format(slug=g["slug"])))
            g["markets"] = ev.get("markets", [])
        except Exception as e:  # noqa: BLE001
            print(f"    event {g['slug']}: skipped ({e})")
            g["markets"] = []
    return games


def match_sched_game(g, sched):
    """Polymarket slug (away, home, date) -> nflverse schedule game (date may differ by a day: time zones)."""
    try:
        d = datetime.date.fromisoformat(g["date"])
    except ValueError:
        return None
    best = None
    for sg in sched.values():
        if {sg["away"], sg["home"]} != {g["away"], g["home"]} or not sg["date"]:
            continue
        try:
            dd = abs((datetime.date.fromisoformat(sg["date"]) - d).days)
        except ValueError:
            continue
        if dd <= 1 and (best is None or dd < best[0]):
            best = (dd, sg)
    return best[1] if best else None


ET_ZONE = ZoneInfo("America/New_York")


def kickoff_utc(sg):
    """Kickoff as an aware UTC datetime from nflverse gameday + gametime (ET), or None
    when either is missing/unparseable — the caller then falls back to freezing at 'final'."""
    try:
        d, t = sg.get("date"), sg.get("time")
        if not d or not t:
            return None
        hh, mm = (t.split(":") + ["0"])[:2]
        kt = datetime.datetime.fromisoformat(d).replace(hour=int(hh), minute=int(mm), tzinfo=ET_ZONE)
        return kt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


# A pick locks when its game kicks off within LOCK_MIN minutes. The site updates about every
# 10 minutes, so that's 20-30 minutes before kickoff; from then on its lists, chance and price
# stay as published, and no new picks are added for the game.
LOCK_MIN = 30


def lock_picks(picks, sched):
    """Lock every pending live pick whose game kicks off within LOCK_MIN minutes, as published
    this run; "lk" records when (UTC). Returns how many locked."""
    now = datetime.datetime.now(datetime.timezone.utc)
    n = 0
    for p in picks:
        if p.get("src") != "live" or p.get("res") is not None or p.get("lk"):
            continue
        sg = sched.get(p.get("gid"))
        ko = kickoff_utc(sg) if sg else None
        if ko and now < ko <= now + datetime.timedelta(minutes=LOCK_MIN):
            p["lk"] = now.strftime("%Y-%m-%dT%H:%MZ")
            n += 1
    return n


def locked_rows(picks, sched):
    """The locked picks still on the board (kickoff ahead), for slate.json: the board shows
    these as published instead of re-pricing their games live. Prices are in cents."""
    now = datetime.datetime.now(datetime.timezone.utc)
    keep = ("gid", "pid", "team", "opp", "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "lk",
            "pp", "kp", "vn")
    out = []
    for p in picks:
        if p.get("src") == "live" and p.get("res") is None and p.get("lk"):
            ko = kickoff_utc(sched.get(p.get("gid")) or {})
            if ko and now < ko:
                out.append({k: p.get(k) for k in keep})
    return out


# ---------------------------------------------------------------------------
# Picks: live (from the Polymarket board, recorded before kickoff, graded after)
# and backtest (what the model would have picked each past week, graded).
# ---------------------------------------------------------------------------
PICK_COLS = ["src", "gid", "season", "week", "date", "pid", "player", "pos", "team", "opp",
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj",
             "px0", "pxc",   # px0/pxc: first and last pre-kickoff price, in cents (closing line value)
             "mv",           # model version the chance came from (MODEL_V)
             "nw",           # pre-game news, test mode (news.py): {"st", "wx", "roof", "p2"}
             "lk",           # when the pick locked (UTC; see lock_picks)
             "pp", "kp",     # this side's price on Polymarket and on Kalshi, in cents (None = not listed there)
             "pd", "kd",     # dollars offered within 2c of each (depth.py)
             "vn",           # which one "price" is: the cheaper with $25+ offered, "P" Polymarket, "K" Kalshi
             "th",           # 1 = thin: neither has $25 offered near its price, so no Value
             "hd"]           # what it waits on: injury news not settled yet (holds.py), so no lists
VALUE_MIN_NEFF = 6.0
TOP_N = 25
TOP_VERIFY = 80         # the surest priced props whose order books are read for Top 25 (it needs $25+ near the price)
VALUE_N = 200           # a safety cap only. At 50 it bound in busy weeks (NFL week 3: 27 picks that
                        # cleared the rule went unrecorded), so the record now holds every pick that clears it
# The Value bar, applied to each side of a market separately: the market itself has
# to give the prop at least a 30% chance (an ask of 30c or more) AND the model has to
# be at least 15 points above that -- so a 30c ask needs a 45% model chance, a 50c ask
# needs 65%. The price floor is what keeps penny longshots off the list.
# And no more than 20 points above: on the NFL record (97 graded Value picks to week 4,
# 2026) picks 15-20 points up hit 56% (+7.3 units, n=43) while bigger gaps hit 42%
# (-6.5 units, n=54) -- a gap that big has more often been the model missing a role change
# the market already priced than a real edge.
VALUE_MIN_PRICE = 0.30
VALUE_MIN_EDGE = 0.15
VALUE_MAX_EDGE = 0.20


def value_qualifies(prob, price):
    """prob and price are fractions. price is what you'd pay for this side."""
    if price is None:
        return False
    return price >= VALUE_MIN_PRICE and VALUE_MIN_EDGE <= prob - price <= VALUE_MAX_EDGE + 1e-9


BT_STATS = {"QB": ["pass_yds", "pass_td", "pass_cmp"], "RB": ["rush_yds", "rush_rec_yds", "rec"],
            "WR": ["rec_yds", "rec", "rec_td"], "TE": ["rec_yds", "rec", "rec_td"], "FB": ["rush_yds", "rec"]}
BT_MIN_PRIOR = 5
BT_MIN_YARDS_MEDIAN = 10


def load_picks():
    try:
        with open("picks.json", "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    cols = d.get("cols") or []
    return [dict(zip(cols, row)) for row in d.get("picks", [])]


def side_prob(mp):
    side = "over" if mp["over"] >= 0.5 else "under"
    if side == "over":
        return side, mp["over"], mp["lo"], mp["hi"]
    return side, mp["under"], 1 - mp["hi"], 1 - mp["lo"]


def make_pick(src, gid, season, week, date, pl, opp, sk, line, mp, price, rec, side=None, pp=None, kp=None,
              kd=None, refs=None):
    """side=None records the side the model leans; pass it explicitly to record the
    other side of the same market (a value spot can sit on either one). pp/kp are that
    side's Polymarket and Kalshi prices (cents), kd the dollars offered at Kalshi's, refs the
    books to read for depth ({"_ps": Polymarket US slug, "_kt": Kalshi ticker}); price is the
    cheaper of the two with enough money offered (depth.choose)."""
    fav, prob, lo, hi = side_prob(mp)
    if side is None:
        side = fav
    elif side != fav:
        prob, lo, hi = 1 - prob, 1 - hi, 1 - lo
    return {"src": src, "gid": gid, "season": season, "week": week, "date": date,
            "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": pl["t"], "opp": opp,
            "stat": sk, "line": line, "side": side,
            "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3), "neff": round(mp["neff"], 1),
            "price": price, "lists": "", "rec": rec, "actual": None, "res": None,
            "adj": round(mp.get("scale", 1.0), 3), "mv": MODEL_V,
            "pp": pp, "kp": kp, "pd": None, "kd": kd, "vn": kalshi.best(pp, kp)[1], **(refs or {})}


def assign_lists(picks, held=0):
    """T = the 25 highest model chances ('Top 25 Surest') you can bet, one line per player-prop. V = every prop the market
    prices at 30c or more that the model puts 15+ points higher, ranked by that edge.
    V is side-agnostic: an under qualifies whenever its own ask is the cheap one.
    `held` Top 25 slots stay with locked picks still on the board. Operates in place."""
    for p in picks:
        p["lists"] = ""
    # waiting on injury news (a questionable teammate in his position group, or himself): no lists
    picks = [p for p in picks if not p.get("hd")]
    # The model's widest gap over the price on any rung of a player-prop (one side): over
    # VALUE_MAX_EDGE on one rung, it's likely missing something about him this week (a role
    # change the market already priced), so no rung of that prop makes Top 25 or Value (on the
    # record, 15-20 point rungs of such props didn't pay either).
    widest = {}
    for p in picks:
        if p.get("price") is not None:
            k = (p["gid"], p["pid"], p["stat"], p.get("side"))
            widest[k] = max(widest.get(k, -1.0), p["prob"] - p["price"] / 100.0)
    wide = lambda p: widest.get((p["gid"], p["pid"], p["stat"], p.get("side")), -1.0) > VALUE_MAX_EDGE + 1e-9
    # Top 25: only props you can bet -- a live price with $25+ offered near it (depth.py; not
    # thin) -- one line per player-prop (its surest rung), none the model is that far off on
    ranked = sorted((p for p in picks if p["prob"] >= 0.5 and p.get("price") is not None and not p.get("th")
                     and not wide(p)), key=lambda p: (-p["prob"], -p["neff"]))
    seen = set()
    for p in ranked:
        k = (p["gid"], p["pid"], p["stat"])
        if k in seen:
            continue
        if len(seen) >= TOP_N - held:
            break
        seen.add(k)
        p["lists"] += "T"
    vals = []
    for p in picks:
        pr = p.get("price")
        if pr is None or p.get("th") or p["neff"] < VALUE_MIN_NEFF:
            continue
        price = pr / 100.0
        if value_qualifies(p["prob"], price) and not wide(p):
            vals.append((p["prob"] - price, p))
    vals.sort(key=lambda x: -x[0])
    seen, n = set(), 0          # one line per player-prop: a ladder's rungs are one opinion, not four picks
    for _, p in vals:
        k = (p["gid"], p["pid"], p["stat"])
        if k in seen or n >= VALUE_N:
            continue
        seen.add(k)
        p["lists"] += "V"
        n += 1


def kalshi_board(markets, names, sg_by_slug, picks=(), props=None):
    """For slate.json: "player key|stat|line" -> [over, under, over $, under $]: Kalshi prices in
    cents (None = no ask) and the dollars offered within 2c of each (the best level's, or the
    full book's where depth.verify read it for a pick), for the slate's players, in their game
    this week only — the board prices its props live off Polymarket US in the browser and
    shows these beside them. props: the (player key, stat, line) the board lists; only those."""
    read = {(pkey(p["player"]), p["stat"], float(p["line"]), p["side"]): p["kd"] for p in picks
            if p.get("src") == "live" and p.get("res") is None and p.get("kd") is not None}
    out = {}
    for k in markets or []:
        if not k.get("tradeable"):
            continue
        key = pkey(k["player"])
        if props is not None and (key, k["sk"], k["line"]) not in props:
            continue
        sg = sg_by_slug.get(names.get(key))
        if not sg or sg.get("date") != k["date"]:
            continue
        out[f"{key}|{k['sk']}|{k['line']}"] = (
            [int(round(k[sd] * 100)) if k[sd] is not None else None for sd in ("over", "under")]
            + [max(k["od" if sd == "over" else "ud"] or 0, read.get((key, k["sk"], k["line"], sd)) or 0)
               for sd in ("over", "under")])
    return out


def build_live_picks(picks, slate_games, sched, by_key, snap, pmus=None, kal=None):
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = []
    for g in slate_games:
        sg = match_sched_game(g, sched)
        if not sg or sg["final"]:
            continue
        # Freeze the recorded board at the lock (once kickoff is within LOCK_MIN minutes):
        # from then on stop refreshing its picks or adding new ones, so the board and Past picks hold
        # what was published at the lock. Unparseable kickoff -> old behavior (keep
        # refreshing until the game is final).
        ko = kickoff_utc(sg)
        if ko is not None and now_dt + datetime.timedelta(minutes=LOCK_MIN) >= ko:
            continue
        seen = set()
        for m in g.get("markets", []):
            pm = parse_market(m)
            if not pm:
                continue
            sk = mkt_stat_key(pm["statText"])
            if not sk:
                continue
            pl = by_key.get(pkey(pm["player"]))
            if not pl or not pl["g"]:
                continue
            key = (pl["id"], sk, pm["line"])
            if key in seen:
                continue
            seen.add(key)
            if pl["t"] == sg["away"]:
                opp, home = sg["home"], 0
            elif pl["t"] == sg["home"]:
                opp, home = sg["away"], 1
            else:
                opp, home = sg["away"] + "/" + sg["home"], None
            game_spr = None if (home is None or sg["spread"] is None) else (sg["spread"] if home else -sg["spread"])
            game_pts = None if (game_spr is None or sg["total"] is None) else sg["total"] / 2.0 + game_spr / 2.0
            fam = stat_family(sk, pl["p"])
            usage = None if inj_on(pl, sk) else usage_of(pl.get("u"))
            ctx = context_scale(fam, hist_context(pl["g"]), game_pts, game_spr,
                                def_ratio(snap, opp if home is not None else None, pl["p"], sk), usage)
            vals = [stat_value(sk, r) for r in model_rows(pl)]
            per = game_per(ctx["scale"], usage, (pl.get("u") or [None])[0], game_shares(pl["id"], pl["g"]), fam)
            mp = model_prob(vals, pm["line"], stat_kind(sk), ctx["scale"], CAL.get(sk), per)
            if not mp:
                continue
            fav = "over" if mp["over"] >= 0.5 else "under"
            pmc = {"over": None, "under": None}     # Polymarket
            if pm["tradeable"]:
                for sd in ("over", "under"):
                    pr = pm[sd]
                    pmc[sd] = int(round(pr * 100)) if pr is not None else None
            # Prefer the Polymarket US quote for the same prop at the same line -- the price
            # the site shows and the one you would actually pay -- whether or not the global
            # book is trading (on NFL props it mostly isn't, and gating on it hid nearly every
            # US price). An inexact line is a different bet, so it is never substituted.
            us = (pmus or {}).get((pkey(pm["player"]), sk, round(float(pm["line"]), 1)))
            if us:
                for sd in ("over", "under"):
                    if us[sd] is not None:
                        pmc[sd] = us[sd]
            # Kalshi, side by side: the same exact prop at the same line in this game, and the
            # cheaper of the two is the price the pick is judged on.
            ks = kalshi.find(kal, pkey(pm["player"]), sk, pm["line"], [sg["date"]]) if kal else None
            kc, kd, cents = {}, {}, {}
            for sd in ("over", "under"):
                kp = kalshi.side_price(ks, sd)
                kc[sd] = int(round(kp * 100)) if kp is not None else None
                kd[sd] = ks["od" if sd == "over" else "ud"] if kp is not None else None
                cents[sd] = kalshi.best(pmc[sd], kc[sd])[0]
            # Depth is read only for picks that could make Value (depth.verify, below): a US
            # price's book by its slug, Kalshi's by its ticker. The global book's isn't read, so
            # a price only it quotes never counts for Value (nor can US users trade there).
            refs = lambda sd: {"_ps": us.get("slug") if us and us[sd] is not None and us[sd] == pmc[sd] else None,
                               "_kt": ks["ticker"] if kc[sd] is not None else None}
            hd = hold_reason(pl, sk)
            fresh.append(make_pick("live", sg["id"], sg["season"], sg["week"], sg["date"], pl, opp,
                                   sk, pm["line"], mp, cents[fav], now, side=fav, pp=pmc[fav], kp=kc[fav],
                                   kd=kd[fav], refs=refs(fav)))
            fresh[-1]["hd"] = hd
            # The other side is recorded too when it's a plausible value play, so an
            # under can reach the Value list even though the model leans over (and
            # vice-versa). Only one side can ever clear: the two asks sum to at least
            # 1 while lo(over) + lo(under) = 1 - (hi - lo) < 1.
            other = "under" if fav == "over" else "over"
            op = cents[other]
            if op is not None and mp["neff"] >= VALUE_MIN_NEFF:
                if value_qualifies(mp[other], op / 100.0):
                    fresh.append(make_pick("live", sg["id"], sg["season"], sg["week"], sg["date"], pl, opp,
                                           sk, pm["line"], mp, op, now, side=other, pp=pmc[other], kp=kc[other],
                                           kd=kd[other], refs=refs(other)))
                    fresh[-1]["hd"] = hd
    held = 0       # Top 25 slots kept by locked picks whose game hasn't kicked off
    for p in picks:
        if p["src"] == "live" and p["res"] is None and p.get("lk") and "T" in (p.get("lists") or ""):
            ko = kickoff_utc(sched.get(p["gid"]) or {})
            held += bool(ko and now_dt < ko)
    # Enough money at the price? Every fresh pick's price is its cheaper exchange that has $25+
    # offered within 2c (depth.choose); the books of the ones that could make Value are read.
    for f in fresh:
        depth.choose(f)
    # ...and of the surest priced ones, which could make Top 25 (it needs $25+ near the price too)
    surest = {id(f) for f in sorted((f for f in fresh if f.get("price") is not None and not f.get("hd") and f["prob"] >= 0.5),
                                    key=lambda f: -f["prob"])[:TOP_VERIFY]}
    nb = depth.verify(fresh, lambda f: f.get("th") and (id(f) in surest or f["neff"] >= VALUE_MIN_NEFF and any(
        px is not None and value_qualifies(f["prob"], px / 100.0) for px in (f.get("pp"), f.get("kp")))))
    print(f"  depth: read {nb} order book(s); {sum(1 for f in fresh if f.get('th'))} of {len(fresh)} props "
          f"too thin for Value (under ${depth.MIN_USD:.0f} offered within 2c)")
    assign_lists(fresh, held)
    fresh_markets = {(f["gid"], f["pid"], f["stat"], f["line"]) for f in fresh}
    fresh_keys = {(f["gid"], f["pid"], f["stat"], f["line"], f["side"]) for f in fresh}
    # A market we just re-scanned may have flipped which side we carry. Drop the
    # stale pending row rather than leaving two sides of one market to be graded.
    picks[:] = [p for p in picks
                if not (p["src"] == "live" and p["res"] is None
                        and (p["gid"], p["pid"], p["stat"], p["line"]) in fresh_markets
                        and (p["gid"], p["pid"], p["stat"], p["line"], p["side"]) not in fresh_keys)]
    existing = {(p["gid"], p["pid"], p["stat"], p["line"], p["side"]): p for p in picks if p["src"] == "live"}
    added = updated = 0
    for f in fresh:
        key = (f["gid"], f["pid"], f["stat"], f["line"], f["side"])
        ex = existing.get(key)
        if ex is None:
            picks.append(f)
            note_price(f)
            added += 1
        elif ex["res"] is None:      # still pending: refresh to the latest pre-kickoff snapshot
            for k in ("side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "team", "opp", "adj",
                      "pp", "kp", "pd", "kd", "vn", "th", "hd"):
                ex[k] = f[k]
            note_price(ex)
            updated += 1
    return len(fresh), added, updated


def news_test(picks, sched, by_pid):
    """TEST MODE (news.py): on every pending live pick whose game hasn't kicked off, record
    ESPN's injury status for the player and, at outdoor stadiums, the forecast for kickoff,
    plus p2: the chance with the wind adjustment the backtest found, for the stats it moved.
    Nothing here changes a pick's chance or its lists."""
    inj = news.espn_injuries("football/nfl")
    status = {pkey(x["name"]): x["status"] for x in (inj or []) if x.get("name")}
    now = datetime.datetime.now(datetime.timezone.utc)
    n = nwx = 0
    for p in picks:
        if p.get("src") != "live" or p.get("res") is not None:
            continue
        sg = sched.get(p["gid"])
        ko = kickoff_utc(sg) if sg else None
        if not sg or sg["final"] or (ko is not None and ko <= now):
            continue
        nw = {"st": status.get(pkey(p["player"]))} if inj is not None else {}
        roof = sg.get("roof") or ""
        nw["roof"] = roof or "unknown"
        wind = 0.0 if roof in ("dome", "closed") else None
        if roof in ("outdoors", "open") and sg.get("stadium") in news.NFL_STADIUMS and ko is not None:
            wx = news.forecast(*news.NFL_STADIUMS[sg["stadium"]], ko.strftime("%Y-%m-%dT%H:%MZ"))
            if wx:
                nw["wx"] = wx
                wind = wx[1]
                nwx += 1
        pl = by_pid.get(p["pid"])
        # p2 only on picks this model version made, so it differs from prob by the news alone
        if wind is not None and p["stat"] in news.WIND_STATS and pl and p.get("adj") is not None and p.get("mv") == MODEL_V:
            scale = min(CTX["clampHi"], max(CTX["clampLo"], p["adj"] * news.wind_factor(wind)))
            usage = None if inj_on(pl, p["stat"]) else usage_of(pl.get("u"))
            per = game_per(p["adj"], usage, (pl.get("u") or [None])[0], game_shares(pl["id"], pl["g"]),
                           stat_family(p["stat"], pl["p"]))
            mp = model_prob([stat_value(p["stat"], r) for r in model_rows(pl)], p["line"], stat_kind(p["stat"]), scale,
                            CAL.get(p["stat"]), per)
            if mp:
                nw["p2"] = round(mp[p["side"]], 3)
        p["nw"] = nw
        n += 1
    print(f"  news test: recorded on {n} pending pick(s), {nwx} with a kickoff forecast")
    news.report(picks, "NFL wind")


def grade_picks(picks, sched, by_pid, stats_gids, espn_gids=frozenset()):
    n = 0
    for p in picks:
        if p["src"] != "live" or p["res"] is not None:
            continue
        g = sched.get(p["gid"])
        if not g or not g["final"] or p["gid"] not in stats_gids:
            continue   # wait until the box score is in the stats file, not just the schedule
        pl = by_pid.get(p["pid"])
        row = None
        if pl:
            row = next((r for r in pl["g"] if r[0] == p["season"] and r[1] == p["week"]), None)
        if row is None:
            if p["gid"] in espn_gids:
                continue   # ESPN fill may not include this player — wait for nflverse before calling it a DNP
            p["res"], p["actual"] = "dnp", None
        else:
            v = stat_value(p["stat"], row)
            p["actual"], p["res"] = v, grade_result(v, p["line"], p["side"])
        n += 1
    return n


def build_backtest(players, seasons_used, sched, snapshot):
    """Walk-forward: for every game from the second season on, what would the model
    have said the week before, using only earlier games (and only the defense numbers
    known before that week)? Lines are the site's seeded 'realistic' line (no market
    prices exist for the past)."""
    if len(seasons_used) < 2:
        return []
    start = seasons_used[1]
    by_wk_opp = {}
    for g in sched.values():
        by_wk_opp[(g["season"], g["week"], g["away"])] = g
        by_wk_opp[(g["season"], g["week"], g["home"])] = g
    out = []
    for pl in players:
        rows = pl["g"]
        stats = BT_STATS.get(pl["p"], [])
        for i, row in enumerate(rows):
            if row[0] < start or i < BT_MIN_PRIOR:
                continue
            prior = rows[:i]
            sg = by_wk_opp.get((row[0], row[1], row[2]))
            if sg:
                gid, date = sg["id"], sg["date"]
                team = sg["home"] if sg["away"] == row[2] else sg["away"]
            else:
                gid, date, team = f"{row[0]}_{row[1]:02d}_?", "", ""
            hist = hist_context(prior)
            shares = usage_shares(pl["id"], prior)
            usage = usage_of(shares)
            gsh = game_shares(pl["id"], prior)
            game_spr, game_tot = row[19], row[18]
            game_pts = None if (game_spr is None or game_tot is None) else game_tot / 2.0 + game_spr / 2.0
            snap = snapshot(row[0], row[1])
            for sk in stats:
                vals = [stat_value(sk, r) for r in prior]
                if stat_kind(sk) == "yards" and median(vals[-10:]) < BT_MIN_YARDS_MEDIAN:
                    continue
                line = seed_line(vals)
                fam = stat_family(sk, pl["p"])
                ctx = context_scale(fam, hist, game_pts, game_spr, def_ratio(snap, row[2], pl["p"], sk), usage)
                per = game_per(ctx["scale"], usage, shares and shares[0], gsh, fam)
                mp = model_prob(vals, line, stat_kind(sk), ctx["scale"], CAL.get(sk), per)
                if not mp:
                    continue
                pk = make_pick("bt", gid, row[0], row[1], date, dict(pl, t=team or pl["t"]), row[2], sk, line, mp, None, None)
                pk["pid"] = None          # only live picks need the id (for grading); keeps picks.json small
                v = stat_value(sk, row)
                pk["actual"], pk["res"] = v, grade_result(v, line, pk["side"])
                out.append(pk)
    by_week = {}
    for p in out:
        by_week.setdefault((p["season"], p["week"]), []).append(p)
    for group in by_week.values():
        assign_lists(group)
    return out


def fit_temperature(picks):
    """Learn a calibration 'temperature' from graded picks (backtest + live) by
    minimizing log-loss with a mild ridge toward no change. T>1 softens the model's
    overconfident chances, T<1 sharpens. Returns 1.0 (no change) until there's enough
    graded history. Applied to the live/displayed chances so the site keeps tuning its
    confidence to its own tracked results each week."""
    data = []
    for p in picks:      # the backtest is rebuilt each run; live picks count only from this model version
        if p.get("src") == "live" and p.get("mv") != MODEL_V:
            continue
        if p.get("res") in ("hit", "miss") and p.get("prob") is not None:
            pr = min(0.999, max(0.001, float(p["prob"])))
            data.append((math.log(pr / (1 - pr)), 1.0 if p["res"] == "hit" else 0.0))
    if len(data) < 400:
        return 1.0

    def loss(T):
        s = 30.0 * (T - 1.0) ** 2                      # mild ridge toward T=1
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
    """Season-to-date record of graded LIVE picks per recommendation list (shown on the site)."""
    out = {}
    for k in ("T", "V", "all"):
        ps = [p for p in picks if p["src"] == "live" and p["res"] in ("hit", "miss") and (k == "all" or k in (p["lists"] or ""))]
        hits = sum(1 for p in ps if p["res"] == "hit")
        priced = [p for p in ps if p.get("price")]
        roi = (sum((100.0 / p["price"] - 1) if p["res"] == "hit" else -1 for p in priced) / len(priced)) if priced else None
        out[k] = {"n": len(ps), "hit": hits, "roi": round(roi, 3) if roi is not None else None, "priced": len(priced),
                  **clv_stats(ps)}
    return out


def js_num(x):
    """A number as JavaScript prints it (4.0 -> "4"), for keys the page builds from its own numbers."""
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def note_price(p):
    """Closing line value: px0 keeps the first price a pick was recorded at and pxc the last
    one seen before kickoff (price itself goes None whenever a market stops trading)."""
    if p.get("price") is not None:
        if p.get("px0") is None:
            p["px0"] = p["price"]
        p["pxc"] = p["price"]


def clv_stats(ps, cents=1):
    """How the price of the side taken moved from a pick's first recording (px0) to the last
    price before kickoff (pxc), in cents (NFL prices already are). The market moving toward a
    pick (it got pricier) is the usual sign of a real edge, and it shows up long before a
    win/loss record does."""
    mv = [round((p["pxc"] - p["px0"]) * cents, 1) for p in ps
          if p.get("px0") is not None and p.get("pxc") is not None]
    return {"clvN": len(mv), "clvUp": sum(1 for m in mv if m >= 1), "clvDn": sum(1 for m in mv if m <= -1),
            "clv": round(sum(mv) / len(mv), 1) if mv else None}


def save_picks(picks):
    picks.sort(key=lambda p: (p["season"], p["week"], p["date"], p["player"], p["stat"], p["line"]))
    live = [p for p in picks if p["src"] == "live"]
    graded = [p for p in live if p["res"] in ("hit", "miss", "push")]
    doc = {"gen": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "model": MODEL, "cols": PICK_COLS,
           "summary": {"live": len(live), "livePending": sum(1 for p in live if p["res"] is None),
                       "liveGraded": len(graded), "backtest": sum(1 for p in picks if p["src"] == "bt")},
           "picks": [[p.get(c) for c in PICK_COLS] for p in picks]}
    with open("picks.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    return doc["summary"]


def write_weekly(picks):
    """Most recent week that has graded LIVE Value picks -> weekly.json, for the
    homepage 'units up' banner. Units = payout profit per 1u bet (win: 100/price-1, loss: -1)."""
    try:
        v = [p for p in picks if p["src"] == "live" and "V" in (p["lists"] or "") and p["res"] in ("hit", "miss")]
        if not v:
            return
        season = max(p["season"] for p in v)
        week = max(p["week"] for p in v if p["season"] == season)
        wk = [p for p in v if p["season"] == season and p["week"] == week]
        priced = [p for p in wk if p.get("price")]
        units = sum((100.0 / p["price"] - 1) if p["res"] == "hit" else -1 for p in priced)
        out = {"season": season, "week": week, "n": len(wk),
               "hit": sum(1 for p in wk if p["res"] == "hit"),
               "priced": len(priced), "units": round(units, 2)}
        with open("weekly.json", "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        print(f"  weekly.json: Week {week} value {out['hit']}/{out['n']} {out['units']:+}u")
    except Exception as e:
        print(f"  weekly.json: skipped ({e})")


# ---------------------------------------------------------------------------
def sanity_check(db):
    """Refuse to publish a dataset that shrank suspiciously versus the last build."""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return
    old_players = [p for p in old.get("players", []) if p.get("g")]
    new_players = [p for p in db["players"] if p["g"]]
    old_rows = sum(len(p["g"]) for p in old_players)
    new_rows = sum(len(p["g"]) for p in new_players)
    same_window = old.get("seasons") == db["seasons"]
    floor = 0.9 if same_window else 0.6
    if old_players and len(new_players) < floor * len(old_players):
        die(f"player count dropped {len(old_players)} -> {len(new_players)}; not publishing")
    if old_rows and new_rows < floor * old_rows:
        die(f"game rows dropped {old_rows} -> {new_rows}; not publishing")


def main():
    print(f"Season {SEASON} · candidate seasons {CANDIDATE_SEASONS}")
    print("Downloading nflverse weekly stats…")
    all_rows, seasons_used = [], []
    for y in CANDIDATE_SEASONS:
        rows = fetch_csv(STATS_URL.format(year=y), f"stats {y}")
        if rows:
            missing = REQUIRED - set(rows[0].keys())
            if missing:
                die(f"stats {y} is missing columns {sorted(missing)} — nflverse changed its format?")
            all_rows.extend(rows)
            seasons_used.append(y)
    if not all_rows:
        die("no data downloaded")
    stats_gids = {r.get("game_id") for r in all_rows if r.get("game_id")}
    nfl_index = {}                       # normalized name -> (player_id, position) for ESPN matching
    for r in all_rows:
        if r.get("position") in SKILL and r.get("player_id"):
            nfl_index[pkey(r.get("player_display_name") or "")] = (r.get("player_id"), r.get("position"))

    print("Downloading schedule, injuries, roster…")
    sched = load_schedule(set(CANDIDATE_SEASONS))
    injuries = load_injuries(SEASON)
    roster = load_roster(SEASON)

    espn_gids = set()
    try:
        nfl_gids = set(stats_gids)
        espn_rows = fetch_espn_recent(sched, stats_gids, nfl_index, SEASON)
        all_rows.extend(espn_rows)
        espn_gids = stats_gids - nfl_gids
        print(f"  ESPN: +{len(espn_rows)} player-rows from {len(espn_gids)} game(s) ahead of nflverse"
              if espn_rows else "  ESPN: nothing fresher to add (nflverse is current)")
    except Exception as e:  # noqa: BLE001
        print(f"  ESPN: skipped ({e}) — using nflverse only")

    players = build_players(all_rows, roster, injuries, sched)
    try:
        espn_inj = news.espn_injuries("football/nfl")     # lists Out / IR all week, ahead of nflverse
        n_out, n_q, n_adj, n_hold = compute_injury_boosts(players, espn_inj, sched)
        print(f"  next man up: {n_out} out, {n_q} questionable or doubtful"
              f"{'' if espn_inj is not None else ' (ESPN report unavailable: nflverse and rosters only)'},"
              f" {n_adj} teammate(s) handed work, {n_hold} player(s) waiting on news (no Top 25 / Value)")
    except Exception as e:  # noqa: BLE001
        print(f"  next man up: skipped ({e})")
    try:
        SNAPS.update(load_snaps(CANDIDATE_SEASONS))
        n_u = 0
        for p in players:
            u = usage_shares(p["id"], p["g"]) if p["g"] else None
            if u:
                p["u"] = u               # [recent, usual] snap share, for the page's model
                n_u += 1
                for r, sh in zip(p["g"], game_shares(p["id"], p["g"])):
                    r.append(sh)         # column 20, for the page's game_per
        print(f"  snap counts: {len(SNAPS)} player-games, usage for {n_u} player(s)")
    except Exception as e:  # noqa: BLE001
        SNAPS.clear()
        print(f"  snap counts: skipped ({e}) — no usage adjustment")
    with_games = [p for p in players if p["g"]]
    latest = (0, 0, "REG")
    for p in with_games:
        last = p["g"][-1]
        if (last[0], last[1]) > (latest[0], latest[1]):
            latest = (last[0], last[1], last[3])
    thru = f"{latest[0]} playoffs" if latest[2] == "POST" else f"{latest[0]} · Week {latest[1]}"

    wk = current_week(sched, SEASON)
    week_games = sorted([g for g in sched.values() if g["season"] == SEASON and g["week"] == wk],
                        key=lambda g: (g["date"], g["time"])) if wk else []
    snapshot = build_def_timeline(all_rows, set(CANDIDATE_SEASONS))
    defense, def_avg, def_note = rank_defense(snapshot(SEASON), SEASON)

    # ---- picks ----
    by_pid = {p["id"]: p for p in players}
    by_key = {}
    for p in players:            # on a name collision prefer the player with a game log
        k = pkey(p["n"])
        if k not in by_key or (not by_key[k]["g"] and p["g"]):
            by_key[k] = p
    picks = [p for p in load_picks() if p.get("src") == "live"]
    graded = grade_picks(picks, sched, by_pid, stats_gids, espn_gids)
    print(f"Picks: graded {graded} live pick(s).")

    slate_games = None
    try:
        slate_games = fetch_slate()
    except Exception as e:  # noqa: BLE001
        print(f"  slate: skipped ({e}) — keeping existing slate.json; no new live picks this run")
    if slate_games is not None:
        pmus, pmus_games = {}, 0
        try:
            pmus, pmus_games = fetch_pmus_prices(slate_games, sched)
        except Exception as e:  # noqa: BLE001
            print(f"  polymarket us: skipped ({e}) — pricing picks off the global book")
        if pmus_games:
            print(f"  polymarket us: {len(pmus)} prop prices from {pmus_games} game(s)")
        try:
            kal_mkts = kalshi.fetch("nfl", days=8)
        except Exception as e:  # noqa: BLE001
            print(f"  kalshi: skipped ({e})")
            kal_mkts = None
        kal = kalshi.index(kal_mkts, pkey) if kal_mkts else None
        total, added, updated = build_live_picks(picks, slate_games, sched, by_key, snapshot(SEASON), pmus, kal)
        print(f"  slate: {len(slate_games)} games, {total} props modeled ({added} new, {updated} refreshed)")
        locked = lock_picks(picks, sched)
        if locked:
            print(f"  picks: locked {locked} pick(s) whose game kicks off within {LOCK_MIN} minutes")
        names, props = {}, set()
        for g in slate_games:
            for m in g.get("markets", []):
                pm = parse_market(m)
                if pm:
                    names.setdefault(pkey(pm["player"]), g["slug"])
                    props.add((pkey(pm["player"]), mkt_stat_key(pm["statText"]), round(float(pm["line"]), 1)))
        sg_by_slug = {g["slug"]: match_sched_game(g, sched) for g in slate_games}
        slate = {"gen": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "games": [{"slug": g["slug"], "away": g["away"], "home": g["home"], "date": g["date"],
                            "start": g["start"], "title": g["title"],
                            "gid": (sg_by_slug[g["slug"]] or {}).get("id")} for g in slate_games],
                 "players": names,
                 "locked": locked_rows(picks, sched),
                 "kalshi": kalshi_board(kal_mkts, names, sg_by_slug, picks, props)}
        with open("slate.json", "w", encoding="utf-8") as f:
            json.dump(slate, f, separators=(",", ":"), ensure_ascii=False)

    try:
        news_test(picks, sched, by_pid)
    except Exception as e:  # noqa: BLE001
        print(f"  news test: step unavailable ({e})")

    bt = build_backtest(with_games, seasons_used, sched, snapshot)
    summary = save_picks(picks + bt)
    print(f"  picks.json: {summary}")
    write_weekly(picks + bt)

    try:
        cal_t = fit_temperature(picks + bt)
    except Exception as e:  # noqa: BLE001
        print(f"  calibration: skipped ({e})")
        cal_t = 1.0
    print(f"  calibration temperature: T={cal_t}")

    try:
        team_top = fetch_team_top(sched, SEASON)
    except Exception as e:  # noqa: BLE001
        print(f"  time of possession: skipped ({e})")
        team_top = {}
    print(f"  time of possession: {len(team_top)} teams")

    db = {
        "gen": TODAY.isoformat(),
        "seasons": seasons_used,
        "thru": thru,
        "season": SEASON,
        "week": {"season": SEASON, "week": wk, "games": week_games},
        "injWeek": next(iter(injuries.values()))[3] if injuries else None,
        "defNote": def_note,
        "defense": defense,
        "defAvg": def_avg,
        "calT": cal_t,
        "top": team_top,
        "record": live_record(picks),
        # first recorded price (cents) of every pending pick, so the board can show how far the
        # live price has moved since: "pid|stat|line|side" -> px0
        "open": {f"{p['pid']}|{p['stat']}|{js_num(p['line'])}|{p['side']}": p["px0"] for p in picks
                 if p["src"] == "live" and p["res"] is None and p.get("px0") is not None},
        "players": players,
    }
    sanity_check(db)
    payload = json.dumps(db, separators=(",", ":"), ensure_ascii=False)
    with open("data.json", "w", encoding="utf-8") as f:
        f.write(payload)
    with open("template.html", "r", encoding="utf-8") as f:
        template = f.read()
    if "__DATA__" not in template:
        die("template.html is missing the __DATA__ placeholder")
    # The NFL page lives at nfl.html; index.html is the static home page (not generated).
    with open("nfl.html", "w", encoding="utf-8") as f:
        f.write(template.replace("__DATA__", payload))

    # SEO: sitemap (with a fresh lastmod each build) and robots.txt.
    site = "https://propstreaklab.com"
    pages = [("/", "daily", "1.0"), ("/nfl.html", "daily", "0.9"), ("/nba.html", "daily", "0.9"),
             ("/nhl.html", "daily", "0.9"), ("/mlb.html", "daily", "0.9"), ("/methodology.html", "monthly", "0.6"), ("/privacy.html", "monthly", "0.3"),
             ("/terms.html", "monthly", "0.3"), ("/cookies.html", "monthly", "0.3")]
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for path, freq, prio in pages:
            f.write(f"  <url>\n    <loc>{site}{path}</loc>\n"
                    f"    <lastmod>{TODAY.isoformat()}</lastmod>\n"
                    f"    <changefreq>{freq}</changefreq>\n    <priority>{prio}</priority>\n  </url>\n")
        f.write("</urlset>\n")
    with open("robots.txt", "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {site}/sitemap.xml\n")

    print(f"Data: {len(with_games)} players with games ({len(players)} total), seasons {seasons_used}, "
          f"through {thru}; week {wk} has {len(week_games)} games; {len(injuries)} injury reports.")

    print("Done.")


if __name__ == "__main__":
    main()

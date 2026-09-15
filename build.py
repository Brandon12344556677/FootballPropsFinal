#!/usr/bin/env python3
"""
Prop Streak Lab — data builder.

Downloads nflverse public data (weekly player stats, schedule, injury reports,
rosters), builds the compact dataset the site runs on, records and grades the
site's picks, and injects the dataset into template.html to produce index.html.

Python 3 standard library only — nothing to install. Run locally: python build.py

Outputs
  data.json   player game logs, this week's schedule, injuries, defense ranks
  index.html  template.html with data.json baked in (the website)
  slate.json  this week's Polymarket player-prop events (for the live board scan)
  picks.json  every pick the site has made (live + backtest), graded as games finish

The probability model here is mirrored line-for-line in template.html (the block
marked "MODEL"). tests/test_model.py checks the two agree. Change both or neither.
"""
import csv, io, json, math, os, re, sys, time, datetime, unicodedata, urllib.request

TODAY = datetime.date.today()


def season_year(d):
    """NFL season label. Sep-Feb games belong to the year the season started."""
    return d.year if d.month >= 8 else d.year - 1


SEASON = season_year(TODAY)
CANDIDATE_SEASONS = [SEASON - 2, SEASON - 1, SEASON]   # 3 seasons so "last 20" has depth

SKILL = {"QB", "RB", "WR", "TE", "FB"}
BASE = "https://github.com/nflverse/nflverse-data/releases/download/"
STATS_URL = BASE + "stats_player/stats_player_week_{year}.csv"
SCHED_URL = BASE + "schedules/games.csv"
INJ_URL = BASE + "injuries/injuries_{year}.csv"
ROSTER_URL = BASE + "rosters/roster_{year}.csv"
UA = {"User-Agent": "prop-streak-lab/2.0"}

# ESPN public box scores — a near-real-time fill for current-season games the
# schedule already shows final but that nflverse hasn't published weekly stats
# for yet (nflverse lags 1-2 days). Unofficial but stable and free.
ESPN_SB = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={season}&seasontype=2&week={week}"
ESPN_SUM = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event}"

# ---------------------------------------------------------------------------
# Game-row layout. The front-end reads rows by index — keep in sync with template.html.
#   0 season  1 week  2 opp  3 type(REG/POST)
#   4 pass_yds 5 pass_td 6 pass_att 7 pass_cmp 8 pass_int
#   9 rush_att 10 rush_yds 11 rush_td 12 rec 13 tgt 14 rec_yds 15 rec_td
#   16 home(1/0)  17 target_share (0-1)
#   18 Vegas total for that game (or null)  19 spread for the player's team (+ = favored, or null)
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


def stat_kind(key):
    return "count" if key in COUNT_STATS else "yards"


# ---------------------------------------------------------------------------
# MODEL — mirrored in template.html. Keep both identical.
#
# Instead of a raw "hit 7 of last 10" frequency, the chance of clearing a line is
# estimated from the *distribution* of the player's recent values:
#   1. take up to the last 20 games, weight recent ones more (half-life 6 games);
#   2. smooth the weighted values with a Gaussian kernel (Silverman bandwidth, with
#      a floor so a run of identical values still has spread);
#   3. read P(over) / P(under) / P(push) off that smoothed distribution;
#   4. shrink toward 50/50 by half a pseudo-game, so tiny samples can't claim 100%;
#   5. attach an 80% Wilson interval sized by the *effective* sample (weights).
# ---------------------------------------------------------------------------
MODEL = {"halfLife": 6.0, "maxGames": 20, "priorK": 0.5, "bwConst": 0.9, "bwFloorCount": 0.35, "bwFloorYards": 1.0, "z": 1.2816}

# Game-context adjustment. The player's distribution is scaled by
#   (this game's implied team points / their usual implied points) ^ betaPts
#   * exp(betaSpr * (spread swing in TDs))          (favorites run more, underdogs pass more)
#   * (opponent's allowed-per-game / league average) ^ gamma
# Strengths were fitted on the walk-forward backtest (tools/tune_context.py) and
# validated on held-out weeks. 0 = adjustment off. Clamped to [clampLo, clampHi].
CTX = {"betaPts": {"pass": 0.25, "rush": 0.25, "rec": 0.25},
       "betaSpr": {"pass": 0.0, "rush": 0.0, "rec": 0.0},
       "gamma": {"pass": 0.75, "rush": 0.25, "rec": 0.5},
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


def model_prob(values, line, kind, scale=1.0):
    """values oldest -> newest; scale multiplies every value (game-context adjustment).
    Returns dict with over/under/push probabilities, an 80% interval on P(over),
    the effective sample size and moments, or None."""
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
    floor = MODEL["bwFloorCount"] if kind == "count" else MODEL["bwFloorYards"]
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
    nq = neff + k
    z = MODEL["z"]
    z2 = z * z
    c = (p + z2 / (2 * nq)) / (1 + z2 / nq)
    hw = z * math.sqrt(p * (1 - p) / nq + z2 / (4 * nq * nq)) / (1 + z2 / nq)
    return {"over": p, "under": 1.0 - p, "push": push, "lo": max(0.0, c - hw), "hi": min(1.0, c + hw),
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


def context_scale(fam, hist, game_pts, game_spr, def_ratio):
    """Multiplier for the player's distribution in this game. Missing inputs -> no change."""
    env = 1.0
    if hist["pts"] and game_pts and hist["pts"] > 0 and game_pts > 0:
        env *= (game_pts / hist["pts"]) ** CTX["betaPts"][fam]
    if hist["spr"] is not None and game_spr is not None:
        env *= math.exp(CTX["betaSpr"][fam] * (game_spr - hist["spr"]) / 7.0)
    dfs = 1.0
    if def_ratio and def_ratio > 0:
        dfs = def_ratio ** CTX["gamma"][fam]
    scale = min(CTX["clampHi"], max(CTX["clampLo"], env * dfs))
    return {"scale": scale, "env": env, "def": dfs}


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


# ---------------------------------------------------------------------------
# Picks: live (from the Polymarket board, recorded before kickoff, graded after)
# and backtest (what the model would have picked each past week, graded).
# ---------------------------------------------------------------------------
PICK_COLS = ["src", "gid", "season", "week", "date", "pid", "player", "pos", "team", "opp",
             "stat", "line", "side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "actual", "res", "adj"]
VALUE_MIN_NEFF = 6.0
TOP_N = 25
VALUE_N = 25
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


def make_pick(src, gid, season, week, date, pl, opp, sk, line, mp, price, rec):
    side, prob, lo, hi = side_prob(mp)
    return {"src": src, "gid": gid, "season": season, "week": week, "date": date,
            "pid": pl["id"], "player": pl["n"], "pos": pl["p"], "team": pl["t"], "opp": opp,
            "stat": sk, "line": line, "side": side,
            "prob": round(prob, 3), "lo": round(lo, 3), "hi": round(hi, 3), "neff": round(mp["neff"], 1),
            "price": price, "lists": "", "rec": rec, "actual": None, "res": None,
            "adj": round(mp.get("scale", 1.0), 3)}


def assign_lists(picks):
    """T = the 25 highest model chances ('25 Guaranteed'), V = the 25 best expected values
    at a real market price (the interval must clear the price). Operates in place."""
    for p in picks:
        p["lists"] = ""
    ranked = sorted(picks, key=lambda p: (-p["prob"], -p["neff"]))
    for p in ranked[:TOP_N]:
        p["lists"] += "T"
    vals = []
    for p in picks:
        pr = p.get("price")
        if pr is None or p["neff"] < VALUE_MIN_NEFF:
            continue
        price = pr / 100.0
        if p["lo"] > price:
            vals.append((p["prob"] / price - 1.0, p))
    vals.sort(key=lambda x: -x[0])
    for _, p in vals[:VALUE_N]:
        p["lists"] += "V"


def build_live_picks(picks, slate_games, sched, by_key, snap):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = []
    for g in slate_games:
        sg = match_sched_game(g, sched)
        if not sg or sg["final"]:
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
            ctx = context_scale(stat_family(sk, pl["p"]), hist_context(pl["g"]), game_pts, game_spr,
                                def_ratio(snap, opp if home is not None else None, pl["p"], sk))
            vals = [stat_value(sk, r) for r in pl["g"]]
            mp = model_prob(vals, pm["line"], stat_kind(sk), ctx["scale"])
            if not mp:
                continue
            side = "over" if mp["over"] >= 0.5 else "under"
            price = None
            if pm["tradeable"]:
                pr = pm["over"] if side == "over" else pm["under"]
                price = int(round(pr * 100)) if pr is not None else None
            fresh.append(make_pick("live", sg["id"], sg["season"], sg["week"], sg["date"], pl, opp,
                                   sk, pm["line"], mp, price, now))
    assign_lists(fresh)
    existing = {(p["gid"], p["pid"], p["stat"], p["line"]): p for p in picks if p["src"] == "live"}
    added = updated = 0
    for f in fresh:
        key = (f["gid"], f["pid"], f["stat"], f["line"])
        ex = existing.get(key)
        if ex is None:
            picks.append(f)
            added += 1
        elif ex["res"] is None:      # still pending: refresh to the latest pre-kickoff snapshot
            for k in ("side", "prob", "lo", "hi", "neff", "price", "lists", "rec", "team", "opp", "adj"):
                ex[k] = f[k]
            updated += 1
    return len(fresh), added, updated


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
            game_spr, game_tot = row[19], row[18]
            game_pts = None if (game_spr is None or game_tot is None) else game_tot / 2.0 + game_spr / 2.0
            snap = snapshot(row[0], row[1])
            for sk in stats:
                vals = [stat_value(sk, r) for r in prior]
                if stat_kind(sk) == "yards" and median(vals[-10:]) < BT_MIN_YARDS_MEDIAN:
                    continue
                line = seed_line(vals)
                ctx = context_scale(stat_family(sk, pl["p"]), hist, game_pts, game_spr, def_ratio(snap, row[2], pl["p"], sk))
                mp = model_prob(vals, line, stat_kind(sk), ctx["scale"])
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


def live_record(picks):
    """Season-to-date record of graded LIVE picks per recommendation list (shown on the site)."""
    out = {}
    for k in ("T", "V", "all"):
        ps = [p for p in picks if p["src"] == "live" and p["res"] in ("hit", "miss") and (k == "all" or k in (p["lists"] or ""))]
        hits = sum(1 for p in ps if p["res"] == "hit")
        priced = [p for p in ps if p.get("price")]
        roi = (sum((100.0 / p["price"] - 1) if p["res"] == "hit" else -1 for p in priced) / len(priced)) if priced else None
        out[k] = {"n": len(ps), "hit": hits, "roi": round(roi, 3) if roi is not None else None, "priced": len(priced)}
    return out


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
        total, added, updated = build_live_picks(picks, slate_games, sched, by_key, snapshot(SEASON))
        print(f"  slate: {len(slate_games)} games, {total} props modeled ({added} new, {updated} refreshed)")
        names = {}
        for g in slate_games:
            for m in g.get("markets", []):
                pm = parse_market(m)
                if pm:
                    names.setdefault(pkey(pm["player"]), g["slug"])
        sg_by_slug = {g["slug"]: match_sched_game(g, sched) for g in slate_games}
        slate = {"gen": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "games": [{"slug": g["slug"], "away": g["away"], "home": g["home"], "date": g["date"],
                            "start": g["start"], "title": g["title"],
                            "gid": (sg_by_slug[g["slug"]] or {}).get("id")} for g in slate_games],
                 "players": names}
        with open("slate.json", "w", encoding="utf-8") as f:
            json.dump(slate, f, separators=(",", ":"), ensure_ascii=False)

    bt = build_backtest(with_games, seasons_used, sched, snapshot)
    summary = save_picks(picks + bt)
    print(f"  picks.json: {summary}")

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
        "record": live_record(picks),
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
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(template.replace("__DATA__", payload))
    print(f"Data: {len(with_games)} players with games ({len(players)} total), seasons {seasons_used}, "
          f"through {thru}; week {wk} has {len(week_games)} games; {len(injuries)} injury reports.")

    print("Done.")


if __name__ == "__main__":
    main()

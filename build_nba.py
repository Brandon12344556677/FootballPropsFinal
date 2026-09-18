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

ESPN_SB = ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
           "scoreboard?dates={date}&limit=100")
ESPN_SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event}"

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


def _ma(s):
    """Parse ESPN 'made-attempted' cells like '10-19' -> (10, 19)."""
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", str(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


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


def parse_box(summ, season, date_iso, stype, home, away):
    """One ESPN summary -> stat row dicts for every player who logged minutes."""
    rows = []
    for tb in (summ.get("boxscore") or {}).get("players") or []:
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
                sb = get_json(ESPN_SB.format(date=date_iso.replace("-", "")))
            except Exception as e:  # noqa: BLE001
                print(f"    scoreboard {date_iso}: skipped ({e})")
                continue
            complete_date = True
            for ev in sb.get("events", []):
                gid = str(ev.get("id") or "")
                if not gid or gid in seen:
                    continue
                comp = (ev.get("competitions") or [{}])[0]
                status = ((comp.get("status") or {}).get("type") or {})
                if not status.get("completed"):
                    complete_date = False       # a game that day isn't final yet
                    continue
                if added >= MAX_NEW_GAMES or over_budget():
                    complete_date = False        # ran out of budget before finishing this date
                    break
                cs = comp.get("competitors") or []
                home = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "home"), None))
                away = team_code(next((c.get("team", {}).get("abbreviation") for c in cs if c.get("homeAway") == "away"), None))
                if not home or not away:
                    continue
                stype = "PST" if (ev.get("season") or {}).get("type") == 3 else "REG"
                d0 = (ev.get("date") or "")[:10]
                date_g = d0 if re.match(r"\d{4}-\d{2}-\d{2}", d0) else date_iso
                try:
                    summ = get_json(ESPN_SUM.format(event=gid))
                except Exception as e:  # noqa: BLE001
                    print(f"    summary {gid}: skipped ({e})")
                    complete_date = False
                    continue
                rows = parse_box(summ, season, date_g, stype, home, away)
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
    games = []
    for i in range(0, 8):
        if over_budget():
            break
        d = (TODAY + datetime.timedelta(days=i))
        try:
            sb = get_json(ESPN_SB.format(date=d.isoformat().replace("-", "")))
        except Exception as e:  # noqa: BLE001
            print(f"    slate {d}: skipped ({e})")
            continue
        for ev in sb.get("events", []):
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
            odds = (comp.get("odds") or [{}])
            if odds:
                o = odds[0]
                total = o.get("overUnder")
                sp = o.get("spread")
                if sp is not None:
                    # ESPN 'spread' is the home line (negative = home favored);
                    # store as the home team's spread with + = favored.
                    try:
                        spread = -float(sp)
                    except (TypeError, ValueError):
                        spread = None
            start = ev.get("date") or ""
            tm = ""
            m = re.search(r"T(\d{2}):(\d{2})", start)
            if m:
                # ESPN times are UTC (Z). Convert to ET (UTC-4/-5 — use -4, in-season).
                hh = (int(m.group(1)) - 4) % 24
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
    for p in picks:
        p["lists"] = ""
    ranked = sorted([p for p in picks if p.get("res") is None],
                    key=lambda p: (-p["prob"], -p["neff"]))
    for p in ranked[:TOP_N]:
        p["lists"] += "T"


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


def probe():
    """One-off shape check for the cdn.espn.com endpoints that work from CI."""
    print("  --- cdn shape probe ---")
    try:
        sb = get_json("https://cdn.espn.com/core/nba/scoreboard?xhr=1&dates=20260310")
        print(f"    SB top keys: {_keys(sb)}")
        content = sb.get("content", {})
        print(f"    SB content keys: {_keys(content)}")
        sbd = content.get("sbData", {})
        print(f"    SB sbData keys: {_keys(sbd)}")
        events = sbd.get("events", [])
        print(f"    SB events: {len(events)}")
        if events:
            ev = events[0]
            print(f"    SB event keys: {_keys(ev)} id={ev.get('id')}")
            comp = (ev.get("competitions") or [{}])[0]
            print(f"    SB comp keys: {_keys(comp)}")
            print(f"    SB status: {(comp.get('status') or {}).get('type')}")
            print(f"    SB odds: {comp.get('odds')}")
            cs = comp.get("competitors") or []
            print(f"    SB competitor0 keys: {_keys(cs[0]) if cs else 'none'}")
            gid = ev.get("id")
            bx = get_json(f"https://cdn.espn.com/core/nba/boxscore?xhr=1&gameId={gid}")
            print(f"    BOX top keys: {_keys(bx)}")
            gpj = bx.get("gamepackageJSON") or bx.get("content", {}).get("gamepackageJSON") or {}
            print(f"    BOX gpj keys: {_keys(gpj)}")
            box = gpj.get("boxscore", {})
            print(f"    BOX boxscore keys: {_keys(box)}")
            players = box.get("players", [])
            print(f"    BOX players teams: {len(players)}")
            if players:
                tb = players[0]
                print(f"    BOX team0 keys: {_keys(tb)} team={(tb.get('team') or {}).get('abbreviation')}")
                stcats = tb.get("statistics") or []
                print(f"    BOX stat cats: {len(stcats)}")
                if stcats:
                    c0 = stcats[0]
                    print(f"    BOX cat keys: {_keys(c0)}")
                    print(f"    BOX labels: {c0.get('labels')}")
                    print(f"    BOX names: {c0.get('names')}")
                    ath = c0.get("athletes") or []
                    if ath:
                        a0 = ath[0]
                        print(f"    BOX athlete keys: {_keys(a0)}")
                        print(f"    BOX athlete.athlete keys: {_keys(a0.get('athlete') or {})}")
                        print(f"    BOX athlete stats: {a0.get('stats')}")
                        print(f"    BOX starter={a0.get('starter')} dnp={a0.get('didNotPlay')}")
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"    PROBE ERROR: {e}\n{traceback.format_exc()}")
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
    for p in players:
        players_by_team.setdefault(p["t"], []).append(p)
    defense, defavg, dgames = build_defense(store["rows"], cur_season)

    picks = load_picks()
    graded = grade_picks(picks, by_pid)
    added_picks = build_board_picks(picks, slate, players_by_team, defense, defavg)
    assign_lists(picks)
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

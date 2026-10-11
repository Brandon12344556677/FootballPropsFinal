"""
Prop Streak Lab — today.json for the home page's cross-sport "Today" feed.

Runs after the four sport builders. Reads what they already wrote (each sport's
picks file, its dataset's season record, and the stat labels from its template)
and writes a small file the home page can fetch in one request:

  today.json   {"gen", "record": {sport: {"T", "V"}}, "picks": [...], "valueLive": [[sport, start], ...],
                "tracked": {"graded": live picks graded so far, "since": first live pick date},
                "fair": {"w": model weight in the fair chance, "n": priced picks it was fitted on},
                "last": {sport: {"day", "T": {n, hit}, "V": {n, hit, units}}}: each sport's latest graded day,
                "calib": [{"lo", "hi", "n", "said", "hit"}]: hit rate by model chance (home page chart),
                "streaks", "moves": home page cards (hot streaks; prices moving toward a pick)}
               (each pick carries "l10": its last ten game values, for the mini chart)

"picks" holds the best upcoming bets across all four sports at the last recorded
Polymarket price: Value spots first (ranked by edge over the price), then, if there
are too few of those, the likeliest picks that still pay (price 85¢ or less). One
pick per player. The home page drops any whose game has started since.

It also updates botd.json, the home page's Bet of the Day (botd.py), from the same
upcoming picks, and writes nba/nhl/mlb_picks_recent.json (pending picks plus the last
RECENT_DAYS days) for the boards' first load.

Standard library only. Never fails the deploy: a sport whose files are missing is
skipped, and a failure leaves the previous today.json in place.
"""
import datetime
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

import botd

SPORTS = [
    # sport, dataset (has "record"), picks file, template (has the stat labels)
    ("nfl", "data.json", "picks.json", "template.html"),
    ("nba", "nba.json", "nba_picks.json", "nba_template.html"),
    ("nhl", "nhl.json", "nhl_picks.json", "nhl_template.html"),
    ("mlb", "mlb.json", "mlb_picks.json", "mlb_template.html"),
]
OUT = "today.json"
SEARCH_OUT = "search.json"   # the home page player search: [sport, id, name, team, pos] per player
MAX_PICKS = 12          # the page shows up to 6; spares cover games that start before the next build
SAFE_MAX_PRICE = 0.85   # "still pays": at least ~1.18x
PER_SPORT = 3           # per sport, before the other sports have had their turn
ET = ZoneInfo("America/New_York")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def stat_labels(template):
    """{key: label} from the template's STATS list, so labels match the sport page."""
    with open(template, "r", encoding="utf-8") as f:
        src = f.read()
    return dict(re.findall(r"\{key:'(\w+)',\s*label:'([^']+)'", src))


def stat_getters(template):
    """{key: row -> value} from the template's STATS list, so the last-10 values on the home
    page use the same per-game formulas as the sport page. They're plain sums of box-score
    columns (g[4]+g[10], 0.04*g[4]+...); anything else is skipped rather than evaluated."""
    with open(template, "r", encoding="utf-8") as f:
        src = f.read()
    out = {}
    for key, expr in re.findall(r"\{key:'(\w+)',[^}]*?get:g=>([^}]+?)\s*\}", src):
        if not re.fullmatch(r"[\dg\[\]\s+\-*.]+", expr):
            continue
        code = compile(expr, "<stat>", "eval")
        out[key] = lambda g, code=code: eval(code, {"__builtins__": {}}, {"g": g})
    return out


MLB_PITCH = {"k", "outs", "ha", "er", "pbb"}


def mlb_games(rows, stat):
    """MLB's statGames(): pitching props count starts (or any outing when there are too few
    starts), hitting props count lineup starts (or any game) — as on the MLB page."""
    col, need = (20, 3) if stat in MLB_PITCH else (19, 5)
    starts = [g for g in rows if len(g) > col and g[col] == 2]
    return starts if len(starts) >= need else [g for g in rows if len(g) > col and (g[col] or 0) >= 1]


def last10(sport, player, stat, getters):
    get = getters.get(stat)
    if not player or not get:
        return []
    rows = player.get("g") or []
    if sport == "mlb":
        rows = mlb_games(rows, stat)
    out = []
    for g in rows[-10:]:
        try:
            out.append(round(float(get(g)), 2))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def nfl_kickoffs(db):
    """NFL picks carry no start time; the week's schedule has date + time in ET."""
    out = {}
    for g in (db.get("week") or {}).get("games") or []:
        if g.get("date") and g.get("time"):
            t = datetime.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
            out[g["id"]] = t.astimezone(datetime.timezone.utc)
    return out


def parse_start(s):
    # No start time (NHL preseason picks are saved without one): skipped, since the feed
    # promises picks leave it at puck drop and a date alone can't keep that promise.
    if not s:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def record(db):
    """The season record the sport page shows, as {tag: {n, hit, priced, units}}."""
    out = {}
    for tag, r in (db.get("record") or {}).items():
        if tag not in ("T", "V") or not r.get("n"):
            continue
        units = r.get("units")
        if units is None and r.get("roi") is not None and r.get("priced"):
            units = r["roi"] * r["priced"]      # the NFL builder stores ROI instead of units
        out[tag] = {"n": r["n"], "hit": r["hit"], "priced": r.get("priced") or 0,
                    "units": round(units, 2) if units is not None else None}
    return out


def cap(p):
    """No chance above 99% (or below 1%), even on picks recorded before the builders capped it."""
    return None if p is None else min(0.99, max(0.01, float(p)))


def upcoming(sport, db, picks_doc, labels, getters, now):
    cols = picks_doc["cols"]
    players = {str(p.get("id")): p for p in db.get("players") or []}
    kick = nfl_kickoffs(db) if sport == "nfl" else {}
    week = (db.get("week") or {}).get("week")
    out = []
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") is not None:
            continue
        if p.get("prob") is None or p.get("price") is None or p.get("th") or p.get("hd"):
            continue        # no price, too little money offered at it (depth.py), or waiting on injury news (holds.py)
        start = kick.get(p.get("gid")) if sport == "nfl" else parse_start(p.get("start"))
        if start is None or start <= now:
            continue
        price, prob = float(p["price"]), cap(p["prob"])
        cents = 100.0 if sport == "nfl" else 1.0    # the NFL builder records prices in cents; the others as fractions
        price /= cents
        venue = {"vn": p.get("vn") or "P"}            # which exchange "price" is (the cheaper), and both prices
        for k in ("pp", "kp"):
            if p.get(k) is not None:
                venue[k] = round(float(p[k]) / cents, 3)
        out.append({
            "sport": sport, "pid": str(p["pid"]), "player": p["player"], "team": p.get("team"),
            "opp": p.get("opp"), "gid": p.get("gid"), "stat": p["stat"],
            "statText": labels.get(p["stat"], p["stat"]), "line": p["line"],
            "side": p.get("side") or "over", "prob": round(prob, 3),
            "lo": cap(p.get("lo")), "hi": cap(p.get("hi")), "price": round(price, 3),
            "edge": round(prob - price, 3), "value": "V" in (p.get("lists") or ""),
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lk": p.get("lk"),      # when the pick locked (its game starts within 30 minutes)
            **venue,
            "l10": last10(sport, players.get(str(p["pid"])), p["stat"], getters),
            # for Bet of the Day (botd.py); not written to today.json
            "neff": p.get("neff"),
            "px0": round(float(p["px0"]) / cents, 3) if p.get("px0") is not None else None,   # price when recorded (moves)
            "flag": botd.news_flag(sport, p.get("nw"), players.get(str(p["pid"])) if sport == "nfl" else None, week),
        })
    return out


def graded(picks_doc):
    """(live picks graded, first live pick date) — the "graded in public" badge counts only
    picks recorded before their game, never the backtest."""
    cols = picks_doc["cols"]
    n, first = 0, None
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live":
            continue
        if p.get("date") and (first is None or p["date"] < first):
            first = p["date"]
        if p.get("res") in ("hit", "miss", "push"):
            n += 1
    return n, first


def last_results(sport, picks_doc, today, max_age=7):
    """The latest ET game day (on or before `today`, within `max_age` days) with graded live
    picks: {"day", "T": {n, hit}, "V": {n, hit, units}} for the results line under each page's
    hero. Pushes and voids don't count; units are 1 unit per Value spot at its recorded price."""
    cols = picks_doc["cols"]
    days = {}
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") not in ("hit", "miss"):
            continue
        t = parse_start(p.get("start"))
        day = t.astimezone(ET).date().isoformat() if t else p.get("date")   # NFL dates are already ET
        if not day:
            continue
        lists, hit = p.get("lists") or "", p["res"] == "hit"
        d = days.setdefault(day, {"T": {"n": 0, "hit": 0}, "V": {"n": 0, "hit": 0, "units": 0.0}})
        if "T" in lists:
            d["T"]["n"] += 1
            d["T"]["hit"] += hit
        if "V" in lists:
            d["V"]["n"] += 1
            d["V"]["hit"] += hit
            price = p.get("price")
            if price:
                price = price / 100.0 if sport == "nfl" else price
                d["V"]["units"] += (1 / price - 1) if hit else -1
    oldest = (datetime.date.fromisoformat(today) - datetime.timedelta(days=max_age)).isoformat()
    recent = sorted(d for d in days if oldest <= d <= today and (days[d]["T"]["n"] or days[d]["V"]["n"]))
    if not recent:
        return None
    day = recent[-1]
    out = {"day": day}
    for tag in ("T", "V"):
        if days[day][tag]["n"]:
            out[tag] = days[day][tag]
    if "V" in out:
        out["V"]["units"] = round(out["V"]["units"], 2)
    return out


CARD_KEYS = ("sport", "pid", "player", "team", "opp", "stat", "statText", "line", "side", "prob", "price", "start")


def streaks(cands, min_streak=5, n=6):
    """Hot streaks for the home page: upcoming priced picks whose player cleared this exact
    line (on this side) in each of his last `min_streak`+ games, longest first, one per player.
    Only props that still pay (priced 85c or less): a streak on a near-certain prop says little."""
    out, seen = [], set()
    def run(c):
        k = 0
        for v in reversed(c.get("l10") or []):
            if v is None or not ((v < c["line"]) if c["side"] == "under" else (v > c["line"])):
                break
            k += 1
        return k
    # longest first; at equal length overs first (the streaks people look for), then likeliest
    rows = sorted(((run(c), c) for c in cands if c["price"] <= SAFE_MAX_PRICE),
                  key=lambda x: (-x[0], x[1]["side"] != "over", -x[1]["prob"]))
    per = {}
    for k, c in rows:
        if k < min_streak or (c["sport"], c["pid"]) in seen or per.get(c["sport"], 0) >= 3:   # 3 per sport at most
            continue
        seen.add((c["sport"], c["pid"]))
        per[c["sport"]] = per.get(c["sport"], 0) + 1
        out.append(dict({key: c[key] for key in CARD_KEYS}, streak=k, games=len(c.get("l10") or [])))
        if len(out) >= n:
            break
    return out


def moves(cands, min_move=0.03, n=6):
    """The market moving our way: upcoming picks whose price rose at least `min_move` since the
    site recorded them (the market came around to the pick), biggest first, one per player."""
    rows = sorted((c for c in cands if c.get("px0") is not None and c["price"] - c["px0"] >= min_move),
                  key=lambda c: -(c["price"] - c["px0"]))
    out, seen = [], set()
    for c in rows:
        if (c["sport"], c["pid"]) in seen:
            continue
        seen.add((c["sport"], c["pid"]))
        out.append(dict({key: c[key] for key in CARD_KEYS}, px0=c["px0"]))
        if len(out) >= n:
            break
    return out


def calibration(docs):
    """How often each confidence level hit, over every graded live pick in all sports:
    [{"lo", "hi", "n", "said", "hit"}] for 50-60% ... 90-100% (the home page's chart).
    "said" is the average model chance in the bucket, "hit" the share that hit."""
    buckets = {}
    for sport, doc in docs:
        cols = doc["cols"]
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or p.get("res") not in ("hit", "miss") or p.get("prob") is None:
                continue
            prob = float(p["prob"])
            if prob < 0.5:
                continue
            b = buckets.setdefault(min(9, int(prob * 10)), [0, 0, 0.0])
            b[0] += 1
            b[1] += p["res"] == "hit"
            b[2] += prob
    return [{"lo": k * 10, "hi": k * 10 + 10, "n": n, "said": round(s / n, 4), "hit": round(h / n, 4)}
            for k, (n, h, s) in sorted(buckets.items())]


def search_rows(sport, db):
    """[sport, id, name, team, pos] for each player with a game this season or last, for the
    home page's player search (search.json). Game rows start with the season."""
    season = db.get("season") or 0
    out = []
    for p in db.get("players") or []:
        if p.get("n") and any(r and isinstance(r[0], int) and r[0] >= season - 1 for r in p.get("g") or []):
            out.append([sport, str(p["id"]), p["n"], p.get("t") or "", p.get("p") or ""])
    return out


RECENT_DAYS = 2   # the ticker only needs the latest graded day; the Past tab loads everything


def write_recent(picks_file, picks_doc, today, days=RECENT_DAYS):
    """<sport>_picks_recent.json: the picks file cut down to pending picks plus the last `days`
    days, so a board loads in a fraction of the bytes. The board fetches the full file only
    when its Past tab opens (and falls back to it if this file is missing)."""
    cols = picks_doc["cols"]
    i_res, i_date = cols.index("res"), cols.index("date")
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=days)).isoformat()
    rows = [r for r in picks_doc["picks"]
            if r[i_res] is None or (r[i_res] in ("hit", "miss", "push") and (r[i_date] or "") >= cutoff)]
    out = dict(picks_doc, picks=rows, recentFrom=cutoff)
    path = picks_file.replace(".json", "_recent.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    return path, len(rows)


def fair_weight(docs):
    """How much to trust the model against the market: the weight w in
        fair chance = w * model + (1 - w) * Polymarket price
    that best predicted every graded live pick that had a price (lowest Brier score),
    pooled across sports. On the record so far the market predicts better than the
    model, so w is small; it's kept between 0.1 and 0.9 and falls back to 0.2 until
    there are 200 priced graded picks."""
    rows = []
    for sport, doc in docs:
        cols = doc["cols"]
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or p.get("res") not in ("hit", "miss") or not p.get("price") or p.get("prob") is None:
                continue
            price = p["price"] / 100.0 if sport == "nfl" else p["price"]
            rows.append((float(p["prob"]), float(price), 1.0 if p["res"] == "hit" else 0.0))
    if len(rows) < 200:
        return {"w": 0.2, "n": len(rows)}
    def brier(w):
        return sum((w * m + (1 - w) * x - y) ** 2 for m, x, y in rows) / len(rows)
    w = min((i / 20 for i in range(21)), key=brier)
    return {"w": round(min(0.9, max(0.1, w)), 2), "n": len(rows),
            "brierModel": round(brier(1.0), 4), "brierMarket": round(brier(0.0), 4)}


def best(cands):
    """Every value spot (by edge) before any safe-but-paying pick (by chance); one per
    player. Within each kind, no more than PER_SPORT from one sport until the others
    have had their turn — otherwise a busy MLB playoff slate would crowd the NFL's value
    spots off the feed — then the rest of that kind."""
    value = sorted((c for c in cands if c["value"]), key=lambda c: -c["edge"])
    safe = sorted((c for c in cands if not c["value"] and c["price"] <= SAFE_MAX_PRICE and c["edge"] > 0),
                  key=lambda c: -c["prob"])
    out, seen = [], set()
    for kind, pool in (("value", value), ("safe", safe)):
        first, spill, per = [], [], {}
        for c in pool:
            key = (c["sport"], c["pid"])
            if key in seen:
                continue
            seen.add(key)
            c = dict(c, kind=kind)
            if per.get(c["sport"], 0) >= PER_SPORT:
                spill.append(c)
                continue
            per[c["sport"]] = per.get(c["sport"], 0) + 1
            first.append(c)
        out += first + spill
    return out[:MAX_PICKS]


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    rec, cands, n_graded, since, docs, last, search = {}, [], 0, None, [], {}, []
    today_et = now.astimezone(ET).date().isoformat()
    for sport, data_file, picks_file, template in SPORTS:
        if not all(os.path.exists(f) for f in (data_file, picks_file, template)):
            print(f"  {sport}: files missing — skipped")
            continue
        try:
            db = load(data_file)
            rec[sport] = record(db)
            picks_doc = load(picks_file)
            docs.append((sport, picks_doc))
            got = upcoming(sport, db, picks_doc, stat_labels(template), stat_getters(template), now)
            g, first = graded(picks_doc)
            n_graded += g
            if first and (since is None or first < since):
                since = first
            cands += got
            search += search_rows(sport, db)
            lr = last_results(sport, picks_doc, today_et)
            if lr:
                last[sport] = lr
            if sport != "nfl":   # the NFL board computes its picks live and loads picks.json only for Past
                try:
                    path, n = write_recent(picks_file, picks_doc, today_et)
                    print(f"  {path}: {n} of {len(picks_doc['picks'])} picks")
                except Exception as e:
                    print(f"  {sport} recent picks: skipped ({e})")
            print(f"  {sport}: {len(got)} upcoming priced pick(s), record {rec[sport]}")
        except Exception as e:     # one bad sport never blanks the others
            print(f"  {sport}: skipped ({e})")
    picks = [{k: v for k, v in c.items() if k not in ("neff", "flag", "px0")} for c in best(cands)]
    # [sport, start] of every upcoming value spot, so the ticker can count what's still live.
    value_live = sorted([c["sport"], c["start"]] for c in cands if c["value"])
    doc = {"gen": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "record": rec, "picks": picks, "valueLive": value_live,
           "tracked": {"graded": n_graded, "since": since}, "fair": fair_weight(docs), "last": last,
           "calib": calibration(docs),
           "streaks": streaks(cands), "moves": moves(cands)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    if search:
        with open(SEARCH_OUT, "w", encoding="utf-8") as f:
            json.dump({"gen": doc["gen"], "cols": ["sport", "id", "name", "team", "pos"],
                       "players": sorted(search, key=lambda r: r[2])}, f, separators=(",", ":"), ensure_ascii=False)
        print(f"  {SEARCH_OUT}: {len(search)} players")
    kinds = sum(1 for p in picks if p["kind"] == "value")
    print(f"  {OUT}: {len(picks)} pick(s) ({kinds} value, {len(picks) - kinds} safe)")
    try:
        botd.run(cands, docs, now)
    except Exception as e:     # never costs the home page its Today feed
        print(f"  {botd.OUT}: not updated ({e})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"today.json not rebuilt: {e}")
        sys.exit(0)

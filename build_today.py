"""
Prop Streak Lab — today.json for the home page's cross-sport "Today" feed.

Runs after the four sport builders. Reads what they already wrote (each sport's
picks file, its dataset's season record, and the stat labels from its template)
and writes a small file the home page can fetch in one request:

  today.json   {"gen", "record": {sport: {"T", "V"}}, "picks": [...], "valueLive": [[sport, start], ...]}

"picks" holds the best upcoming bets across all four sports at the last recorded
Polymarket price: Value spots first (ranked by edge over the price), then, if there
are too few of those, the likeliest picks that still pay (price 85¢ or less). One
pick per player. The home page drops any whose game has started since.

Standard library only. Never fails the deploy: a sport whose files are missing is
skipped, and a failure leaves the previous today.json in place.
"""
import datetime
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

SPORTS = [
    # sport, dataset (has "record"), picks file, template (has the stat labels)
    ("nfl", "data.json", "picks.json", "template.html"),
    ("nba", "nba.json", "nba_picks.json", "nba_template.html"),
    ("nhl", "nhl.json", "nhl_picks.json", "nhl_template.html"),
    ("mlb", "mlb.json", "mlb_picks.json", "mlb_template.html"),
]
OUT = "today.json"
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


def upcoming(sport, db, picks_doc, labels, now):
    cols = picks_doc["cols"]
    kick = nfl_kickoffs(db) if sport == "nfl" else {}
    out = []
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") is not None:
            continue
        if p.get("prob") is None or p.get("price") is None:
            continue
        start = kick.get(p.get("gid")) if sport == "nfl" else parse_start(p.get("start"))
        if start is None or start <= now:
            continue
        price, prob = float(p["price"]), float(p["prob"])
        if sport == "nfl":
            price /= 100.0      # the NFL builder records prices in cents; the others as fractions
        out.append({
            "sport": sport, "pid": str(p["pid"]), "player": p["player"], "team": p.get("team"),
            "opp": p.get("opp"), "gid": p.get("gid"), "stat": p["stat"],
            "statText": labels.get(p["stat"], p["stat"]), "line": p["line"],
            "side": p.get("side") or "over", "prob": round(prob, 3),
            "lo": p.get("lo"), "hi": p.get("hi"), "price": round(price, 3),
            "edge": round(prob - price, 3), "value": "V" in (p.get("lists") or ""),
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out


def best(cands):
    """Value spots by edge, then safe-but-paying picks by chance; one per player, and
    no more than PER_SPORT from one sport until the others have had their turn —
    otherwise a busy MLB playoff slate would crowd the NFL's value spots off the feed."""
    value = sorted((c for c in cands if c["value"]), key=lambda c: -c["edge"])
    safe = sorted((c for c in cands if not c["value"] and c["price"] <= SAFE_MAX_PRICE and c["edge"] > 0),
                  key=lambda c: -c["prob"])
    out, seen, per, spill = [], set(), {}, []
    for kind, pool in (("value", value), ("safe", safe)):
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
            out.append(c)
    return (out + spill)[:MAX_PICKS]


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    rec, cands = {}, []
    for sport, data_file, picks_file, template in SPORTS:
        if not all(os.path.exists(f) for f in (data_file, picks_file, template)):
            print(f"  {sport}: files missing — skipped")
            continue
        try:
            db = load(data_file)
            rec[sport] = record(db)
            got = upcoming(sport, db, load(picks_file), stat_labels(template), now)
            cands += got
            print(f"  {sport}: {len(got)} upcoming priced pick(s), record {rec[sport]}")
        except Exception as e:     # one bad sport never blanks the others
            print(f"  {sport}: skipped ({e})")
    picks = best(cands)
    # [sport, start] of every upcoming value spot, so the ticker can count what's still live.
    value_live = sorted([c["sport"], c["start"]] for c in cands if c["value"])
    doc = {"gen": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "record": rec, "picks": picks, "valueLive": value_live}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    kinds = sum(1 for p in picks if p["kind"] == "value")
    print(f"  {OUT}: {len(picks)} pick(s) ({kinds} value, {len(picks) - kinds} safe)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"today.json not rebuilt: {e}")
        sys.exit(0)

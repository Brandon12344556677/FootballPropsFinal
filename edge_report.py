"""
Prop Streak Lab — edge tracker: once a day, which betting strategies are actually making money.

Grades every recorded live pick that has a market price and a result (picks.json and the
other sports' picks files) as a flat $1 bet at its recorded price, for a fixed set of
strategies: each sport's Value and Top 25 lists, NHL Value since the regular season, the
unders edge found in October 2026's analysis, and the bets that were losing. Each gets its
record, return, a likely range (a bootstrap over game days, since picks from one night win
and lose together) and the last 7 days, so the team sees an edge grow or fade.

Prices that can't have been real are left out: under 10c, or 35c+ away from the pick's
first price (a stale or pulled book; depth.guard stops new ones from being recorded).

Writes team/edges.enc, encrypted like team/stats.enc (team_stats.encrypt, TEAM_DASH_PASSWORD),
for the team dashboard. Runs from update_pass.sh every pass (~10 minutes); the file is rewritten
only when the numbers changed (the bootstrap is seeded, so the same picks give the same report). Without
the password it does nothing. Standard library only; never fails the deploy.
"""
import datetime
import json
import os
import random
import sys
from zoneinfo import ZoneInfo

import team_stats

OUT = os.path.join("team", "edges.enc")
ET = ZoneInfo("America/New_York")
FILES = [("nfl", "picks.json"), ("nhl", "nhl_picks.json"), ("mlb", "mlb_picks.json"), ("nba", "nba_picks.json")]
NHL_REGULAR = "2026-10-07"     # NHL regular season: preseason picks are left out of every row (current season only)
BOOT = 400

STRATEGIES = [   # (key, label, sport or None, test)
    ("nhl-value", "NHL Value spots", "nhl", lambda p: "V" in p["lists"]),
    ("nhl-top", "NHL Top 25 Surest", "nhl", lambda p: "T" in p["lists"]),
    ("nfl-value", "NFL Value spots", "nfl", lambda p: "V" in p["lists"]),
    ("nfl-top", "NFL Top 25 Surest", "nfl", lambda p: "T" in p["lists"]),
    ("mlb-value", "MLB Value spots (unders, the current rule)", "mlb", lambda p: "V" in p["lists"] and p["side"] == "under"),
    ("mlb-top", "MLB Top 25 Surest", "mlb", lambda p: "T" in p["lists"]),
    ("nba-value", "NBA Value spots", "nba", lambda p: "V" in p["lists"]),
    ("unders", "Unders edge (the three rules below)", None,
     lambda p: any(f(p) for f in (UNDER_RULES[k] for k in UNDER_RULES))),
    ("mlb-unders-mid", "MLB unders priced 50-65c", "mlb", lambda p: UNDER_RULES["mlb-unders-mid"](p)),
    ("nhl-assist-unders", "NHL assist unders priced 65-80c", "nhl", lambda p: UNDER_RULES["nhl-assist-unders"](p)),
    ("mlb-tb-under", "MLB total bases under 1.5", "mlb", lambda p: UNDER_RULES["mlb-tb-under"](p)),
    ("all-nhl", "Every NHL pick", "nhl", lambda p: True),
    ("all-mlb", "Every MLB pick", "mlb", lambda p: True),
    ("all-nfl", "Every NFL pick", "nfl", lambda p: True),
]
UNDER_RULES = {
    "mlb-unders-mid": lambda p: p["sport"] == "mlb" and p["side"] == "under" and 0.50 <= p["pr"] < 0.65,
    "nhl-assist-unders": lambda p: p["sport"] == "nhl" and p["stat"] == "a" and p["side"] == "under" and 0.65 <= p["pr"] < 0.80,
    "mlb-tb-under": lambda p: p["sport"] == "mlb" and p["stat"] == "tb" and p["side"] == "under" and p["line"] == 1.5,
}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def frac(x):
    if x is None:
        return None
    x = float(x)
    return x / 100 if x > 1 else x


def et_day(p):
    s = p.get("start")
    if s:
        try:
            t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)).astimezone(ET).date().isoformat()
        except ValueError:
            pass
    return p.get("date")


def graded(sport, doc):
    """Live picks with a result and a believable price, as small dicts."""
    out = []
    cols = doc.get("cols") or []
    for row in doc.get("picks") or []:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") not in ("hit", "miss"):
            continue
        pr, p0 = frac(p.get("price")), frac(p.get("px0"))
        if pr is None or not 0.10 <= pr <= 0.99 or (p0 is not None and abs(pr - p0) > 0.35):
            continue
        day = et_day(p)
        if not day:
            continue
        out.append({"sport": sport, "day": day, "pr": pr, "win": p["res"] == "hit", "side": p.get("side") or "over",
                    "stat": p.get("stat"), "line": p.get("line"), "lists": p.get("lists") or ""})
    return out


def pnl(p):
    return (1 - p["pr"]) / p["pr"] if p["win"] else -1.0


def summary(rows, today, rng):
    n = len(rows)
    if not n:
        return None
    units = sum(pnl(p) for p in rows)
    byday = {}
    for p in rows:
        byday.setdefault(p["day"], []).append(pnl(p))
    days = list(byday.values())
    boots = []
    for _ in range(BOOT):
        s = c = 0
        for _ in days:
            d = rng.choice(days)
            s += sum(d)
            c += len(d)
        boots.append(s / c)
    boots.sort()
    week = (datetime.date.fromisoformat(today) - datetime.timedelta(days=7)).isoformat()
    recent = [p for p in rows if p["day"] > week]
    lo, hi = boots[int(BOOT * 0.025)], boots[int(BOOT * 0.975) - 1]
    roi = units / n
    verdict = ("Edge holding" if lo > 0 else "Promising" if roi >= 0.05 else
               "Losing" if hi < 0 or roi <= -0.05 else "No clear edge")
    return {"n": n, "days": len(days), "hit": round(sum(p["win"] for p in rows) / n, 3),
            "px": round(sum(p["pr"] for p in rows) / n, 3), "units": round(units, 1), "roi": round(roi, 4),
            "lo": round(lo, 4), "hi": round(hi, 4), "verdict": verdict,
            "n7": len(recent), "roi7": round(sum(pnl(p) for p in recent) / len(recent), 4) if recent else None,
            "first": min(byday), "last": max(byday),
            "daily": [[d, round(sum(byday[d]), 2)] for d in sorted(byday)][-30:]}


def current_season(rows):
    """This season's picks only: NHL preseason games are left out."""
    return [p for p in rows if not (p["sport"] == "nhl" and p["day"] < NHL_REGULAR)]


def build(rows, today, seed=1):
    rng = random.Random(seed)
    rows = current_season(rows)
    out = []
    for key, label, sport, test in STRATEGIES:
        s = summary([p for p in rows if (sport is None or p["sport"] == sport) and test(p)], today, rng)
        if s:
            out.append(dict(s, key=key, label=label, sport=sport))
    return out


def main():
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("edge report: TEAM_DASH_PASSWORD not set, skipping")
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(ET).date().isoformat()
    rows = []
    for sport, path in FILES:
        doc = load(path)
        if doc:
            rows += graded(sport, doc)
    report = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "day": today, "picks": len(current_season(rows)),
              "strategies": build(rows, today)}
    try:   # the same numbers as the last pass: leave the file alone (a new salt would change it every time)
        with open(OUT, encoding="ascii") as f:
            old = json.loads(team_stats.decrypt(f.read().strip(), password))
        if {k: v for k, v in old.items() if k != "generated_at"} == {k: v for k, v in report.items() if k != "generated_at"}:
            print(f"edge report: no change ({len(rows)} graded priced picks)")
            return 0
    except Exception:
        pass
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(report, separators=(",", ":")), password) + "\n")
    print(f"edge report: wrote {OUT} ({len(rows)} graded priced picks, {len(report['strategies'])} strategies)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"edge report failed ({type(e).__name__}: {e})")
        sys.exit(0)

"""
Prop Streak Lab — edge tracker: once a day, which betting strategies are actually making money.

Grades every recorded live pick that has a market price and a result (picks.json and the
other sports' picks files) as a flat $1 bet at its recorded price, for a fixed set of
strategies: each sport's Value and Top 25 lists, NHL Value since the regular season, the
team's private strategies (rules.enc, see load_private), the daily model parlay (parlay.py,
graded as one bet at the product of its legs' prices), and the bets that were losing. Each gets its
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

import depth
import team_stats

OUT = os.path.join("team", "edges.enc")
PARLAYS = os.path.join("team", "parlays.enc")
ET = ZoneInfo("America/New_York")
FILES = [("nfl", "picks.json"), ("nhl", "nhl_picks.json"), ("mlb", "mlb_picks.json"), ("nba", "nba_picks.json")]
NHL_REGULAR = "2026-09-29"     # NHL 2026-27 regular season opener: anything earlier is left out (current season only)
BOOT = 400
WAITING = {"nba"}       # rows shown even before their first graded pick (the NBA season starts Oct 2026)
WAITING_KEYS = {"parlays"}     # and rows for lists that start posting later

STRATEGIES = [   # (key, label, sport or None, test)
    ("nhl-value", "NHL Value spots", "nhl", lambda p: "V" in p["lists"]),
    ("nhl-top", "NHL Top 25 Surest", "nhl", lambda p: "T" in p["lists"]),
    ("nhl-top-rule", "NHL Top 25, current rule (no goal unders)", "nhl", lambda p: "T" in p["lists"] and not (p["stat"] == "g" and p["side"] == "under")),
    ("nfl-value", "NFL Value spots", "nfl", lambda p: "V" in p["lists"]),
    ("nfl-top", "NFL Top 25 Surest", "nfl", lambda p: "T" in p["lists"]),
    ("mlb-value", "MLB Value spots (unders, the current rule)", "mlb", lambda p: "V" in p["lists"] and p["side"] == "under"),
    ("mlb-top", "MLB Top 25 Surest", "mlb", lambda p: "T" in p["lists"]),
    ("nba-value", "NBA Value spots", "nba", lambda p: "V" in p["lists"]),
    ("nba-top", "NBA Top 25 Surest", "nba", lambda p: "T" in p["lists"]),
    ("nba-unders", "NBA unders", "nba", lambda p: p["side"] == "under"),
    ("nba-overs", "NBA overs", "nba", lambda p: p["side"] == "over"),
    ("all-nhl", "Every NHL pick", "nhl", lambda p: True),
    ("all-mlb", "Every MLB pick", "mlb", lambda p: True),
    ("all-nfl", "Every NFL pick", "nfl", lambda p: True),
    ("all-nba", "Every NBA pick", "nba", lambda p: True),
    ("parlays", "Model parlay (one a day, about 50% by the model)", "parlay", lambda p: True),
]
# Private strategies (the unders rules and any the team adds) are not in this file: they live
# encrypted in rules.enc on the repo's team-data branch, written from the team dashboard's
# Private strategies panel and unlocked here with the team password (load_private).
PRIVATE_URL = "https://raw.githubusercontent.com/Brandon12344556677/FootballPropsFinal/team-data/rules.enc"


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
        if sport in ("nhl", "mlb") and depth.unchecked(p):
            continue      # launch-day picks the $25 rule never checked: left out of the boards' records too
        pr, p0 = frac(p.get("price")), frac(p.get("px0"))
        if pr is None or not 0.10 <= pr <= 0.99 or (p0 is not None and abs(pr - p0) > 0.35):
            continue
        day = et_day(p)
        if not day:
            continue
        out.append({"sport": sport, "day": day, "pr": pr, "win": p["res"] == "hit", "side": p.get("side") or "over",
                    "stat": p.get("stat"), "line": p.get("line"), "lists": p.get("lists") or ""})
    return out


def parlay_rows(doc):
    """The daily model parlays (parlay.py's team/parlays.enc, decrypted) that won or lost, as rows
    for the "parlay" strategy: one bet a day at the product of the legs' prices."""
    out = []
    for e in (doc or {}).get("days") or []:
        if e.get("res") not in ("hit", "miss"):
            continue
        pr = e.get("paid") if e["res"] == "hit" else e.get("price")
        if not pr:
            continue
        out.append({"sport": "parlay", "day": e["date"], "pr": float(pr), "win": e["res"] == "hit",
                    "side": "parlay", "stat": None, "line": None, "lists": ""})
    return out


def load_parlays(password):
    try:
        with open(PARLAYS, encoding="ascii") as f:
            return parlay_rows(json.loads(team_stats.decrypt(f.read().strip(), password)))
    except Exception as e:  # noqa: BLE001 - no parlays yet (or unreadable) only empties that row
        print(f"edge report: no parlays loaded ({type(e).__name__})")
        return []


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


def before(rows, day):
    """A strategy's headline numbers from the picks graded before `day` (its record as of the day
    before the latest results), for the dashboard's up/down arrows. No bootstrap: just the counts."""
    rows = [p for p in rows if p["day"] < day]
    if not rows:
        return None
    n = len(rows)
    last = max(p["day"] for p in rows)
    week = (datetime.date.fromisoformat(last) - datetime.timedelta(days=7)).isoformat()
    recent = [p for p in rows if p["day"] > week]
    return {"n": n, "hit": round(sum(p["win"] for p in rows) / n, 3),
            "units": round(sum(pnl(p) for p in rows), 1), "roi": round(sum(pnl(p) for p in rows) / n, 4),
            "roi7": round(sum(pnl(p) for p in recent) / len(recent), 4) if recent else None}


def current_season(rows):
    """This season's picks only: NHL preseason games are left out."""
    return [p for p in rows if not (p["sport"] == "nhl" and p["day"] < NHL_REGULAR)]


def rule_test(r):
    """A private rule ({sport, side, stat, line, pmin, pmax}; any field may be empty) as a pick test."""
    def num(v):
        try:
            return None if v in (None, "") else float(v)
        except (TypeError, ValueError):
            return None
    sport, side, stat = r.get("sport") or None, r.get("side") or None, r.get("stat") or None
    line, lo, hi = num(r.get("line")), num(r.get("pmin")), num(r.get("pmax"))

    def test(p):
        return ((sport is None or p["sport"] == sport) and (side is None or p["side"] == side)
                and (stat is None or p["stat"] == stat) and (line is None or p.get("line") == line)
                and (lo is None or p["pr"] >= lo) and (hi is None or p["pr"] < hi))
    return test


def private_strategies(doc):
    """Strategy rows from the decrypted rules.enc document ({"items": [rule, ...]}), plus one row for
    all of them together when there are two or more."""
    items = [r for r in (doc or {}).get("items") or [] if r.get("label")]
    out = [(r.get("key") or "private-" + str(i), r["label"], r.get("sport") or None, rule_test(r)) for i, r in enumerate(items)]
    if len(out) > 1:
        tests = [t for _, _, _, t in out]
        out.insert(0, ("private-all", "Private strategies, all together", None, lambda p: any(t(p) for t in tests)))
    return out


def load_private(password):
    """The team's private strategies from rules.enc (team-data branch), or [] if it can't be read."""
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(PRIVATE_URL, headers={"Cache-Control": "no-cache"}), timeout=20) as r:
            blob = r.read().decode("ascii").strip()
        return private_strategies(json.loads(team_stats.decrypt(blob, password)))
    except Exception as e:  # noqa: BLE001 - a missing or unreadable file only drops the private rows
        print(f"edge report: private strategies not loaded ({type(e).__name__})")
        return []


def build(rows, today, seed=1, strategies=None):
    rng = random.Random(seed)
    rows = current_season(rows)
    latest = max((p["day"] for p in rows), default=None)   # the most recent day with graded picks
    out = []
    for key, label, sport, test in (STRATEGIES if strategies is None else strategies):
        mine = [p for p in rows if (p["sport"] == sport if sport else p["sport"] != "parlay") and test(p)]
        s = summary(mine, today, rng)
        if s:
            prev = before(mine, latest) if latest else None
            out.append(dict(s, key=key, label=label, sport=sport, prev=prev, prev_day=latest))
        elif sport in WAITING or key in WAITING_KEYS:   # not started yet: shown empty, fills in by itself
            out.append({"key": key, "label": label, "sport": sport, "n": 0, "verdict": "Waiting for games"})
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
              "strategies": build(rows + load_parlays(password), today, strategies=STRATEGIES + load_private(password))}
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

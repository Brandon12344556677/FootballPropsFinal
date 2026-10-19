"""
Prop Streak Lab — the model parlays: three a day, each a parlay the model gives about a coin flip
(45-55%) that the market prices well below that, for the team only (never on the public site).

Legs come from the upcoming recorded picks of the sports in TEST_PARLAY_SPORTS (NHL only for now):
a live price on an exchange with enough money behind it (not thin), no injury hold, not locked, 6+ effective games of history, and a model
chance at least 3 points above the price. Each game has to start today (ET) and at least 45 minutes
after the parlay is made; different players, at most 2 legs from one game. Of the 2-4 leg
combinations the model puts at 45-55%, the one with the biggest model-to-market ratio is posted.
The day's parlays never share a player, so they're three separate bets, not one bet three times.

Timing (like Pick of the Day): from the first run at or after 11:00 AM ET, every run makes as many
of today's PER_DAY parlays as it can (later runs fill the rest as more games get prices); once made
a parlay never changes. Still none at 7:30 PM ET: "No parlay today"; fewer than three is fine.

Grading reads each leg's own pick in its sport's picks file: any miss loses; a push or a DNP drops
that leg (the parlay pays on the rest); every leg dropped is a void. Still ungraded 5 days after
the day, the open legs are dropped too. A win pays 1/price - 1 units, where price is the product
of the winning legs' recorded prices (a flat 1-unit parlay at fair prices; a book's parlay price
for linked legs can be lower). edge_report.py grades it in the edge tracker.

State and output: team/parlays.enc, encrypted with TEAM_DASH_PASSWORD like team/edges.enc, rewritten
only on a change. Without the password it does nothing. Standard library only; never fails the deploy.
"""
import datetime
import itertools
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

import build_today
import team_stats

OUT = os.path.join("team", "parlays.enc")
ET = ZoneInfo("America/New_York")
FILES = [("nfl", "picks.json"), ("nba", "nba_picks.json"), ("nhl", "nhl_picks.json"), ("mlb", "mlb_picks.json")]
# The sports new parlays may take legs from (hockey only for now: NFL has been doing poorly). Add a
# sport back here to use it again; every file in FILES is still read so older legs keep grading.
TEST_PARLAY_SPORTS = {"nhl"}
OPEN_AT = (11, 0)          # ET: first try
CLOSE_AT = (19, 30)        # ET: still none -> no parlay today
LEAD_MIN = 45              # every leg's game starts at least this long after the parlay is made
MODEL_LO, MODEL_HI = 0.45, 0.55
MIN_NEFF = 6.0
MIN_EDGE = 0.03
MAX_PER_GAME = 2
PER_DAY = 3
POOL = 40                  # best legs (by model / price) searched for combinations
VOID_AFTER_DAYS = 5


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def rows_of(doc):
    cols = (doc or {}).get("cols") or []
    return [dict(zip(cols, r)) for r in (doc or {}).get("picks") or []]


def start_utc(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def frac(x):
    if x is None:
        return None
    x = float(x)
    return x / 100 if x > 1 else x


def leg_key(sport, p):
    return [sport, p.get("gid"), p.get("pid"), p.get("stat"), p.get("line"), p.get("side")]


def candidates(docs, now, nfl_kick=None):
    """Legs that may go in today's parlay (see the module docstring). NFL picks carry no start
    time: nfl_kick maps their gid to the kickoff (build_today.nfl_kickoffs)."""
    today = now.astimezone(ET).date()
    out = []
    for sport, doc in docs:
        if sport not in TEST_PARLAY_SPORTS:
            continue
        for p in rows_of(doc):
            if sport == "nfl":
                p = dict(p, start=(nfl_kick or {}).get(p.get("gid")) and nfl_kick[p["gid"]].strftime("%Y-%m-%dT%H:%M:%SZ"))
            if p.get("src", "live") != "live" or p.get("res") is not None or p.get("lk") or p.get("th") or p.get("hd"):
                continue
            pr, prob, t = frac(p.get("price")), p.get("prob"), start_utc(p.get("start"))
            if pr is None or prob is None or t is None or not 0.05 < pr < 0.97:
                continue
            if (p.get("neff") or 0) < MIN_NEFF or prob - pr < MIN_EDGE:
                continue
            if t.astimezone(ET).date() != today or t < now + datetime.timedelta(minutes=LEAD_MIN):
                continue
            out.append({"key": leg_key(sport, p), "sport": sport, "player": p.get("player"), "team": p.get("team"),
                        "opp": p.get("opp"), "stat": p.get("stat"), "line": p.get("line"), "side": p.get("side"),
                        "prob": round(prob, 4), "price": round(pr, 4), "start": p.get("start"), "gid": p.get("gid"),
                        "pid": p.get("pid"), "venue": "Kalshi" if p.get("vn") == "K" else "Polymarket"})
    return out


def choose(legs):
    """The 2-4 leg combination the model puts at 45-55% with the biggest model / market ratio, or None."""
    legs = sorted(legs, key=lambda l: (-l["prob"] / l["price"], l["player"] or ""))[:POOL]
    best = None
    for k in (2, 3, 4):
        for c in itertools.combinations(legs, k):
            if len({(l["sport"], l["pid"]) for l in c}) < k:
                continue
            games = {}
            for l in c:
                games[(l["sport"], l["gid"])] = games.get((l["sport"], l["gid"]), 0) + 1
            if max(games.values()) > MAX_PER_GAME:
                continue
            m = math.prod(l["prob"] for l in c)
            if not MODEL_LO <= m <= MODEL_HI:
                continue
            q = math.prod(l["price"] for l in c)
            score = (m / q, m)
            if best is None or score > best[0]:
                best = (score, c, m, q)
    if not best:
        return None
    _, c, m, q = best
    return {"legs": [dict(l) for l in c], "model": round(m, 4), "price": round(q, 4)}


def grade(entry, docs, today):
    """Fill in each leg's result and the parlay's (res, units) once it's settled."""
    if not entry.get("legs") or entry.get("res"):
        return False
    index = {}
    for sport, doc in docs:
        for p in rows_of(doc):
            index[json.dumps(leg_key(sport, p))] = p.get("res")
    changed = False
    late = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(entry["date"])).days > VOID_AFTER_DAYS
    for l in entry["legs"]:
        if l.get("res"):
            continue
        r = index.get(json.dumps(l["key"]))
        if r in ("hit", "miss", "push", "dnp"):
            l["res"] = r; changed = True
        elif late:
            l["res"] = "void"; changed = True
    res = [l.get("res") for l in entry["legs"]]
    if "miss" in res:
        entry["res"], entry["units"] = "miss", -1.0
    elif all(res):
        won = [l for l in entry["legs"] if l["res"] == "hit"]
        if not won:
            entry["res"], entry["units"] = "void", 0.0
        else:
            q = math.prod(l["price"] for l in won)
            entry["res"], entry["units"], entry["paid"] = "hit", round(1 / q - 1, 3), round(q, 4)
    else:
        return changed
    return True


def step(state, docs, now, nfl_kick=None):
    """One pass: grade open parlays, then make (or close) today's. Returns True if anything changed."""
    et = now.astimezone(ET)
    today = et.date().isoformat()
    days = state.setdefault("days", [])
    changed = False
    for e in days:
        changed |= grade(e, docs, today)
    mine = [e for e in days if e["date"] == today]
    if (et.hour, et.minute) < OPEN_AT or any(e.get("closed") for e in mine):
        return changed
    made = [e for e in mine if e.get("legs")]
    if len(made) < PER_DAY and (et.hour, et.minute) < CLOSE_AT:
        used = {(l["sport"], l["pid"]) for e in made for l in e["legs"]}
        legs = [l for l in candidates(docs, now, nfl_kick) if (l["sport"], l["pid"]) not in used]
        while len(made) < PER_DAY:
            pick = choose(legs)
            if not pick:
                break
            e = dict(pick, date=today, n=len(made) + 1, made=now.strftime("%Y-%m-%dT%H:%MZ"), res=None)
            days.append(e); made.append(e); changed = True
            taken = {(l["sport"], l["pid"]) for l in pick["legs"]}
            legs = [l for l in legs if (l["sport"], l["pid"]) not in taken]
    if not made and (et.hour, et.minute) >= CLOSE_AT:
        days.append({"date": today, "closed": True})
        return True
    return changed


def read_state(password):
    try:
        with open(OUT, encoding="ascii") as f:
            return json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        return {"days": []}


def main():
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("parlay: TEAM_DASH_PASSWORD not set, skipping")
        return 0
    state = read_state(password)    # an unreadable file raises: never start over and lose the record
    docs = [(s, load(p)) for s, p in FILES]
    now = datetime.datetime.now(datetime.timezone.utc)
    if not step(state, docs, now, build_today.nfl_kickoffs(load("data.json") or {})):
        print(f"parlay: no change ({len(state.get('days', []))} day(s) on record)")
        return 0
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":")), password) + "\n")
    last = state["days"][-1] if state["days"] else {}
    print(f"parlay: wrote {OUT} (latest {last.get('date')}: "
          f"{'no parlay' if last.get('closed') else str(len(last.get('legs', []))) + ' legs, model ' + str(last.get('model'))})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"parlay failed ({type(e).__name__}: {e})")
        sys.exit(0)

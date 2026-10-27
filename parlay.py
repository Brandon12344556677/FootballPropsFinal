"""
Prop Streak Lab — the model parlays: three a day, one in each payout band (3-3.5x, 3.5-4x, 4-4.5x
the stake), each a parlay the model gives 35-55% that the market prices well below that, for the team
only (never on the public site).

Separate tracks, each with these rules and its own three a day and record (TRACKS): NHL in
team/parlays.enc, NBA in team/parlays_nba.enc and NFL in team/parlays_nfl.enc. Legs come from the upcoming recorded picks of the
track's sports, priced on Polymarket only (the pick's "pp", with $25+ offered there; Kalshi prices are not used):
a live price with enough money behind it (not thin), a prop type Polymarket US lets you parlay (combos.py: not NHL
assists), no injury hold, not locked, 6+ effective games of history, and a model
chance at least 3 points above the price. Each game has to start today (ET) and at least 45 minutes
after the parlay is made; different players, at most 2 legs from one game. For each band in BANDS,
of the 2-4 leg combinations the model puts at 35-55% whose payout (1 / the legs' prices multiplied)
falls in that band, the one with the biggest model-to-market ratio is posted.
The day's parlays never share a player (so never the same prop), so they're three separate bets.

Timing (like Pick of the Day): from the first run at or after 11:00 AM ET, every run makes as many
of today's band parlays as it can (later runs fill the rest as more games get prices); once made
a parlay never changes, except that one of today's that breaks rules changed since it was made (sport,
Polymarket price, payout band, model range) is remade while none of its games has started. Still none at 7:30 PM ET: "No parlay today"; fewer than three is fine.

Grading reads each leg's own pick in its sport's picks file: any miss loses; a push or a DNP drops
that leg (the parlay pays on the rest); every leg dropped is a void. Still ungraded 5 days after
the day, the open legs are dropped too. A win pays 1/price - 1 units, where price is the product
of the winning legs' recorded prices (a flat 1-unit parlay at fair prices; a book's parlay price
for linked legs can be lower). edge_report.py grades it in the edge tracker.

Parlay of the Day (POTD_RULES, team/parlay_potd.enc, added Oct 27, 2026): one more track with the same legs,
timing, freezing and grading, but one parlay a day from every sport, paying 3x or more and over 50% by the
model, and never an NBA under or an NHL assists under (banned_under). It never shares a player with
the day's 3 Picks of the Day (tpod.py, team/tpod.enc), which come first: its players are left out, and
today's Parlay of the Day is remade if one of them turns up there before its games start (tpod.py's later
fills leave Parlay of the Day's players out too). Its own record, dashboard tab and edge-tracker row.
The tab's Lock button saves the day's parlay to potd_locks.enc on team-data (needs a GitHub token, as in
Expenses; load_locks reads it through the API each run, like tpod.py's): a locked day is never remade,
filled or closed, and a parlay changed after locking is put back while none of its games has started.

State and output: each track's file (team/parlays.enc, team/parlays_nba.enc, team/parlays_nfl.enc, team/parlay_potd.enc), encrypted with
TEAM_DASH_PASSWORD like team/edges.enc, rewritten only on a change. Without the password it does nothing. Standard library only; never fails the deploy.
"""
import datetime
import itertools
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

import build_today
import combos
import team_stats

OUT = os.path.join("team", "parlays.enc")
ET = ZoneInfo("America/New_York")
FILES = [("nfl", "picks.json"), ("nba", "nba_picks.json"), ("nhl", "nhl_picks.json"), ("mlb", "mlb_picks.json")]
# The sports new parlays may take legs from (hockey only for now: NFL has been doing poorly). Add a
# sport back here to use it again; every file in FILES is still read so older legs keep grading.
TEST_PARLAY_SPORTS = {"nhl"}
OUT_NBA = os.path.join("team", "parlays_nba.enc")
OUT_NFL = os.path.join("team", "parlays_nfl.enc")
OUT_POTD = os.path.join("team", "parlay_potd.enc")
OPEN_AT = (11, 0)          # ET: first try
CLOSE_AT = (19, 30)        # ET: still none -> no parlay today
LEAD_MIN = 45              # every leg's game starts at least this long after the parlay is made
MODEL_LO, MODEL_HI = 0.35, 0.55   # 35%+: with the 3x payout floor, 45%+ left about one parlay a day (Oct 19)
# One parlay a day in each payout band (x the stake, both ends included): even the lowest covers the
# day's three stakes on its own.
BANDS = [(3.0, 3.5), (3.5, 4.0), (4.0, 4.5)]
MIN_NEFF = 6.0
MIN_EDGE = 0.03
MIN_DEPTH = 25             # dollars offered on Polymarket near its price (the pick's "pd"), like the thin rule
MAX_PER_GAME = 2
POOL = 40                  # best legs (by model / price) searched for combinations
VOID_AFTER_DAYS = 5
# A track's rules: its payout bands (one parlay a day in each) and the model's range for the parlay
# (lo_open: the chance must be above lo, not just at it).
RULES = {"bands": BANDS, "lo": MODEL_LO, "hi": MODEL_HI}
# Parlay of the Day (the owner's rules, Oct 27, 2026): pays 3x or more, over 50% by the model, any sport.
POTD_RULES = {"bands": [(3.0, math.inf)], "lo": 0.50, "lo_open": True, "hi": 1.0, "no_banned_unders": True,
              "avoid_tpod": True,   # no player in today's 3 Picks of the Day
              "lockable": True}     # the tab's Lock button (potd_locks.enc)
TPOD = os.path.join("team", "tpod.enc")
LOCKS_URL = "https://api.github.com/repos/Brandon12344556677/FootballPropsFinal/contents/potd_locks.enc?ref=team-data"
ALL_SPORTS = {s for s, _ in FILES}
# (name, sports, file, rules): each track makes its own parlays a day and keeps its own record. NBA added
# Oct 20, 2026 to see how the same rules do there, and NFL the same day (tracking only); neither changes the NHL track.
TRACKS = [("nhl", TEST_PARLAY_SPORTS, OUT, RULES), ("nba", {"nba"}, OUT_NBA, RULES), ("nfl", {"nfl"}, OUT_NFL, RULES),
          ("potd", ALL_SPORTS, OUT_POTD, POTD_RULES)]


def banned_under(sport, stat, side):
    """Parlay of the Day never takes an NBA under or an NHL assists under."""
    return side == "under" and (sport == "nba" or (sport == "nhl" and stat == "a"))


def model_ok(m, rules=RULES):
    lo = rules["lo"] < m if rules.get("lo_open") else rules["lo"] <= m
    return lo and m <= rules["hi"]


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


def candidates(docs, now, nfl_kick=None, sports=None, rules=RULES):
    """Legs that may go in today's parlay (see the module docstring). NFL picks carry no start
    time: nfl_kick maps their gid to the kickoff (build_today.nfl_kickoffs)."""
    today = now.astimezone(ET).date()
    out = []
    for sport, doc in docs:
        if sport not in (TEST_PARLAY_SPORTS if sports is None else sports):
            continue
        for p in rows_of(doc):
            if sport == "nfl":
                p = dict(p, start=(nfl_kick or {}).get(p.get("gid")) and nfl_kick[p["gid"]].strftime("%Y-%m-%dT%H:%M:%SZ"))
            if p.get("src", "live") != "live" or p.get("res") is not None or p.get("lk") or p.get("th") or p.get("hd"):
                continue
            pr, prob, t = frac(p.get("pp")), p.get("prob"), start_utc(p.get("start"))   # Polymarket's price only
            if pr is None or prob is None or t is None or not 0.05 < pr < 0.97 or (p.get("pd") or 0) < MIN_DEPTH:
                continue
            if (p.get("neff") or 0) < MIN_NEFF or prob - pr < MIN_EDGE:
                continue
            if not combos.allowed(sport, p.get("stat"), today):    # Polymarket won't parlay it (NHL assists)
                continue
            if rules.get("no_banned_unders") and banned_under(sport, p.get("stat"), p.get("side")):
                continue
            if t.astimezone(ET).date() != today or t < now + datetime.timedelta(minutes=LEAD_MIN):
                continue
            out.append({"key": leg_key(sport, p), "sport": sport, "player": p.get("player"), "team": p.get("team"),
                        "opp": p.get("opp"), "stat": p.get("stat"), "line": p.get("line"), "side": p.get("side"),
                        "prob": round(prob, 4), "price": round(pr, 4), "start": p.get("start"), "gid": p.get("gid"),
                        "pid": p.get("pid"), "venue": "Polymarket"})
    return out


def in_band(price, band):
    return band[0] - 1e-9 <= 1 / price <= band[1] + 1e-9


def choose(legs, band=BANDS[0], rules=RULES):
    """The 2-4 leg combination in the model range of rules (35-55% by default), paying within band
    (x the stake), with the biggest model / market ratio, or None."""
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
            if not model_ok(m, rules):
                continue
            q = math.prod(l["price"] for l in c)
            if not in_band(q, band):
                continue
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


def meets_rules(e, sports=None, rules=RULES):
    """A made parlay still fits today's rules (checked on what was recorded, not on new prices)."""
    b, bands = e.get("band"), rules["bands"]
    sports = TEST_PARLAY_SPORTS if sports is None else sports
    return (all(l["sport"] in sports and l.get("venue") == "Polymarket" and combos.allowed(l["sport"], l.get("stat"))
                and not (rules.get("no_banned_unders") and banned_under(l["sport"], l.get("stat"), l.get("side")))
                for l in e["legs"])
            and model_ok(e.get("model", 0), rules)
            and isinstance(b, int) and 0 <= b < len(bands) and in_band(e.get("price", 1), bands[b]))


def step(state, docs, now, nfl_kick=None, sports=None, rules=RULES, avoid=frozenset(), locks={}):   # noqa: B006 - only read
    """One pass: grade open parlays, then make (or close) today's. Returns True if anything changed.
    avoid: (sport, pid) of players today's parlays may not use (Parlay of the Day: the 3 Picks of the Day).
    locks: load_locks() (Parlay of the Day's Lock button): a locked today keeps (or puts back) the
    parlay as locked and is never remade, filled or closed. None (couldn't read them): today's
    parlays aren't remade, in case they were locked, but a day without one still fills."""
    et = now.astimezone(ET)
    today = et.date().isoformat()
    days = state.setdefault("days", [])
    changed = False
    for e in days:
        changed |= grade(e, docs, today)
    lock = (locks or {}).get(today)
    if lock:
        mine = [e for e in days if e["date"] == today]
        held = lock["parlay"]
        if [[l.get("key") for l in e["legs"]] for e in mine if e.get("legs")] != [[l.get("key") for l in held["legs"]]]                 and not any(e.get("res") or any(l.get("res") or (start_utc(l.get("start")) or now) <= now for l in e["legs"])
                            for e in mine if e.get("legs")):   # changed after locking: put it back
            days[:] = [e for e in days if e["date"] != today] + [dict(held, date=today, res=None)]
            changed = True
        for e in days:
            if e["date"] == today and e.get("legs") and e.get("locked") != lock.get("at"):
                e["locked"] = lock.get("at")
                changed = True
        days.sort(key=lambda e: (e["date"], e.get("n", 0)))
        return changed
    if locks is not None:
        for e in days:
            if e["date"] == today and e.pop("locked", None):   # unlocked on the dashboard
                changed = True
    # The rules changed after today's parlays were made (a sport dropped, Polymarket prices only, the
    # payout bands, the model range): remake any of today's that break them while none of its games has
    # started (no result yet, so the record is unaffected).
    stale = [] if locks is None else [e for e in days if e["date"] == today and e.get("legs") and not e.get("res") and (not meets_rules(e, sports, rules) or any((l["sport"], l["pid"]) in avoid for l in e["legs"]))
             and all(not l.get("res") and (start_utc(l.get("start")) or now) > now for l in e["legs"])]
    if stale:
        days[:] = [e for e in days if not any(e is s for s in stale)]
        changed = True
    mine = [e for e in days if e["date"] == today]
    if (et.hour, et.minute) < OPEN_AT or any(e.get("closed") for e in mine):
        return changed
    made = [e for e in mine if e.get("legs")]
    if len(made) < len(rules["bands"]) and (et.hour, et.minute) < CLOSE_AT:
        used = {(l["sport"], l["pid"]) for e in made for l in e["legs"]} | set(avoid)
        legs = [l for l in candidates(docs, now, nfl_kick, sports, rules) if (l["sport"], l["pid"]) not in used]
        filled = {e.get("band") for e in made}
        for b, band in enumerate(rules["bands"]):
            if b in filled:
                continue
            pick = choose(legs, band, rules)
            if not pick:
                continue
            e = dict(pick, date=today, n=b + 1, band=b, made=now.strftime("%Y-%m-%dT%H:%MZ"), res=None)
            days.append(e); made.append(e); changed = True
            taken = {(l["sport"], l["pid"]) for l in pick["legs"]}
            legs = [l for l in legs if (l["sport"], l["pid"]) not in taken]
        days.sort(key=lambda e: (e["date"], e.get("n", 0)))
    if not made and (et.hour, et.minute) >= CLOSE_AT:
        days.append({"date": today, "closed": True})
        return True
    return changed


def read_state(password, path=OUT):
    try:
        with open(path, encoding="ascii") as f:
            return json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        return {"days": []}


def tpod_players(password, today, path=TPOD):
    """(sport, pid) of today's 3 Picks of the Day (tpod.py, run earlier in the pass by build_today.py)."""
    day = next((d for d in read_state(password, path).get("days") or [] if d.get("date") == today), {})
    return {(p.get("sport"), p.get("pid")) for p in day.get("picks") or []}


def load_locks(password, url=LOCKS_URL):
    """{date: lock} from potd_locks.enc on team-data (the Parlay of the Day tab's Lock button: the day's
    parlay as locked), {} if there's no file yet, or None if it can't be read (tpod.load_locks)."""
    import tpod
    return tpod.load_locks(password, url, "parlay of the day", "parlay")


def run_track(name, sports, path, docs, now, nfl_kick, password, rules=RULES):
    state = read_state(password, path)    # an unreadable file raises: never start over and lose the record
    # an unreadable 3 Picks file raises too: better no Parlay of the Day this run than one that overlaps it
    avoid = tpod_players(password, now.astimezone(ET).date().isoformat()) if rules.get("avoid_tpod") else frozenset()
    locks = load_locks(password) if rules.get("lockable") else {}
    if not step(state, docs, now, nfl_kick, sports, rules, avoid, locks):
        print(f"parlay {name}: no change ({len(state.get('days', []))} day(s) on record)")
        return
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":")), password) + "\n")
    last = state["days"][-1] if state["days"] else {}
    print(f"parlay {name}: wrote {path} (latest {last.get('date')}: "
          f"{'no parlay' if last.get('closed') else str(len(last.get('legs', []))) + ' legs, model ' + str(last.get('model'))})")


def main():
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("parlay: TEAM_DASH_PASSWORD not set, skipping")
        return 0
    docs = [(s, load(p)) for s, p in FILES]
    now = datetime.datetime.now(datetime.timezone.utc)
    nfl_kick = build_today.nfl_kickoffs(load("data.json") or {})
    for name, sports, path, rules in TRACKS:
        try:   # one track failing never stops the other
            run_track(name, sports, path, docs, now, nfl_kick, password, rules)
        except Exception as e:  # noqa: BLE001
            print(f"parlay {name} failed ({type(e).__name__}: {e})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"parlay failed ({type(e).__name__}: {e})")
        sys.exit(0)

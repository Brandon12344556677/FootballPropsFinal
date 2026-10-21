"""
Prop Streak Lab — 3 Picks of the Day (team only: the team posts them on TikTok).

Three picks a day from the team's private methods (rules.enc, the Secret methods tab), for posting:
good payouts the model is confident in, not 95c "locks". build_today.py calls run() with every
upcoming priced pick (its candidates) after Pick of the Day.

A pick qualifies when:
  - it fits at least one private method with MIN_METHOD_N+ graded picks (the methods are ranked by
    the low end of their likely return, so a lucky small sample doesn't rank first);
  - its price is PRICE (pays about 1.54x-2.9x) and the model gives it MIN_PROB+, MIN_EDGE+ over the price;
  - no news flag or injury hold, MIN_NEFF+ effective games of history, its price hasn't dropped
    MAX_DROP+ cents since it was first recorded, and its game starts today (ET), LEAD+ from now.
Ranked by the best method it fits, then by how far the model is over the price; three different
games and players, at most MAX_PER_KIND of one kind of bet. From 11 AM ET each run fills the empty slots; a pick never changes once made.
Still short at 7:30 PM ET: that day has fewer than three.

Each pick keeps "why" (for the team: the method it fits and that method's record, the model against
the price, the last 10 games, the price's move) and a spoken line for the video; each day gets a
script to read on camera and a caption. Neither names a method.

The fun parlay: one a day, a longer shot paying PARLAY_PAYS (about 3x). 2-3 legs, each fitting a
method, priced LEG_PRICE with the model MIN_PROB+ and LEG_EDGE+ over the price, from different games
and not a player from the day's three picks; of the combinations paying in that band, the one the
model gives the best chance. Frozen once made; graded like parlay.py (a miss loses, a push or DNP
drops the leg, every leg dropped is a void; a win pays 1/price - 1 at the winning legs' prices).
It keeps its own record.

Graded like Pick of the Day (botd.grade: the sport's own graded pick; a DNP or a game still
ungraded 5 days later is void). Output: team/tpod.enc, encrypted with TEAM_DASH_PASSWORD like
team/parlays.enc, rewritten only on a change. Without the password or the rules it does nothing.
Standard library only; never fails the run.
"""
import datetime
import json
import os
import random

import botd
import edge_report
import team_stats

OUT = os.path.join("team", "tpod.enc")
ET = botd.ET
PICK_FROM, PICK_UNTIL = datetime.time(11, 0), datetime.time(19, 30)
LEAD = datetime.timedelta(minutes=60)
PRICE = (0.35, 0.65)    # pays about 1.54x-2.9x
MIN_PROB = 0.60
MIN_EDGE = 0.05         # the model at least 5 points over the price
MIN_NEFF = 6.0
MAX_DROP = 3            # cents
MIN_METHOD_N = 30
PER_DAY = 3
SERIES_START = "2026-10-21"   # the TikTok series' day 1: earlier days (a dry run on Oct 20) are dropped from the record
PARLAY_PAYS = (2.8, 3.4)
LEG_PRICE = (0.45, 0.85)
LEG_EDGE = 0.03
POOL = 25
MAX_PER_KIND = 2        # a day isn't three of the same bet (same sport, stat and side)
SPORT_NAME = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB"}


def utc(s):
    return botd._utc(s)


def as_rule_pick(c):
    """A candidate (build_today.upcoming) in the shape edge_report.rule_test reads."""
    return {"sport": c["sport"], "side": c["side"], "stat": c["stat"], "line": c["line"], "pr": c["price"],
            "p0": c.get("px0"), "prob": c["prob"], "lists": c.get("lists") or "", "pos": c.get("pos"),
            "day": utc(c["start"]).astimezone(ET).date().isoformat()}


def rank_methods(private, docs, today):
    """[(label, test, record)] of the methods with enough graded picks, best first."""
    rows = []
    for sport, doc in docs:
        rows += edge_report.graded(sport, doc)
    rows = [p for p in edge_report.current_season(rows) if p["sport"] not in edge_report.OWN_ROWS]
    rng = random.Random(3)
    out = []
    for key, label, sport, test in private:
        if key == "private-all":
            continue
        s = edge_report.summary([p for p in rows if (not sport or p["sport"] == sport) and test(p)], today, rng)
        if s and s["n"] >= MIN_METHOD_N:
            out.append((label, sport, test, {k: s[k] for k in ("n", "hit", "roi", "lo", "hi")}))
    out.sort(key=lambda m: -m[3]["lo"])
    return out


def eligible(c, now):
    start = utc(c["start"])
    if not (PRICE[0] <= c["price"] <= PRICE[1]) or c["prob"] < MIN_PROB or c["prob"] - c["price"] < MIN_EDGE:
        return False
    if c.get("flag") or c.get("lk") or (c.get("neff") or 0) < MIN_NEFF:
        return False
    if c.get("px0") is not None and round((c["price"] - c["px0"]) * 100) <= -MAX_DROP:
        return False
    return start.astimezone(ET).date() == now.astimezone(ET).date() and start >= now + LEAD


def cashed(c):
    """(times the line would have cashed, games) over the last 10."""
    l10 = [v for v in (c.get("l10") or []) if v is not None]
    hit = sum(1 for v in l10 if (v > c["line"] if c["side"] == "over" else v < c["line"]))
    return hit, len(l10)


def say_line(c):
    """'under 0.5 assists' in words."""
    line = c["line"]
    words = (c.get("statText") or c["stat"]).lower()
    if line == 0.5:
        return ("at least one " + words.rstrip("s")) if c["side"] == "over" else ("no " + words)
    return f"{c['side']} {line:g} {words}"


def explain(c, method):
    """(why: bullet strings for the team, spoken: one line for the video)."""
    pays = 1 / c["price"]
    hit, n = cashed(c)
    move = None if c.get("px0") is None else round((c["price"] - c["px0"]) * 100)
    why = [f"The model gives it {round(c['prob'] * 100)}% (likely {round(c['lo'] * 100)}-{round(c['hi'] * 100)}%) "
           f"against a {round(c['price'] * 100)}c price: {round((c['prob'] - c['price']) * 100)} points over the market, paying {pays:.2f}x."
           if c.get("lo") is not None and c.get("hi") is not None else
           f"The model gives it {round(c['prob'] * 100)}% against a {round(c['price'] * 100)}c price, paying {pays:.2f}x."]
    if n:
        why.append(f"Would have cashed in {hit} of {c['player']}'s last {n} games ("
                   + ", ".join(f"{v:g}" for v in (c.get("l10") or [])[-5:]) + " most recently).")
    if c.get("neff"):
        why.append(f"The chance is built on about {round(c['neff'])} games of his history.")
    if move is not None:
        why.append("The price has held steady since it was posted." if move == 0 else
                   f"The market has moved toward it: {round(c['px0'] * 100)}c to {round(c['price'] * 100)}c." if move > 0 else
                   f"The price has slipped {-move}c since it was posted (within the {MAX_DROP}c limit).")
    label, rec = method
    why.append(f"Fits {label}: {round(rec['hit'] * 100)}% hit, {rec['roi'] * 100:+.1f}% return on {rec['n']} graded picks.")
    spoken = (f"{c['player']}, {say_line(c)}"
              + f", paying about {pays:.1f} times your money. Our model has it at {round(c['prob'] * 100)} percent"
              + (f", and it would have cashed in {hit} of his last {n} games." if n else "."))
    return why, spoken


def kind(c):
    return (c["sport"], c["stat"], c["side"])


def choose(cands, methods, now, taken, used=()):
    """The next best pick for an empty slot, or None. taken: (gid, pid) already used today; used:
    the kinds of bet today's picks are (one kind at most MAX_PER_KIND times)."""
    best = None
    full = {k for k in used if list(used).count(k) >= MAX_PER_KIND}
    for c in cands:
        if not eligible(c, now) or kind(c) in full or (c.get("gid"), c["pid"]) in taken or any(c.get("gid") == g for g, _ in taken):
            continue
        rp = as_rule_pick(c)
        fit = next(((i, m) for i, m in enumerate(methods) if (not m[1] or m[1] == c["sport"]) and m[2](rp)), None)
        if fit is None:
            continue
        score = (-fit[0], c["prob"] - c["price"], c["prob"])
        if best is None or score > best[0]:
            best = (score, c, fit[1])
    if not best:
        return None
    _, c, (label, _, _, rec) = best
    why, spoken = explain(c, (label, rec))
    keep = {k: c.get(k) for k in botd.KEEP}
    return dict(keep, method=label, method_rec=rec, why=why, spoken=spoken, px0=c.get("px0"), res=None,
                made=now.strftime("%Y-%m-%dT%H:%MZ"))


def record(days):
    done = [p for d in days for p in d.get("picks") or [] if p.get("res") in ("hit", "miss")]
    w = sum(1 for p in done if p["res"] == "hit")
    units = sum((1 / p["price"] - 1) if p["res"] == "hit" else -1.0 for p in done)
    return {"n": len(done), "hit": w, "miss": len(done) - w, "units": round(units, 2)}


def parlay_record(days):
    done = [d["parlay"] for d in days if (d.get("parlay") or {}).get("res") in ("hit", "miss")]
    w = sum(1 for p in done if p["res"] == "hit")
    return {"n": len(done), "hit": w, "miss": len(done) - w, "units": round(sum(p.get("units") or 0 for p in done), 2)}


def choose_parlay(cands, methods, now, avoid):
    """The fun parlay, or None. avoid: player ids in the day's picks."""
    import itertools
    import math
    legs = []
    for c in cands:
        start = utc(c["start"])
        if not (LEG_PRICE[0] <= c["price"] <= LEG_PRICE[1]) or c["prob"] < MIN_PROB or c["prob"] - c["price"] < LEG_EDGE:
            continue
        if c.get("flag") or c.get("lk") or (c.get("neff") or 0) < MIN_NEFF or c["pid"] in avoid:
            continue
        if c.get("px0") is not None and round((c["price"] - c["px0"]) * 100) <= -MAX_DROP:
            continue
        if start.astimezone(ET).date() != now.astimezone(ET).date() or start < now + LEAD:
            continue
        rp = as_rule_pick(c)
        fit = next(((i, m) for i, m in enumerate(methods) if (not m[1] or m[1] == c["sport"]) and m[2](rp)), None)
        if fit:
            legs.append((fit[0], c, fit[1]))
    legs.sort(key=lambda x: (x[0], -(x[1]["prob"] - x[1]["price"])))
    legs = legs[:POOL]
    best = None
    for k in (2, 3):
        for combo in itertools.combinations(legs, k):
            cs = [x[1] for x in combo]
            if len({c.get("gid") for c in cs}) < k or len({c["pid"] for c in cs}) < k:
                continue
            q = math.prod(c["price"] for c in cs)
            if not PARLAY_PAYS[0] <= 1 / q <= PARLAY_PAYS[1]:
                continue
            m = math.prod(c["prob"] for c in cs)
            if best is None or m > best[0]:
                best = (m, q, combo)
    if not best:
        return None
    m, q, combo = best
    out = []
    for _, c, (label, _, _, rec) in combo:
        why, spoken = explain(c, (label, rec))
        out.append(dict({k: c.get(k) for k in botd.KEEP}, method=label, why=why, spoken=spoken, px0=c.get("px0"), res=None))
    return {"legs": out, "price": round(q, 4), "model": round(m, 4), "res": None, "made": now.strftime("%Y-%m-%dT%H:%MZ")}


def grade_parlay(par, index, now):
    if not par or par.get("res"):
        return
    for leg in par["legs"]:
        botd.grade(leg, index, now)
    res = [leg.get("res") for leg in par["legs"]]
    if "miss" in res:
        par["res"], par["units"] = "miss", -1.0
    elif all(res):
        won = [leg for leg in par["legs"] if leg["res"] == "hit"]
        if not won:
            par["res"], par["units"] = "void", 0.0
        else:
            q = 1.0
            for leg in won:
                q *= leg["price"]
            par["res"], par["units"], par["paid"] = "hit", round(1 / q - 1, 3), round(q, 4)


def last_day(past):
    """(date, won, graded, units) of the latest earlier day with a graded pick or parlay, or None."""
    for d in sorted(past, key=lambda x: x["date"], reverse=True):
        bets = [p for p in d.get("picks") or [] if p.get("res") in ("hit", "miss")]
        par = d.get("parlay") or {}
        units = sum((1 / p["price"] - 1) if p["res"] == "hit" else -1.0 for p in bets)
        won = sum(1 for p in bets if p["res"] == "hit")
        if par.get("res") in ("hit", "miss"):
            bets.append(par)
            won += par["res"] == "hit"
            units += par.get("units") or 0.0
        if bets:
            return d["date"], won, len(bets), units
    return None


def units_said(u):
    """+2 units / -1.5 units, as read out."""
    return f"{u:+.1f}".replace(".0", "") + (" unit" if abs(round(u, 1)) == 1 else " units")


def script(day, rec, date, prec=None, day_no=1, last=None):
    """What to say on camera, and the caption. day_no: which day of the series this is (day 1 = the first);
    last: last_day() of the earlier days, for "Yesterday we went 2 for 4, which is +2 units..."."""
    d = datetime.date.fromisoformat(date)
    picks = day.get("picks") or []
    par = day.get("parlay")
    nums = ["First up", "Second", "And third"]
    top = f"my top {len(picks)} picks" if len(picks) != 1 else "my top pick"
    lines = [f"This is day {day_no} of giving you guys {top} for the day" + (", plus one more of a reach parlay." if par else ".")]
    for i, p in enumerate(picks):
        lines.append(f"{nums[i]}: {SPORT_NAME.get(p['sport'], '')}, {p['spoken']}")
    if par:
        legs = ", and ".join(f"{p['player']}, {say_line(p)}" for p in par["legs"])
        lines.append(f"Now the reach parlay. It's {len(par['legs'])} legs paying about {1 / par['price']:.1f} times your money: "
                     f"{legs}. It's a reach, so keep it small.")   # no model % here: the model runs hot on parlays
    prec = prec or {"n": 0, "units": 0.0}
    total = rec.get("units", 0.0) + prec.get("units", 0.0)   # the series: picks and reach parlays, 1 unit each
    if last:   # right after the intro: how the last day went and where the series stands
        when = ("Yesterday" if (d - datetime.date.fromisoformat(last[0])).days == 1
                else "On " + datetime.date.fromisoformat(last[0]).strftime("%A"))
        lines.insert(1, f"{when} we went {last[1]} for {last[2]}, which is {units_said(last[3])}, "
                        f"bringing the series total to {units_said(total)}.")
    lines.append("Follow for three picks every day. Eighteen and over only, this is for entertainment, not betting advice.")
    cap = [f"Day {day_no}: {top}" + (" + a reach parlay" if par else "") + f" ({d.strftime('%b')} {d.day})"]
    for i, p in enumerate(picks):
        cap.append(f"{i + 1}) {p['player']} {p['side']} {p['line']:g} {(p.get('statText') or p['stat']).lower()} ({1 / p['price']:.2f}x)")
    if par:
        cap.append(f"Reach parlay ({1 / par['price']:.2f}x): " + " + ".join(
            f"{p['player']} {p['side']} {p['line']:g} {(p.get('statText') or p['stat']).lower()}" for p in par["legs"]))
    if last:
        cap.append(("Yesterday" if (d - datetime.date.fromisoformat(last[0])).days == 1 else
                    datetime.date.fromisoformat(last[0]).strftime("%A")) + f": {last[1]}/{last[2]} ({units_said(last[3])})"
                   + f" | Series: {units_said(total)}")
    cap.append("18+ | For entertainment, not betting advice")
    return " ".join(lines), "\n".join(cap)


def update(state, cands, docs, methods, now):
    """Grade, then fill today's slots. Returns True if anything changed."""
    days = state.setdefault("days", [])
    before = json.dumps(days, sort_keys=True)
    days[:] = [d for d in days if d["date"] >= SERIES_START]
    index = botd._picks_index(docs)
    for d in days:
        for p in d.get("picks") or []:
            botd.grade(p, index, now)
        grade_parlay(d.get("parlay"), index, now)
    et = now.astimezone(ET)
    today = et.date().isoformat()
    day = next((d for d in days if d["date"] == today), None)
    if PICK_FROM <= et.time() < PICK_UNTIL and methods and (day is None or len(day["picks"]) < PER_DAY):
        if day is None:
            day = {"date": today, "picks": []}
            days.append(day)
        taken = {(p.get("gid"), p["pid"]) for p in day["picks"]}
        while len(day["picks"]) < PER_DAY:
            p = choose(cands, methods, now, taken, [kind(q) for q in day["picks"]])
            if not p:
                break
            day["picks"].append(p)
            taken.add((p.get("gid"), p["pid"]))
    if PICK_FROM <= et.time() < PICK_UNTIL and methods and day is not None and not day.get("parlay"):
        par = choose_parlay(cands, methods, now, {p["pid"] for p in day["picks"]})
        if par:
            day["parlay"] = par
    if day is not None:
        past = [d for d in days if d["date"] < today]
        day_no = 1 + sum(1 for d in past if d.get("picks"))   # the series counts days with picks
        day["script"], day["caption"] = script(day, record(past), today, parlay_record(past), day_no, last_day(past))
    return json.dumps(days, sort_keys=True) != before


def run(cands, docs, now, path=OUT):
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("  3 picks of the day: TEAM_DASH_PASSWORD not set, skipping")
        return
    try:
        with open(path, encoding="ascii") as f:
            state = json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        state = {"days": []}
    today = now.astimezone(ET).date().isoformat()
    methods = rank_methods(edge_report.load_private(password), docs, today)
    if not update(state, cands, docs, methods, now):
        print(f"  3 picks of the day: no change ({len(methods)} method(s) ranked)")
        return
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["record"] = record(state["days"])
    state["parlay_record"] = parlay_record(state["days"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":"), ensure_ascii=True), password) + "\n")
    d = state["days"][-1] if state["days"] else {}
    print(f"  {path}: {d.get('date')} {len(d.get('picks') or [])} pick(s), record {state['record']['hit']}-{state['record']['miss']}")

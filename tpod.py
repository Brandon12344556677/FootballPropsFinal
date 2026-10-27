"""
Prop Streak Lab — 3 Picks of the Day (team only: the team posts them on TikTok).

Three picks a day from the team's private methods (rules.enc, the Secret methods tab), for posting:
good payouts the model is confident in, not 95c "locks". build_today.py calls run() with every
upcoming priced pick (its candidates) after Pick of the Day.

A pick qualifies when:
  - proven first: it fits a private method that has MIN_METHOD_N+ graded picks IN THE PICK'S SPORT and
    is in profit there (a method is judged sport by sport, so one whose record comes from the NHL can't
    vouch for a new NBA pick: these go out in public), ranked by the low end of their likely return.
    The day always gets three picks: short of proven picks, the next best fill the rest
    (a method not proven in that sport, then no method with Value spots first, then relaxed filters),
    each marked as a fill-in for the team (never in the script);
  - its price is PRICE (pays about 1.33x-2.9x) and the model gives it MIN_PROB+, MIN_EDGE+ over the price;
  - no news flag or injury hold, MIN_NEFF+ effective games of history, its price hasn't dropped
    MAX_DROP+ cents since it was first recorded, and its game starts today (ET), LEAD+ from now.
Ranked by the best method it fits, then by how far the model is over the price; three different
games and players, at most MAX_PER_KIND of one kind of bet (a proven pick may go past it rather than
leave the slot to a fill-in), and no player in the day's Parlay of the Day (parlay.py, team/parlay_potd.enc; these
picks come first, so the parlay steers around them and is remade if needed). From 11 AM ET each run fills the empty
slots; a pick never changes once made.
Still short at 7:30 PM ET: that day has fewer than three. Once the team films, the dashboard's Lock button
saves the day's picks to tpod_locks.enc on team-data (load_locks): a locked day is never remade or filled,
and picks that changed after filming are put back.

Each pick keeps "why" (for the team: the method it fits and that method's record, the model against
the price, the last 10 games, the price's move) and a spoken line for the video; each day gets a
script to read on camera and a caption. Neither names a method.

There was also a fun parlay (about 3x) until Oct 23, 2026; it's no longer made, graded or shown.
Days recorded before then keep their "parlay" entry as it was, unread.

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
POTD = os.path.join("team", "parlay_potd.enc")   # parlay.py's Parlay of the Day: never a player from it
LOCKS_URL = "https://api.github.com/repos/Brandon12344556677/FootballPropsFinal/contents/tpod_locks.enc?ref=team-data"
ET = botd.ET
PICK_FROM, PICK_UNTIL = datetime.time(11, 0), datetime.time(19, 30)
LEAD = datetime.timedelta(minutes=60)
PRICE = (0.35, 0.75)    # pays about 1.33x-2.9x (75c, not 65c: on light nights the proven methods' picks sit at 65-75c)
MIN_PROB = 0.60
MIN_EDGE = 0.05         # the model at least 5 points over the price
MIN_NEFF = 6.0
MAX_DROP = 3            # cents
MIN_METHOD_N = 30
PER_DAY = 3
MIN_PM_USD = 25.0   # dollars offered near the Polymarket price for the side (depth.MIN_USD), or it isn't a pick
RULES_V = 3   # bump when the selection changes: today's picks are remade if none has started (2: methods judged by sport; 3: proven picks past the kind cap)
SERIES_START = "2026-10-21"   # the TikTok series' day 1: earlier days (a dry run on Oct 20) are dropped from the record
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
    """[(label, sport, test, record)]: every method in every sport it covers, best first. A pair with
    MIN_METHOD_N+ graded picks in that sport and a positive return there is proven (record["tier"] 0),
    ranked by the low end of its likely return; the rest are fill-ins (tier 1), ranked by the method's
    record over every sport. record also says how many graded picks it has in that sport ("sport_n")."""
    rows = []
    for sport, doc in docs:
        rows += edge_report.graded(sport, doc)
    rows = [p for p in edge_report.current_season(rows) if p["sport"] not in edge_report.OWN_ROWS]
    rng = random.Random(3)
    keep = ("n", "hit", "roi", "lo", "hi")
    proven, fill = [], []
    for key, label, sport, test in private:
        if key == "private-all":
            continue
        overall = edge_report.summary([p for p in rows if (not sport or p["sport"] == sport) and test(p)], today, rng)
        for sp in ([sport] if sport else list(SPORT_NAME)):
            s = edge_report.summary([p for p in rows if p["sport"] == sp and test(p)], today, rng)
            if s and s["n"] >= MIN_METHOD_N and s["roi"] > 0:
                proven.append((label, sp, test, dict({k: s[k] for k in keep}, tier=0, sport_n=s["n"])))
            elif overall:
                fill.append((label, sp, test, dict({k: overall[k] for k in keep}, tier=1, sport_n=s["n"] if s else 0)))
    proven.sort(key=lambda m: -m[3]["lo"])
    fill.sort(key=lambda m: -m[3]["lo"])
    return proven + fill


def eligible(c, now, relaxed=False):
    """The pick filters; relaxed (only to fill the last slots on a thin night): model 55%+ and at the
    price or above, 30-85c."""
    start = utc(c["start"])
    lo, hi, prob, edge = (0.30, 0.85, 0.55, 0.0) if relaxed else (PRICE[0], PRICE[1], MIN_PROB, MIN_EDGE)
    if not (lo <= c["price"] <= hi) or c["prob"] < prob or c["prob"] - c["price"] < edge:
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
    if "+" in words:   # combos read out: "pts+reb+ast" -> "points, rebounds and assists"
        parts = [{"pts": "points", "reb": "rebounds", "ast": "assists", "r": "runs", "h": "hits", "rbi": "RBIs"}.get(w.strip(), w.strip())
                 for w in words.split("+")]
        words = ", ".join(parts[:-1]) + " and " + parts[-1]
    if line == 0.5:
        return ("at least one " + words.rstrip("s")) if c["side"] == "over" else ("no " + words)
    return f"{c['side']} {line:g} {words}"


NO_METHOD = ("No method", None, None, {"tier": 2})


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
    sp = SPORT_NAME.get(c["sport"], c["sport"])
    tier = rec.get("tier", 0)
    if tier == 0:
        why.append(f"Fits {label}, which in the {sp} has hit {round(rec['hit'] * 100)}% "
                   f"for a {rec['roi'] * 100:+.1f}% return on {rec['n']} graded picks.")
    elif tier == 1:
        why.append(f"Fill-in: fits {label}, which isn't proven in the {sp} yet ({rec.get('sport_n', 0)} graded picks there); "
                   f"over every sport it has hit {round(rec['hit'] * 100)}% for {rec['roi'] * 100:+.1f}% on {rec['n']}.")
    else:
        why.append("Fill-in: fits none of the methods; the best remaining pick by the model's edge on a thin night.")
    spoken = (f"{c['player']}, {say_line(c)}"
              + f", paying about {pays:.1f} times your money. Our model has it at {round(c['prob'] * 100)} percent"
              + (f", and it would have cashed in {hit} of his last {n} games." if n else "."))
    return why, spoken


def kind(c):
    return (c["sport"], c["stat"], c["side"])


def fit_of(c, methods):
    """(rank, method) of the best method c fits (proven pairs first), or (len(methods), NO_METHOD)."""
    rp = as_rule_pick(c)
    return next(((i, m) for i, m in enumerate(methods) if (not m[1] or m[1] == c["sport"]) and m[2](rp)),
                (len(methods), NO_METHOD))


def choose(cands, methods, now, taken, used=(), avoid=frozenset()):
    """The next best pick for an empty slot, or None. Proven methods first, then fill-ins (a method not
    proven in that sport, then no method, Value spots first), then on a thin night the relaxed filters.
    taken: (gid, pid) already used today; used: the kinds of bet today's picks are (at most MAX_PER_KIND
    of one kind, unless it's a proven pick and the only other choice is a fill-in; dropped too if that's
    the only way to fill the day). avoid: (sport, pid) of today's Parlay of the Day legs."""
    for relaxed, varied in ((False, True), (True, True), (True, False)):
        full = {k for k in used if list(used).count(k) >= MAX_PER_KIND} if varied else set()
        best = None
        for c in cands:
            if not eligible(c, now, relaxed) or (c.get("gid"), c["pid"]) in taken \
                    or any(c.get("gid") == g for g, _ in taken) or (c.get("sport"), c["pid"]) in avoid:
                continue
            rank, m = fit_of(c, methods)
            proven, over = m[3].get("tier", 0) == 0, kind(c) in full
            if over and not proven:
                continue
            # proven first; among those, a new kind of bet before one more of a full kind
            score = (proven, not over, -rank, "V" in (c.get("lists") or ""), c["prob"] - c["price"], c["prob"])
            if best is None or score > best[0]:
                best = (score, c, m)
        if best:
            (_, fresh, *_), c, (label, _, _, rec) = best
            why, spoken = explain(c, (label, rec))
            if not fresh:
                why.append(f"More than {MAX_PER_KIND} of this kind of bet today: no other proven pick fit, so it beat a fill-in.")
            if relaxed:
                why.append("Thin night: picked under the relaxed bar (model 55%+, 30-85c) to fill the day.")
            keep = {k: c.get(k) for k in botd.KEEP}
            return dict(keep, method=label, method_rec=rec, tier=rec.get("tier", 0), relaxed=relaxed,
                        why=why, spoken=spoken, px0=c.get("px0"), res=None, made=now.strftime("%Y-%m-%dT%H:%MZ"))
    return None


def record(days):
    done = [p for d in days for p in d.get("picks") or [] if p.get("res") in ("hit", "miss")]
    w = sum(1 for p in done if p["res"] == "hit")
    units = sum((1 / p["price"] - 1) if p["res"] == "hit" else -1.0 for p in done)
    return {"n": len(done), "hit": w, "miss": len(done) - w, "units": round(units, 2)}


def last_day(past):
    """(date, picks won, picks graded, picks units) of the latest earlier day with a graded pick, or None."""
    for d in sorted(past, key=lambda x: x["date"], reverse=True):
        bets = [p for p in d.get("picks") or [] if p.get("res") in ("hit", "miss")]
        units = sum((1 / p["price"] - 1) if p["res"] == "hit" else -1.0 for p in bets)
        won = sum(1 for p in bets if p["res"] == "hit")
        if bets:
            return d["date"], won, len(bets), units
    return None


def units_said(u):
    """+2 units / -1.5 units, as read out."""
    return f"{u:+.1f}".replace(".0", "") + (" unit" if abs(round(u, 1)) == 1 else " units")


def script(day, rec, date, day_no=1, last=None):
    """What to say on camera, and the caption. day_no: which day of the series this is (day 1 = the first);
    last: last_day() of the earlier days, for "Yesterday we went 2 for 3 on picks, which is +1.5 units, bringing the
    series total to..." The units and the series total are the picks', 1 unit each."""
    d = datetime.date.fromisoformat(date)
    picks = day.get("picks") or []
    if not picks:   # a light day: nothing fit the proven methods at a good price
        return ("No picks from me today: nothing fit my best methods at a good enough price, and I'd rather skip a day "
                "than force it. Back tomorrow. Eighteen and over only, this is for entertainment, not betting advice.",
                f"No picks today ({d.strftime('%b')} {d.day}): nothing fit the best methods at a good price.\n18+ | For entertainment, not betting advice")
    nums = ["First up", "Second", "And third"]
    top = f"my top {len(picks)} picks" if len(picks) != 1 else "my top pick"
    lines = [f"This is day {day_no} of giving you guys {top} for the day."]
    for i, p in enumerate(picks):
        lines.append(f"{nums[i]}: {SPORT_NAME.get(p['sport'], '')}, {p['spoken']}")
    total = rec.get("units", 0.0)   # the series: the picks, 1 unit each
    if last:   # right after the intro: how the last day went and where the series stands
        _, pw, pn, pu = last
        when = ("Yesterday" if (d - datetime.date.fromisoformat(last[0])).days == 1
                else "On " + datetime.date.fromisoformat(last[0]).strftime("%A"))
        said = (f"{when} we went {pw} for {pn} on picks, which is {units_said(pu)}, bringing the series total to {units_said(total)}."
                if pn else f"{when} we had no graded picks.")
        lines.insert(1, said)
    lines.append("Make sure to like and follow for more to stay posted, three picks every day. "
                 "Eighteen and over only, this is for entertainment, not betting advice.")
    cap = [f"Day {day_no}: {top} ({d.strftime('%b')} {d.day})"]
    for i, p in enumerate(picks):
        cap.append(f"{i + 1}) {p['player']} {p['side']} {p['line']:g} {(p.get('statText') or p['stat']).lower()} ({1 / p['price']:.2f}x)")
    if last:
        _, pw, pn, pu = last
        cap.append(("Yesterday" if (d - datetime.date.fromisoformat(last[0])).days == 1 else
                    datetime.date.fromisoformat(last[0]).strftime("%A")) + ": "
                   + " | ".join(([f"picks {pw}/{pn} ({units_said(pu)})"] if pn else []) + [f"Series: {units_said(total)}"]))
    cap.append("18+ | For entertainment, not betting advice")
    return " ".join(lines), "\n".join(cap)


def on_polymarket(cands):
    """The candidates as bets on Polymarket US, the exchange the picks are posted for: priced at its
    price for the side, and only when MIN_PM_USD+ is offered near that price (on NBA props the under
    side is often nearly empty, so an under there can't really be bought)."""
    return [dict(c, price=c["pp"], vn="P") for c in cands
            if c.get("pp") is not None and (c.get("pd") or 0) >= MIN_PM_USD]


def load_locks(password, url=LOCKS_URL, what="3 picks of the day", key="picks"):
    """{date: lock} from tpod_locks.enc on team-data (the dashboard's Lock button: the day's picks as
    filmed), {} if there's no file yet, or None if it can't be read. Read through the GitHub API, not
    raw.githubusercontent.com, whose 5-minute cache could miss a lock made just before this run.
    parlay.py reads Parlay of the Day's locks the same way (url, what, key: the field a lock must have)."""
    import urllib.error
    import urllib.request
    headers = {"Accept": "application/vnd.github.raw", "Cache-Control": "no-cache"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            doc = json.loads(team_stats.decrypt(r.read().decode("ascii").strip(), password))
        return {x["date"]: x for x in doc.get("items") or [] if x.get("date") and x.get(key)}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        print(f"  {what}: locks not read (HTTP {e.code})")
    except Exception as e:  # noqa: BLE001 - unreadable locks only hold today's picks as they are
        print(f"  {what}: locks not read ({type(e).__name__})")
    return None


def update(state, cands, docs, methods, now, locks={}, avoid=frozenset()):   # noqa: B006 - only read
    """Grade, then fill today's slots. Returns True if anything changed. locks: load_locks(); today
    locked keeps (or puts back) the picks as filmed and is never remade or filled. None (couldn't
    read them): today's picks aren't remade, in case they were locked, but empty slots still fill.
    avoid: (sport, pid) of today's Parlay of the Day legs, left out of new picks."""
    cands = on_polymarket(cands)
    days = state.setdefault("days", [])
    before = json.dumps(days, sort_keys=True)
    days[:] = [d for d in days if d["date"] >= SERIES_START]
    index = botd._picks_index(docs)
    for d in days:
        for p in d.get("picks") or []:
            botd.grade(p, index, now)
    et = now.astimezone(ET)
    today = et.date().isoformat()
    day = next((d for d in days if d["date"] == today), None)
    lock = (locks or {}).get(today)
    if lock:
        if day is None:
            day = {"date": today, "picks": []}
            days.append(day)
        filmed = [p["pid"] for p in lock["picks"]]
        if [p["pid"] for p in day["picks"]] != filmed \
                and not any(p.get("res") or utc(p["start"]) <= now for p in day["picks"]):   # changed after filming: put them back
            day["picks"] = [dict(p, res=None) for p in lock["picks"]]
        day["locked"], day["v"] = lock.get("at"), RULES_V
    elif day is not None and locks is not None:
        day.pop("locked", None)   # unlocked on the dashboard
    if day is not None and day.get("v") != RULES_V and locks is not None:
        if not any(p.get("res") or utc(p["start"]) <= now for p in day.get("picks") or []):   # nothing started: remake under the new rules
            day["picks"], day["v"] = [], RULES_V
    if PICK_FROM <= et.time() < PICK_UNTIL and methods and not lock and (day is None or len(day["picks"]) < PER_DAY):
        if day is None:
            day = {"date": today, "picks": [], "v": RULES_V}
            days.append(day)
        taken = {(p.get("gid"), p["pid"]) for p in day["picks"]}
        while len(day["picks"]) < PER_DAY:
            p = choose(cands, methods, now, taken, [kind(q) for q in day["picks"]], avoid)
            if not p:
                break
            day["picks"].append(p)
            taken.add((p.get("gid"), p["pid"]))
    if day is not None:
        past = [d for d in days if d["date"] < today]
        day_no = 1 + sum(1 for d in past if d.get("picks"))   # the series counts days with picks
        day["script"], day["caption"] = script(day, record(past), today, day_no, last_day(past))
    return json.dumps(days, sort_keys=True) != before


def potd_players(password, today, path=POTD):
    """(sport, pid) of the legs of today's Parlay of the Day, or none if there's no file or it can't be read."""
    try:
        with open(path, encoding="ascii") as f:
            days = json.loads(team_stats.decrypt(f.read().strip(), password)).get("days") or []
    except Exception:  # noqa: BLE001 - no parlay file: nothing to avoid (the parlay steers around these picks anyway)
        return set()
    return {(l.get("sport"), l.get("pid")) for d in days if d.get("date") == today for l in d.get("legs") or []}


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
    if not update(state, cands, docs, methods, now, load_locks(password), potd_players(password, today)):
        print(f"  3 picks of the day: no change ({len(methods)} method(s) ranked)")
        return
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["record"] = record(state["days"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":"), ensure_ascii=True), password) + "\n")
    d = state["days"][-1] if state["days"] else {}
    print(f"  {path}: {d.get('date')} {len(d.get('picks') or [])} pick(s), record {state['record']['hit']}-{state['record']['miss']}")

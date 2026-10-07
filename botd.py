"""
Prop Streak Lab — Bet of the Day for the home page: a Lock and a Value Shot, picked once a
day from every sport's upcoming priced picks, frozen once posted, and graded in public.

  Lock        the surest pick on the board: Polymarket price 90-96c (pays 1.04-1.11x) and a
              model chance of 90%+. On the graded record, picks priced 90-96c hit 91-92%
              when the model was under 90%, and 135 of 138 (97.8%) when it was 90%+ — on
              both halves (odd days 63/63, even days 72/75) and in each sport with enough
              picks (NHL 42/44, MLB 88/89). Lower down (80-90c) the model agreeing added
              nothing, so that band isn't used. Ranked by the lower of the two chances (both
              have to be high), then by price. Nothing hits 100%: at ~98% expect a miss
              every month or two.
  Value Shot  pays 2x or more: price 30-50c with a model chance of 70-80%. The market thinks
              these are coin flips; on the graded record they've hit about what the price
              says (model 65%+ at 30-50c: 26 of 54, 48%, against a 46% price), so it's the
              riskier pick and labeled that way. Ranked by model chance.

Both skip players the news flags (an ESPN injury status, an NFL injury-report status or a
limited/missed practice this week, an MLB lineup posted without them) — the news the model
can't see and the market can — and props with under 6 effective games of history. Different
players for the two picks. Each game has to start today (ET) and at least 45 minutes after the
pick is made.

Timing: from the first run at or after 11:00 AM ET, every run tries to fill an empty slot with
that moment's best candidate; once filled it never changes, whatever the price does after.
A slot still empty at 7:30 PM ET is closed: "No bet today", never a forced pick.

Grading reads each sport's own picks file (the same graded result the sport page shows).
'dnp' (didn't play) is a void: no win, no loss. A pick still ungraded 5 days after its game
is voided too, so the record can't hang on a missing box score.

  botd.json  {"gen", "rules", "days": [{"date", "lock", "value", "closed"}],
              "record": {"lock"|"value": {"n", "hit", "miss", "push", "void", "units", "last"}},
              "hist": {"lock"|"value": {"n", "hit"}}}     (every day is kept: it's the record)

Standard library only; build_today.py calls update() and never lets it fail the run.
"""
import datetime
import json
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OUT = "botd.json"
PICK_FROM = datetime.time(11, 0)
PICK_UNTIL = datetime.time(19, 30)
MIN_LEAD = datetime.timedelta(minutes=45)
MIN_NEFF = 6.0
VOID_AFTER = datetime.timedelta(days=5)
SLOTS = ("lock", "value")
RULES = {   # inclusive bounds
    "lock": {"price": [0.90, 0.96], "prob": [0.90, 1.00]},
    "value": {"price": [0.30, 0.50], "prob": [0.70, 0.80]},
}
KEEP = ("sport", "pid", "player", "team", "opp", "gid", "stat", "statText", "line", "side",
        "prob", "lo", "hi", "price", "vn", "start", "l10")    # vn: the exchange the price is from
PRACTICE_FLAGS = ("DNP", "LP")


def _utc(s):
    t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _iso(t):
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def news_flag(sport, nw, player=None, week=None):
    """Why the news rules a pick out, or None. nw is the pick's pre-game news column;
    player the NFL dataset entry (its injury report and roster status)."""
    nw = nw if isinstance(nw, dict) else {}
    st = (nw.get("st") or "").strip()
    if st:
        return st                                   # ESPN: Questionable, Out, Day-To-Day, ...
    if sport == "mlb" and nw.get("lu") == 0:
        return "not in the posted lineup"
    if sport == "nfl" and player:
        if player.get("st"):
            return f"roster status {player['st']}"  # injured reserve, practice squad, ...
        inj = player.get("inj") or []
        if len(inj) > 0 and inj[0]:
            return str(inj[0])                      # injury report game status
        if len(inj) > 3 and inj[2] in PRACTICE_FLAGS and week is not None and inj[3] == week:
            return f"practice: {inj[2]}"
    return None


def qualifies(c, slot):
    r = RULES[slot]
    return (r["price"][0] <= c["price"] <= r["price"][1] and r["prob"][0] <= c["prob"] <= r["prob"][1]
            and (c.get("neff") or 0) >= MIN_NEFF and not c.get("flag"))


def rank_key(c, slot):
    if slot == "lock":
        return (min(c["prob"], c["price"]), c["price"])
    return (c["prob"], c["prob"] - c["price"])


def choose(cands, slot, now, taken=()):
    """The best candidate for a slot right now, or None."""
    today = now.astimezone(ET).date()
    ok = []
    for c in cands:
        try:
            start = _utc(c["start"])
        except (KeyError, ValueError, TypeError):
            continue
        if start.astimezone(ET).date() != today or start < now + MIN_LEAD:
            continue
        if (c["sport"], str(c["pid"])) in taken or not qualifies(c, slot):
            continue
        ok.append(c)
    return max(ok, key=lambda c: rank_key(c, slot)) if ok else None


def freeze(c, now):
    p = {k: c.get(k) for k in KEEP}
    p.update(picked=_iso(now), res=None, actual=None)
    return p


def _picks_index(docs):
    """{sport: {(pid, stat, line, side): [pick, ...]}} of live picks, for grading."""
    out = {}
    for sport, doc in docs:
        cols, idx = doc["cols"], {}
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or p.get("line") is None:
                continue
            idx.setdefault((str(p.get("pid")), p.get("stat"), float(p["line"]), p.get("side")), []).append(p)
        out[sport] = idx
    return out


def grade(pick, index, now):
    """Fill res/actual from the sport's graded pick (same game, or the same day either side)."""
    if pick.get("res") is not None:
        return
    rows = index.get(pick["sport"], {}).get((str(pick["pid"]), pick["stat"], float(pick["line"]), pick["side"]), [])
    start = _utc(pick["start"])
    same = [p for p in rows if p.get("gid") == pick.get("gid")]
    if not same:
        day = start.astimezone(ET).date()
        same = [p for p in rows if p.get("date") and abs((datetime.date.fromisoformat(p["date"][:10]) - day).days) <= 1]
    for p in same:
        if p.get("res") in ("hit", "miss", "push"):
            pick["res"], pick["actual"] = p["res"], p.get("actual")
            return
        if p.get("res") == "dnp":
            pick["res"] = "void"
            return
    if now - start > VOID_AFTER:
        pick["res"] = "void"


def record(days, slot):
    r = {"n": 0, "hit": 0, "miss": 0, "push": 0, "void": 0, "units": 0.0, "last": []}
    for d in sorted(days, key=lambda d: d["date"]):
        p = d.get(slot)
        if not p or p.get("res") is None:
            continue
        res = p["res"]
        r[res] = r.get(res, 0) + 1
        if res in ("hit", "miss"):
            r["n"] += 1
            r["units"] += (1.0 / p["price"] - 1.0) if res == "hit" else -1.0
        r["last"].append(res)
    r["units"] = round(r["units"], 2)
    r["last"] = r["last"][-10:]
    return r


def history(docs):
    """How picks inside each slot's price/chance window have done on the whole graded record
    (any sport, before the news and history filters) — the honest base rate shown on the page."""
    out = {s: {"n": 0, "hit": 0} for s in SLOTS}
    for sport, doc in docs:
        cols = doc["cols"]
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or p.get("res") not in ("hit", "miss") or p.get("price") is None or p.get("prob") is None:
                continue
            price = p["price"] / 100.0 if sport == "nfl" else float(p["price"])
            c = {"price": price, "prob": float(p["prob"]), "neff": MIN_NEFF}
            for s in SLOTS:
                if qualifies(c, s):
                    out[s]["n"] += 1
                    out[s]["hit"] += p["res"] == "hit"
    return out


def update(doc, cands, docs, now):
    """One run: open today's entry from 11 AM ET, fill empty slots, close at 7:30 PM ET, grade,
    and refresh the record. doc is the previous botd.json content (or {}); returns it updated."""
    days = doc.setdefault("days", [])
    et = now.astimezone(ET)
    today = et.date().isoformat()
    day = next((d for d in days if d["date"] == today), None)
    if day is None and et.time() >= PICK_FROM:
        day = {"date": today, "lock": None, "value": None, "closed": False}
        days.append(day)
    if day is not None and not day["closed"]:
        for slot in SLOTS:
            if day[slot] is None:
                taken = {(day[s]["sport"], str(day[s]["pid"])) for s in SLOTS if day.get(s)}
                c = choose(cands, slot, now, taken)
                if c:
                    day[slot] = freeze(c, now)
        if et.time() >= PICK_UNTIL:
            day["closed"] = True
    index = _picks_index(docs)
    for d in days:
        if d["date"] < today:
            d["closed"] = True
        for slot in SLOTS:
            if d.get(slot):
                grade(d[slot], index, now)
    days.sort(key=lambda d: d["date"])
    doc.update(gen=_iso(now), rules=RULES, pickFrom=PICK_FROM.strftime("%H:%M"), pickUntil=PICK_UNTIL.strftime("%H:%M"),
               record={s: record(days, s) for s in SLOTS}, hist=history(docs))
    return doc


def run(cands, docs, now, path=OUT):
    doc = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    doc = update(doc, cands, docs, now)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    d = doc["days"][-1] if doc["days"] else None
    shown = {s: (f"{d[s]['player']} {d[s]['side']} {d[s]['line']} {d[s]['stat']} @ {round(d[s]['price'] * 100)}c"
                 if d and d.get(s) else ("none" if d and d.get("closed") else "pending")) for s in SLOTS}
    rec = {s: f"{doc['record'][s]['hit']}-{doc['record'][s]['miss']}" for s in SLOTS}
    print(f"  {path}: {d['date'] if d else 'before 11 AM ET'} lock={shown['lock']} value={shown['value']} record {rec}")
    return doc

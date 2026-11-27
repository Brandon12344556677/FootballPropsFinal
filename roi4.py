"""
Prop Streak Lab — the "4% return" track (team only, never public): paper bets, sized in units, aiming at
a 4% return on every unit staked over each month (MONTH_TARGET, units won / units staked that month; the owner's
goal since Nov 23, 2026, after a daily 4% proved unreachable and then the bank up 4% a month, Nov 17-23). Paper only
until REVIEW_ON, the end of the NFL season, when the live months are judged.

The owner's brief: any sport, any number of bets a day, choose the stake of each, the one goal a 4% return.
No rule can promise 4% every day: props this close to fair swing a lot from one night to the next, so the
target is the long-run return on units staked, and the dashboard tab shows every day, losing ones included.

How it bets (the same code runs the backtest and the live track):

  Bets come only from the site's own recorded picks (the sports' picks files) that could really have been
  bought: a real price (depth.real_price, 10c-99c), $25+ offered on the exchange it's priced on (not thin,
  a venue recorded), no injury hold, no unconfirmed price jump, and a model chance. They are bet at the
  locked price, the last one before the game (the pick's price once it locks, 20-30 minutes before the start):
  that's the price every graded pick in the files records, so the backtest and the live bets are priced alike.

  Each day the plan (frozen at the day's first run) is the set of segments that have earned it on the
  graded picks before that day: from a short fixed menu, each sport's Value spots, Top 25, and picks the
  model rates EDGE_MIN+ over the price. A segment qualifies with MIN_N+ graded picks over MIN_DAYS+ game days
  in the last LOOKBACK days, returning MIN_ROI+ (the 4% target) with the low end of its bootstrap range
  (seeded, resampled by game day, since one night's picks win and lose together) at LO_FLOOR or better.
  Nothing qualifies: no bets that day.

  One bet per player, stat and game (the line the model likes most), sized by quarter Kelly on the
  segment's own past return, shrunk toward zero (r * n / (n + SHRINK_N)): with a bankroll of BANK units,
  stake = BANK * KELLY * p * r / (1 - p), rounded to 0.05, MIN_BET-MAX_BET units. At most GAME_CAP units on one
  game (the biggest model edges first) and DAY_CAP a day (first come, as games lock).

  Frozen once made; graded from the pick's own result: a win pays stake * (1 - p) / p, a loss costs the stake,
  a push or a void returns it. Still ungraded VOID_AFTER days after the game: void.

The backtest replays the same rule over every day before the track went live (state["live_from"]), each day
using only the picks graded before it, and is frozen into the file on the first run: the picks files can be
trimmed later, and the live record must never be judged against a backtest refit after the fact.

Output: team/roi4.enc, encrypted with TEAM_DASH_PASSWORD like team/edges.enc, rewritten only on a change.
`python roi4.py backtest` prints the backtest without the password. Standard library only; never fails the deploy.
"""
import datetime
import json
import os
import random
import sys
from zoneinfo import ZoneInfo

import depth
import edge_report
import team_stats

OUT = os.path.join("team", "roi4.enc")
ET = ZoneInfo("America/New_York")
UTC = datetime.timezone.utc
FILES = edge_report.FILES
SPORTS = ["nfl", "nba", "nhl", "mlb", "tennis"]
SPORT_NAME = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB", "tennis": "Tennis"}

TARGET = 0.04        # 4% back on every unit staked: what a day or a bet is judged against
MONTH_TARGET = 0.04  # the owner's goal (Nov 23, 2026): 4%+ back on the units staked each month (was the bank up 4%, Nov 17-23)
REVIEW_ON = "2027-02-15"   # paper only until then: the day after the NFL season's last game, when the live months are judged
EDGE_MIN = 0.10      # the "model edge" segments: the model's chance at least 10 points over the price
LOOKBACK = 42        # days of graded picks a segment is judged on
MIN_N = 300          # graded picks (one per player, stat and game) a segment needs
MIN_DAYS = 6         # over this many game days
MIN_ROI = TARGET     # returning the target or better
LO_FLOOR = 0.0       # and the low end of its 80% bootstrap range above zero (a looser floor let NHL in on a hot streak, and it lost)
BOOT = 300
SHRINK_N = 500       # r * n / (n + SHRINK_N): a segment's past return is trusted more as it grows
BANK = 100.0         # units: the stake is a fraction of this
KELLY = 0.25         # quarter Kelly
MIN_BET, MAX_BET = 0.10, 1.00
GAME_CAP = 5.0       # units on one game
DAY_CAP = 25.0       # units in a day
VOID_AFTER = 5       # days
NFL_BET_MIN = 15     # NFL picks carry no start time: bet only within this many minutes of the lock
# Posted picks (since Nov 17, 2026): the same plan, posted from POST_FROM ET for buying on Polymarket US by hand, at the
# Polymarket price then (frozen), for games 30+ minutes away. The at-lock bets above stay as the tested comparison:
# NFL edge picks' prices fall ~8c on average from first listing to the lock, so buying early may cost the edge.
POST_FROM = (11, 0)
POST_LEAD = 30       # minutes before the start
POST_USD = 25.0      # dollars offered near the Polymarket price for the side (the pick's "pd")
# Depth (since Nov 27, 2026): a bet needs its whole stake in dollars offered within 2c of its price on its exchange (the
# pick's "pd" on Polymarket, "kd" on Kalshi), at UNIT_USD a unit, the owner's unit size. In thinner markets a bet that
# size moves the price (the numbers are in the encrypted file, as always). Bets made before the rule that don't meet it
# are kept in the file, marked "thin", and left out of every record (stats).
UNIT_USD = 100.0
BACKTEST_V = 2       # bump when the rule changes what the backtest would have bet: the frozen backtest is replayed once
SPORT_DATA = {"nfl": "data.json", "nba": "nba.json", "nhl": "nhl.json", "mlb": "mlb.json", "tennis": "tennis.json"}


def frac(x):
    return edge_report.frac(x)


def segments():
    """The fixed menu: (key, label, sport, test). Kept short on purpose: the more segments tried, the more
    of them look good by luck."""
    out = []
    for s in SPORTS:
        out += [(f"{s}-edge", f"{SPORT_NAME[s]} picks the model rates {round(EDGE_MIN * 100)}+ points over the price", s,
                 lambda c: c["prob"] - c["pr"] >= EDGE_MIN),
                (f"{s}-value", f"{SPORT_NAME[s]} Value spots", s, lambda c: "V" in c["lists"]),
                (f"{s}-top", f"{SPORT_NAME[s]} Top 25 Surest", s, lambda c: "T" in c["lists"])]
    return out


SEGMENTS = segments()
SEG_BY_KEY = {k: (k, label, s, t) for k, label, s, t in SEGMENTS}


def pick_key(sport, p):
    return "|".join(str(x) for x in (sport, p.get("gid"), p.get("pid"), p.get("stat"), p.get("side"), p.get("line")))


def candidate(sport, p):
    """A recorded pick as a bet candidate, or None if it couldn't really have been bought."""
    if p.get("src") != "live" or p.get("prob") is None:
        return None
    if p.get("th") or p.get("vn") not in ("P", "K") or p.get("hd") or p.get("pj"):
        return None            # thin (<$25 offered), no venue, waiting on injury news, unconfirmed price jump
    if sport in ("nhl", "mlb") and depth.unchecked(p):
        return None
    if not depth.real_price(p):
        return None
    pr = frac(p.get("price"))
    if pr is None or not 0.10 <= pr <= 0.99:
        return None
    day = edge_report.et_day(p)
    if not day or (sport == "nhl" and day < edge_report.NHL_REGULAR):
        return None
    return {"key": pick_key(sport, p), "sport": sport, "day": day, "gid": p.get("gid"), "pid": p.get("pid"),
            "player": p.get("player"), "stat": p.get("stat"), "line": p.get("line"), "side": p.get("side") or "over",
            "pr": pr, "prob": float(p["prob"]), "lists": p.get("lists") or "", "vn": p.get("vn"),
            "start": p.get("start"), "lk": p.get("lk"), "res": p.get("res"),
            # for the methods study (roi4_study.py): both exchanges' prices and depth, the first and closing price, the model's range
            "pp": frac(p.get("pp")), "kp": frac(p.get("kp")), "pd": p.get("pd"), "kd": p.get("kd"),
            "p0": frac(p.get("px0")), "pc": frac(p.get("pxc")), "neff": p.get("neff"), "lo": p.get("lo"), "hi": p.get("hi"),
            "pos": p.get("pos"), "team": p.get("team"), "opp": p.get("opp"), "tour": p.get("tour"),
            "nw": p.get("nw") if isinstance(p.get("nw"), dict) else None, "actual": p.get("actual")}


def load_docs():
    return {s: edge_report.load(f) for s, f in FILES}


def all_candidates(docs):
    out = []
    for s, doc in docs.items():
        if not doc:
            continue
        cols = doc.get("cols") or []
        for row in doc.get("picks") or []:
            c = candidate(s, dict(zip(cols, row)))
            if c:
                out.append(c)
    return out


def all_results(docs):
    """{pick key: result} for every live pick, buyable or not: a bet is graded from its pick even when that pick no
    longer passes candidate() (it went thin, or its price jumped, after the bet was made)."""
    out = {}
    for s, doc in docs.items():
        cols = (doc or {}).get("cols") or []
        for row in (doc or {}).get("picks") or []:
            p = dict(zip(cols, row))
            if p.get("src") == "live":
                out[pick_key(s, p)] = p.get("res")
    return out


def depth_usd(c):
    """Dollars offered within 2c of the price on the bet's exchange, or None if not recorded."""
    d = c.get("pd") if c.get("vn") == "P" else c.get("kd")
    return None if d is None else float(d)


def deep_enough(c, stake):
    d = depth_usd(c)
    return d is not None and d >= stake * UNIT_USD


def all_depths(docs):
    """{pick key: {"pd", "kd"}} for every live pick: the depth behind bets made before the depth rule."""
    out = {}
    for s, doc in docs.items():
        cols = (doc or {}).get("cols") or []
        for row in (doc or {}).get("picks") or []:
            p = dict(zip(cols, row))
            if p.get("src") == "live":
                out[pick_key(s, p)] = {"pd": p.get("pd"), "kd": p.get("kd")}
    return out


def mark_thin(bets, depths):
    """Bets made before the depth rule get its verdict once: their pick's recorded depth on their exchange against
    the stake. Under it: "thin", kept in the file but left out of the records. Returns how many were marked."""
    n = 0
    for b in bets:
        if "depth" in b:
            continue
        d = depths.get(b["key"])
        b["depth"] = depth_usd(dict(d or {}, vn=b.get("vn")))
        if b["depth"] is None or b["depth"] < b["stake"] * UNIT_USD:
            b["thin"] = True
            n += 1
    return n


def edge(c):
    return c["prob"] - c["pr"]


def dedupe(cands):
    """One per player, stat and game: the line the model likes most (then the price nearest 50c)."""
    best = {}
    for c in cands:
        k = (c["sport"], c["gid"], c["pid"], c["stat"])
        b = best.get(k)
        if b is None or (edge(c), -abs(c["pr"] - 0.5)) > (edge(b), -abs(b["pr"] - 0.5)):
            best[k] = c
    return list(best.values())


def ret(c):
    """Return on 1 unit of a graded candidate."""
    return (1 - c["pr"]) / c["pr"] if c["res"] == "hit" else -1.0


def judge(rows, seed):
    """n, game days, return and the low end of the 80% day-bootstrap range of graded rows."""
    n = len(rows)
    if not n:
        return None
    byday = {}
    for c in rows:
        byday.setdefault(c["day"], []).append(ret(c))
    days = list(byday.values())
    rng = random.Random(seed)
    boots = []
    for _ in range(BOOT):
        s = k = 0
        for _ in days:
            d = rng.choice(days)
            s += sum(d)
            k += len(d)
        boots.append(s / k)
    boots.sort()
    return {"n": n, "days": len(days), "roi": round(sum(ret(c) for c in rows) / n, 4), "lo": round(boots[int(BOOT * 0.10)], 4)}


def plan(history, day):
    """The day's plan from graded candidates before it: every menu segment, with its numbers and whether
    it qualifies. history: graded, deduped candidates (any days; only those before `day` and inside the
    lookback are used)."""
    since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=LOOKBACK)).isoformat()
    past = [c for c in history if since <= c["day"] < day]
    out = []
    for key, label, sport, test in SEGMENTS:
        j = judge([c for c in past if c["sport"] == sport and test(c)], f"{day}:{key}")
        if not j:
            continue
        ok = j["n"] >= MIN_N and j["days"] >= MIN_DAYS and j["roi"] >= MIN_ROI and j["lo"] >= LO_FLOOR
        out.append(dict(j, key=key, label=label, sport=sport, ok=ok,
                        r=round(j["roi"] * j["n"] / (j["n"] + SHRINK_N), 4) if ok else None))
    return out


def stake_for(pr, r):
    """Quarter Kelly on the segment's shrunk return r, at price pr, in units of a BANK-unit bankroll."""
    if r is None or r <= 0:
        return 0.0
    f = pr * r / (1 - pr)          # Kelly fraction when the chance is pr * (1 + r)
    s = BANK * KELLY * f
    return round(min(MAX_BET, max(MIN_BET, round(s / 0.05) * 0.05)), 2)


def choose(cands, day_plan, bets):
    """New bets from candidates that just became bettable, given the day's plan and the bets already made
    (all days). Returns the new bets; never changes the old ones."""
    segs = [(s, SEG_BY_KEY[s["key"]][3]) for s in day_plan if s["ok"] and s["key"] in SEG_BY_KEY]
    if not segs:
        return []
    have = {b["key"] for b in bets}
    have_prop = {(b["sport"], b["gid"], b["pid"], b["stat"]) for b in bets}
    fits = []
    for c in dedupe(cands):
        if c["key"] in have or (c["sport"], c["gid"], c["pid"], c["stat"]) in have_prop:
            continue
        mine = [s for s, t in segs if s["sport"] == c["sport"] and t(c)]
        if not mine:
            continue
        seg = max(mine, key=lambda s: s["r"])
        st = stake_for(c["pr"], seg["r"])
        if st > 0:
            fits.append((c, seg, st))
    fits.sort(key=lambda x: (-edge(x[0]), x[0]["key"]))
    out = []
    for c, seg, st in fits:
        day_used = sum(b["stake"] for b in bets + out if b["day"] == c["day"])
        game_used = sum(b["stake"] for b in bets + out if b["day"] == c["day"] and b["gid"] == c["gid"])
        st = round(min(st, GAME_CAP - game_used, DAY_CAP - day_used), 2)
        if st < MIN_BET or not deep_enough(c, st):   # the whole stake has to be offered within 2c, or the bet moves the price
            continue
        out.append({"key": c["key"], "sport": c["sport"], "day": c["day"], "gid": c["gid"], "pid": c["pid"],
                    "player": c["player"], "stat": c["stat"], "line": c["line"], "side": c["side"],
                    "price": c["pr"], "prob": round(c["prob"], 3), "vn": c["vn"], "seg": seg["key"], "stake": st, "depth": depth_usd(c),
                    "start": c.get("start"), "team": c.get("team"), "opp": c.get("opp"),   # for the tab's live tracking
                    "res": None, "pnl": None})
    return out


def settle(bet, res):
    """Grade a bet from its pick's result. Returns True if it changed."""
    if bet.get("res") is not None or res is None:
        return False
    if res == "hit":
        bet["res"], bet["pnl"] = "hit", round(bet["stake"] * (1 - bet["price"]) / bet["price"], 4)
    elif res == "miss":
        bet["res"], bet["pnl"] = "miss", -bet["stake"]
    else:                                  # push, DNP, void: the stake comes back
        bet["res"], bet["pnl"] = "void", 0.0
    return True


def grade(bets, results, today):
    """results: {pick key: res}. Old pending bets with no result are voided. A bet that was voided that way and whose
    pick has since been graded hit or miss gets that result (before Nov 26, 2026 results came only from buyable picks,
    so a pick that went thin after the bet was made could never grade it)."""
    changed = False
    for b in bets:
        r = results.get(b["key"])
        if b.get("res") == "void" and r in ("hit", "miss") and not b.get("regraded"):
            b["res"], b["regraded"] = None, True
            changed |= settle(b, r)
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=VOID_AFTER)).isoformat()
    for b in bets:
        if b.get("res") is not None:
            continue
        r = results.get(b["key"])
        if r is None and b["day"] < cutoff:
            r = "void"
        changed |= settle(b, r)
    return changed


def stats(bets, days_planned=()):
    """Every number the tab shows, from graded bets."""
    thin = sum(1 for b in bets if b.get("thin"))
    bets = [b for b in bets if not b.get("thin")]   # bets made before the depth rule that broke it: left out of every record
    done = [b for b in bets if b.get("res") in ("hit", "miss")]
    byday = {}
    for b in done:
        d = byday.setdefault(b["day"], {"day": b["day"], "n": 0, "staked": 0.0, "pnl": 0.0, "hit": 0})
        d["n"] += 1
        d["staked"] += b["stake"]
        d["pnl"] += b["pnl"]
        d["hit"] += b["res"] == "hit"
    daily, cum, peak, dd, run, worst_run = [], 0.0, 0.0, 0.0, 0, 0
    cum_staked = 0.0
    for day in sorted(byday):
        d = byday[day]
        cum += d["pnl"]
        cum_staked += d["staked"]
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        run = run + 1 if d["pnl"] < 0 else 0
        worst_run = max(worst_run, run)
        daily.append({"day": day, "n": d["n"], "hit": d["hit"], "staked": round(d["staked"], 2), "pnl": round(d["pnl"], 2),
                      "roi": round(d["pnl"] / d["staked"], 4) if d["staked"] else None,
                      "cum": round(cum, 2), "cum_staked": round(cum_staked, 2),
                      "cum_roi": round(cum / cum_staked, 4) if cum_staked else None})
    staked = sum(b["stake"] for b in done)
    won = sum(b["pnl"] for b in done)
    rois = sorted(d["roi"] for d in daily if d["roi"] is not None)
    sport = {}
    for b in done:
        s = sport.setdefault(b["sport"], {"n": 0, "hit": 0, "staked": 0.0, "pnl": 0.0})
        s["n"] += 1
        s["hit"] += b["res"] == "hit"
        s["staked"] += b["stake"]
        s["pnl"] += b["pnl"]
    loss_streak = cur = 0
    for b in sorted(done, key=lambda b: (b["day"], b["key"])):
        cur = cur + 1 if b["res"] == "miss" else 0
        loss_streak = max(loss_streak, cur)
    n = len(done)
    return {
        "n": n, "hit": round(sum(b["res"] == "hit" for b in done) / n, 4) if n else None,
        "staked": round(staked, 2), "pnl": round(won, 2), "roi": round(won / staked, 4) if staked else None,
        "avg_stake": round(staked / n, 3) if n else None,
        "avg_price": round(sum(b["price"] for b in done) / n, 3) if n else None,
        "days": len(daily), "days_hit": sum(1 for d in daily if d["roi"] is not None and d["roi"] >= TARGET),
        "days_up": sum(1 for d in daily if d["pnl"] > 0), "days_down": sum(1 for d in daily if d["pnl"] < 0),
        "no_bet_days": sum(1 for d in days_planned if d not in byday),
        "best_day": rois[-1] if rois else None, "worst_day": rois[0] if rois else None,
        "median_day": rois[len(rois) // 2] if rois else None,
        "max_dd": round(dd, 2), "losing_days_run": worst_run, "losing_bets_run": loss_streak,
        "voids": sum(1 for b in bets if b.get("res") == "void"), "thin": thin,
        "by_sport": {k: {"n": v["n"], "hit": round(v["hit"] / v["n"], 4), "staked": round(v["staked"], 2),
                         "pnl": round(v["pnl"], 2), "roi": round(v["pnl"] / v["staked"], 4) if v["staked"] else None}
                     for k, v in sorted(sport.items())},
        "daily": daily,
        **monthly(daily),
    }


def monthly(daily):
    """The month-by-month record: the return on units staked (judged against the 4%-a-month target) and units
    won as a share of the BANK-unit bankroll. The current month is still running; the tab marks it."""
    months = {}
    for d in daily:
        m = months.setdefault(d["day"][:7], {"month": d["day"][:7], "n": 0, "days": 0, "staked": 0.0, "pnl": 0.0})
        m["n"] += d["n"]
        m["days"] += 1
        m["staked"] += d["staked"]
        m["pnl"] += d["pnl"]
    out = [{"month": m["month"], "n": m["n"], "days": m["days"], "staked": round(m["staked"], 2), "pnl": round(m["pnl"], 2),
            "bank": round(m["pnl"] / BANK, 4), "roi": round(m["pnl"] / m["staked"], 4) if m["staked"] else None}
           for m in (months[k] for k in sorted(months))]
    return {"monthly": out, "months_hit": sum(1 for m in out if (m["roi"] or 0) >= MONTH_TARGET),
            "months_down": sum(1 for m in out if m["pnl"] < 0)}


def outlook(daily, calendar_days, sims=5000, seed=4):
    """What a 30-day month could look like, from the backtest's own betting days: bootstrap months of the same
    number of betting days, with the edge as replayed, halved, and gone (each day's units shifted so the whole
    replay returns that much on its stakes). Each month's return on the units it staked, the 4% goal's measure."""
    if not daily or not calendar_days:
        return None
    k = max(1, round(len(daily) / calendar_days * 30))
    staked = sum(d["staked"] for d in daily)
    pnl = sum(d["pnl"] for d in daily)
    rng, out = random.Random(seed), []
    for label, roi in (("As replayed", None), ("Edge half as big", pnl / staked / 2 if staked else 0), ("No edge (the market's -2%)", -0.02)):
        days = [(d["pnl"] + ((roi * staked - pnl) * d["staked"] / staked if roi is not None and staked else 0), d["staked"]) for d in daily]
        res = []
        for _ in range(sims):
            pick = [rng.choice(days) for _ in range(k)]
            st = sum(x[1] for x in pick)
            res.append(sum(x[0] for x in pick) / st if st else 0.0)
        res.sort()
        out.append({"label": label, "roi": round(pnl / staked if roi is None else roi, 4), "median": round(res[sims // 2], 4),
                    "p_hit": round(sum(r >= MONTH_TARGET for r in res) / sims, 3), "p_down": round(sum(r < 0 for r in res) / sims, 3),
                    "bad": round(res[sims // 20], 4), "good": round(res[sims - sims // 20 - 1], 4)})
    return {"bet_days": k, "staked": round(staked / calendar_days * 30, 1), "rows": out}


def backtest(cands, until):
    """Replays the rule over every day before `until` that has graded picks, each day planned only from
    picks graded before it. Returns (bets, {day: plan})."""
    graded = dedupe([c for c in cands if c["res"] in ("hit", "miss") and c["day"] < until])
    results = {c["key"]: c["res"] for c in cands}
    pool = [c for c in cands if c["day"] < until and c["res"] is not None]
    days = sorted({c["day"] for c in pool})
    bets, plans = [], {}
    for day in days:
        p = plan(graded, day)
        plans[day] = p
        today = [c for c in pool if c["day"] == day]
        # games lock in start order: bet each game's picks together, in that order, like the live passes
        order = sorted({(c.get("start") or c.get("lk") or "", c["gid"]) for c in today})
        for _, gid in order:
            bets += choose([c for c in today if c["gid"] == gid], p, bets)
    grade(bets, results, "9999-12-31")
    return bets, plans


def utc(s):
    if not s:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def bettable(c, now):
    """Locked (its price is final) and its game not started."""
    if c["res"] is not None or not c.get("lk"):
        return False
    start = utc(c.get("start"))
    if start is not None:
        return now < start
    lk = utc(c["lk"])
    return lk is not None and now < lk + datetime.timedelta(minutes=NFL_BET_MIN)


def slim_plan(p):
    return [{k: s[k] for k in ("key", "label", "sport", "n", "days", "roi", "lo", "ok", "r")} for s in p]


def load_meta():
    """What a posted pick needs that the picks files don't carry: each game's Polymarket event slug (the sport files'
    "links", as the pages use them) and NFL kickoff times (slate.json; NFL picks carry no start)."""
    links = {}
    for sport, path in SPORT_DATA.items():
        doc = edge_report.load(path) or {}
        for gid, g in (doc.get("links") or {}).items():
            if isinstance(g, dict) and g.get("p"):
                links[(sport, str(gid))] = g["p"]
    starts = {str(g.get("gid")): g.get("start") for g in (edge_report.load("slate.json") or {}).get("games") or [] if g.get("gid")}
    return {"links": links, "nfl_starts": starts}


def post_candidates(cands, now, meta):
    """Today's picks that can still be posted for buying on Polymarket US: not locked, the game 30+ minutes away,
    a Polymarket price for the side with POST_USD+ offered near it. Priced at that Polymarket price."""
    today = now.astimezone(ET).date().isoformat()
    out = []
    for c in cands:
        if c["day"] != today or c["res"] is not None or c.get("lk"):
            continue
        start = c.get("start")
        if not start and c["sport"] == "nfl":
            start = (meta.get("nfl_starts") or {}).get(str(c["gid"]))
        t = utc(start)
        if t is None or t < now + datetime.timedelta(minutes=POST_LEAD):
            continue
        pp = c.get("pp")
        if pp is None or not 0.10 <= pp <= 0.95 or (c.get("pd") or 0) < POST_USD:
            continue
        out.append(dict(c, pr=pp, vn="P", start=start))
    return out


def post(state, cands, now, meta):
    """From POST_FROM ET, post today's picks that fit the day's plan at their Polymarket price (frozen once posted),
    with the event link and the most worth paying. Returns the new ones."""
    et = now.astimezone(ET)
    if (et.hour, et.minute) < POST_FROM:
        return []
    today = et.date().isoformat()
    pool = {c["key"]: c for c in post_candidates(cands, now, meta)}
    new = choose(list(pool.values()), state["plans"][today], state["posted"])
    for b in new:
        c = pool[b["key"]]
        slug = (meta.get("links") or {}).get((c["sport"], str(c["gid"])))
        b.update({"start": c["start"], "team": c.get("team"), "opp": c.get("opp"), "posted": now.strftime("%Y-%m-%dT%H:%MZ"),
                  "url": f"https://polymarket.us/event/{slug}" if slug else None,
                  # the most worth paying: where the model is still EDGE_MIN over (Value / Top 25 picks: the posted price)
                  "max": round(max(b["price"], int((c["prob"] - EDGE_MIN) * 100) / 100), 2) if b["seg"].endswith("-edge") else b["price"]})
    state["posted"] += new
    return new


def season_stats(state):
    """The at-lock record from the start of the backtest: the backtest's bets, then the live ones (each tagged)."""
    bt = [dict(b, src="backtest") for b in (state.get("backtest") or {}).get("bets") or []]
    return stats(bt + [dict(b, src="live") for b in state.get("bets") or []])


def update(state, cands, now, meta=None, results=None, depths=None):
    """One pass: freeze the backtest (first run), plan today, post today's Polymarket picks (from 11 AM ET), add the
    at-lock bets, grade both. Returns True on a change."""
    meta = meta or {}
    before = json.dumps(state, sort_keys=True)
    state.setdefault("posted", [])
    today = now.astimezone(ET).date().isoformat()
    state.setdefault("live_from", today)
    state.setdefault("bets", [])
    plans = state.setdefault("plans", {})
    if (state.get("backtest") or {}).get("v") != BACKTEST_V:   # first run, or a rule change: replay the backtest once
        bt, bt_plans = backtest(cands, state["live_from"])
        bts = stats(bt, bt_plans.keys())
        state["backtest"] = {"bets": bt, "stats": bts, "outlook": outlook(bts["daily"], len(bt_plans)),
                             "qualified": {d: [s["key"] for s in p if s["ok"]] for d, p in bt_plans.items()}, "v": BACKTEST_V}
    # recomputed every run from the frozen backtest days (seeded, so it only moves when the method does)
    state["backtest"]["outlook"] = outlook(state["backtest"]["stats"]["daily"], len(state["backtest"].get("qualified") or {}))
    if "study" not in state:     # every other method, replayed the same way (roi4_study.py), frozen like the backtest
        try:
            import roi4_study
            state["study"] = roi4_study.study(cands, state["live_from"])
        except Exception as e:  # noqa: BLE001 - the study is extra: without it the track still bets
            print(f"4% return: methods study failed ({type(e).__name__}: {e})")
    graded = dedupe([c for c in cands if c["res"] in ("hit", "miss")])
    if today not in plans:
        plans[today] = slim_plan(plan(graded, today))
    post(state, cands, now, meta)
    state["bets"] += choose([c for c in cands if c["day"] == today and bettable(c, now)], plans[today], state["bets"])
    by_key = {c["key"]: c for c in cands}
    for b in state["bets"]:   # pending bets made before Nov 23, 2026 lack the game details the live tracker needs
        c = by_key.get(b["key"])
        if b.get("res") is None and c and not b.get("start"):
            b.update({"start": c.get("start"), "team": c.get("team"), "opp": c.get("opp")})
    depth_map = dict({c["key"]: {"pd": c.get("pd"), "kd": c.get("kd")} for c in cands}, **(depths or {}))
    mark_thin(state["bets"], depth_map)
    mark_thin(state["posted"], depth_map)
    results = dict({c["key"]: c["res"] for c in cands}, **(results or {}))   # every live pick's result (all_results), not just the buyable ones
    grade(state["bets"], results, today)
    grade(state["posted"], results, today)
    state["stats"] = stats(state["bets"], [d for d in plans if d < today])
    state["posted_stats"] = stats(state["posted"], [d for d in plans if d < today])
    state["season"] = season_stats(state)
    state["rules"] = {"target": TARGET, "edge_min": EDGE_MIN, "lookback": LOOKBACK, "min_n": MIN_N, "min_days": MIN_DAYS,
                      "min_roi": MIN_ROI, "lo_floor": LO_FLOOR, "shrink_n": SHRINK_N, "bank": BANK, "kelly": KELLY,
                      "min_bet": MIN_BET, "max_bet": MAX_BET, "game_cap": GAME_CAP, "day_cap": DAY_CAP,
                      "month_target": MONTH_TARGET, "review_on": REVIEW_ON,
                      "post_from": "%d:%02d" % POST_FROM, "post_lead": POST_LEAD, "post_usd": POST_USD, "unit_usd": UNIT_USD}
    return json.dumps(state, sort_keys=True) != before


def print_backtest(cands, until):
    bets, plans = backtest(cands, until)
    s = stats(bets, plans.keys())
    print(f"backtest to {until}: {s['n']} bets on {s['days']} days ({s['no_bet_days']} days with no bet)")
    if s["n"]:
        print(f"  staked {s['staked']}u, won {s['pnl']:+}u, return {s['roi']:+.2%}, hit {s['hit']:.1%}, "
              f"avg stake {s['avg_stake']}u at {s['avg_price']:.2f}")
        print(f"  days at 4%+: {s['days_hit']}/{s['days']}, up {s['days_up']}, down {s['days_down']}, "
              f"median day {s['median_day']:+.1%}, worst {s['worst_day']:+.1%}, best {s['best_day']:+.1%}")
        print(f"  max drawdown {s['max_dd']}u, longest losing run {s['losing_days_run']} days / {s['losing_bets_run']} bets")
        for k, v in s["by_sport"].items():
            print(f"  {k}: {v['n']} bets, {v['staked']}u staked, {v['pnl']:+}u, {v['roi']:+.2%}")
        for d in s["daily"]:
            print(f"    {d['day']} {d['n']:4d} bets {d['staked']:6.2f}u {d['pnl']:+7.2f}u {d['roi']:+7.1%}  cum {d['cum']:+.2f}u")
    seen = {}
    for d, p in sorted(plans.items()):
        for x in p:
            if x["ok"]:
                seen.setdefault(x["key"], []).append(d)
    for k, ds in seen.items():
        print(f"  qualified {k}: {len(ds)} days, {ds[0]}..{ds[-1]}")
    return s


def main():
    now = datetime.datetime.now(UTC)
    docs = load_docs()
    cands = all_candidates(docs)
    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        print_backtest(cands, sys.argv[2] if len(sys.argv) > 2 else now.astimezone(ET).date().isoformat())
        return 0
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not password:
        print("4% return: TEAM_DASH_PASSWORD not set, skipping")
        return 0
    try:
        with open(OUT, encoding="ascii") as f:
            state = json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        state = {}
    if not update(state, cands, now, load_meta(), all_results(docs), all_depths(docs)):
        print(f"4% return: no change ({len(state.get('bets') or [])} live bets)")
        return 0
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":"), ensure_ascii=True), password) + "\n")
    s = state["stats"]
    print(f"4% return: wrote {OUT} ({len(state['bets'])} live bets, return {s['roi']}, backtest {state['backtest']['stats']['roi']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - a team-only page never fails the deploy
        print(f"4% return failed ({type(e).__name__}: {e})")
        sys.exit(0)

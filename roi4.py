"""
Prop Streak Lab — the "4% return" track (team only, never public): paper bets, sized in units, aiming at
a 4% return on every unit staked.

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

TARGET = 0.04        # the owner's goal: 4% back on every unit staked
EDGE_MIN = 0.10      # the "model edge" segments: the model's chance at least 10 points over the price
LOOKBACK = 42        # days of graded picks a segment is judged on
MIN_N = 300          # graded picks (one per player, stat and game) a segment needs
MIN_DAYS = 6         # over this many game days
MIN_ROI = TARGET     # returning the target or better
LO_FLOOR = 0.0       # and the low end of its 80% bootstrap range above zero (a looser -3% let NHL in on a hot streak: -15% after)
BOOT = 300
SHRINK_N = 500       # r * n / (n + SHRINK_N): a segment's past return is trusted more as it grows
BANK = 100.0         # units: the stake is a fraction of this
KELLY = 0.25         # quarter Kelly
MIN_BET, MAX_BET = 0.10, 1.00
GAME_CAP = 5.0       # units on one game
DAY_CAP = 25.0       # units in a day
VOID_AFTER = 5       # days
NFL_BET_MIN = 15     # NFL picks carry no start time: bet only within this many minutes of the lock


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
        if st < MIN_BET:
            continue
        out.append({"key": c["key"], "sport": c["sport"], "day": c["day"], "gid": c["gid"], "pid": c["pid"],
                    "player": c["player"], "stat": c["stat"], "line": c["line"], "side": c["side"],
                    "price": c["pr"], "prob": round(c["prob"], 3), "vn": c["vn"], "seg": seg["key"], "stake": st,
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
    """results: {pick key: res}. Old pending bets with no result are voided."""
    changed = False
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
        "voids": sum(1 for b in bets if b.get("res") == "void"),
        "by_sport": {k: {"n": v["n"], "hit": round(v["hit"] / v["n"], 4), "staked": round(v["staked"], 2),
                         "pnl": round(v["pnl"], 2), "roi": round(v["pnl"] / v["staked"], 4) if v["staked"] else None}
                     for k, v in sorted(sport.items())},
        "daily": daily,
    }


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


def update(state, cands, now):
    """One pass: freeze the backtest (first run), plan today, add today's new bets, grade. Returns True on a change."""
    before = json.dumps(state, sort_keys=True)
    today = now.astimezone(ET).date().isoformat()
    state.setdefault("live_from", today)
    state.setdefault("bets", [])
    plans = state.setdefault("plans", {})
    if "backtest" not in state:
        bt, bt_plans = backtest(cands, state["live_from"])
        state["backtest"] = {"bets": bt, "stats": stats(bt, bt_plans.keys()),
                             "qualified": {d: [s["key"] for s in p if s["ok"]] for d, p in bt_plans.items()}}
    if "study" not in state:     # every other method, replayed the same way (roi4_study.py), frozen like the backtest
        try:
            import roi4_study
            state["study"] = roi4_study.study(cands, state["live_from"])
        except Exception as e:  # noqa: BLE001 - the study is extra: without it the track still bets
            print(f"4% return: methods study failed ({type(e).__name__}: {e})")
    graded = dedupe([c for c in cands if c["res"] in ("hit", "miss")])
    if today not in plans:
        plans[today] = slim_plan(plan(graded, today))
    state["bets"] += choose([c for c in cands if c["day"] == today and bettable(c, now)], plans[today], state["bets"])
    grade(state["bets"], {c["key"]: c["res"] for c in cands}, today)
    state["stats"] = stats(state["bets"], [d for d in plans if d < today])
    state["rules"] = {"target": TARGET, "edge_min": EDGE_MIN, "lookback": LOOKBACK, "min_n": MIN_N, "min_days": MIN_DAYS,
                      "min_roi": MIN_ROI, "lo_floor": LO_FLOOR, "shrink_n": SHRINK_N, "bank": BANK, "kelly": KELLY,
                      "min_bet": MIN_BET, "max_bet": MAX_BET, "game_cap": GAME_CAP, "day_cap": DAY_CAP}
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
    cands = all_candidates(load_docs())
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
    if not update(state, cands, now):
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

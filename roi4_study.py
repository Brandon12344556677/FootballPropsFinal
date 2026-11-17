"""
Prop Streak Lab — the 4% return track's methods study (team only): every way of choosing and sizing bets
we could think of, replayed walk-forward on the same recorded picks the track bets from, so they can be
compared on one footing.

Walk-forward: from TEST_FROM, each day's bets are chosen using only picks graded before that day (models
refit weekly), then graded on that day's results. Bets are priced at the locked price, $25+ offered, as in
roi4.py. Each method gets its record, its return on units staked, a 90% range (bootstrap over game days),
the share of betting days at 4%+, its worst drawdown, and its return by sport.

Families: baselines (every pick, each list), fixed model-edge cut-offs, the walk-forward segment rule roi4.py
uses, recalibrating the model on past results, blending model and market (logistic regression), price bands
(favourite/longshot), over/under, stat by side cells, market moves before lock (follow and fade), the two
exchanges disagreeing, line shopping, model confidence (games of history, range width), hot streaks, fading the
model, two-leg parlays of the best bets, and staking/money-management rules (flat, Kelly variants, stop after a
4% day, doubling after a losing day). Pick of the Day is shown from botd.json.

roi4.py runs study() once and freezes its result into team/roi4.enc, so the dashboard's 4% return tab can show
it (the numbers stay encrypted: this public file holds the methods, never their results).
`python roi4_study.py` prints it. Standard library only.
"""
import datetime
import json
import math
import random
import sys

import roi4

TEST_FROM = "2026-10-15"   # a month of graded NFL/NHL/MLB picks before the first test day
BOOT = 300
REFIT_DAYS = 7
FEW = 100            # methods with fewer bets than this are listed last: too few to judge
TARGET = roi4.TARGET


def ret(c, pr=None):
    pr = c["pr"] if pr is None else pr
    return (1 - pr) / pr if c["res"] == "hit" else -1.0


def edge(c):
    return c["prob"] - c["pr"]


def logit(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def judge(rows):
    """Returns n, days, roi and the 10th-percentile day-bootstrap return of graded rows (1 unit each)."""
    return roi4.judge(rows, "study")


def qualify(train, keyfn, day, min_n=300, min_days=6, lookback=42, min_roi=TARGET, lo_floor=0.0, recent=None):
    """Keys of the cells (keyfn) that earned it on the past: the roi4.py test applied to any grouping."""
    since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=recent or lookback)).isoformat()
    cells = {}
    for c in train:
        if c["day"] >= since:
            k = keyfn(c)
            if k is not None:
                cells.setdefault(k, []).append(c)
    out = {}
    for k, rows in cells.items():
        if len(rows) < min_n:
            continue
        j = roi4.judge(rows, f"{day}:{k}")
        if j["days"] >= min_days and j["roi"] >= min_roi and j["lo"] >= lo_floor:
            out[k] = j
    return out


# ---------------------------------------------------------------- models fit on the past
def fit_logistic(rows, iters=8):
    """P(hit) = sigmoid(a + b * logit(price) + c * (logit(model) - logit(price))), by Newton's method (ridge 1)."""
    w = [0.0, 1.0, 0.0]
    xs = [(1.0, logit(c["pr"]), logit(c["prob"]) - logit(c["pr"])) for c in rows]
    ys = [1.0 if c["res"] == "hit" else 0.0 for c in rows]
    for _ in range(iters):
        g = [0.0, 0.0, 0.0]
        h = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
        g = [w[0] * 1.0, (w[1] - 1.0) * 1.0, w[2] * 1.0]     # ridge toward "the market is right"
        for x, y in zip(xs, ys):
            z = w[0] * x[0] + w[1] * x[1] + w[2] * x[2]
            p = 1 / (1 + math.exp(-max(min(z, 30), -30)))
            for i in range(3):
                g[i] += (p - y) * x[i]
                for j in range(3):
                    h[i][j] += p * (1 - p) * x[i] * x[j]
        w = [a - b for a, b in zip(w, solve3(h, g))]
    return w


def solve3(a, b):
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(m[r][i]))
        m[i], m[piv] = m[piv], m[i]
        if abs(m[i][i]) < 1e-12:
            return [0.0, 0.0, 0.0]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [x - f * y for x, y in zip(m[r], m[i])]
    return [m[i][3] / m[i][i] for i in range(3)]


def p_logistic(w, c):
    z = w[0] + w[1] * logit(c["pr"]) + w[2] * (logit(c["prob"]) - logit(c["pr"]))
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))


def fit_bins(rows, width=0.05):
    """Model chance -> how often such picks really hit, in bins (with a +1/+2 prior)."""
    bins = {}
    for c in rows:
        b = bins.setdefault(int(c["prob"] / width), [0, 0])
        b[0] += c["res"] == "hit"
        b[1] += 1
    return {k: ((h + 1) / (n + 2), n) for k, (h, n) in bins.items()}


# ---------------------------------------------------------------- the harness
class Ctx:
    """Per-method cache for things refit every REFIT_DAYS."""
    def __init__(self):
        self.fit_day, self.models = None, {}

    def refit(self, day, fn):
        if self.fit_day is None or (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(self.fit_day)).days >= REFIT_DAYS:
            self.models, self.fit_day = fn(), day
        return self.models


def run(method, graded, by_day, days):
    """Walk-forward: method(train, today, day, ctx) -> [(cand, stake, price)] per day."""
    bets, ctx, i = [], Ctx(), 0
    for day in days:
        while i < len(graded) and graded[i]["day"] < day:
            i += 1
        today = by_day.get(day, [])
        for c, stake, pr in method(graded[:i], today, day, ctx, bets):
            bets.append({"day": day, "sport": c["sport"], "res": c["res"], "stake": stake, "price": pr, "key": c["key"],
                         "pnl": stake * ret(c, pr), "gid": c["gid"]})
    return bets


def summarize(name, family, bets, note=""):
    done = [b for b in bets if b["res"] in ("hit", "miss")]
    s = roi4.stats(done)
    byday = {}
    for b in done:
        d = byday.setdefault(b["day"], [0.0, 0.0])
        d[0] += b["pnl"]
        d[1] += b["stake"]
    days = list(byday.values())
    lo = hi = None
    if days:
        rng, boots = random.Random(name), []
        for _ in range(BOOT):
            pn = st = 0.0
            for _ in days:
                d = rng.choice(days)
                pn += d[0]
                st += d[1]
            boots.append(pn / st if st else 0)
        boots.sort()
        lo, hi = boots[int(BOOT * 0.05)], boots[int(BOOT * 0.95) - 1]
    return {"name": name, "family": family, "note": note, "n": s["n"], "days": s["days"], "staked": s["staked"],
            "pnl": s["pnl"], "roi": s["roi"], "lo": None if lo is None else round(lo, 4), "hi": None if hi is None else round(hi, 4),
            "days_hit": s["days_hit"], "max_dd": s["max_dd"], "worst_day": s["worst_day"], "hit": s["hit"],
            "avg_price": s["avg_price"], "by_sport": {k: [v["n"], v["roi"]] for k, v in s["by_sport"].items()}}


# ---------------------------------------------------------------- methods
def flat(test, dedup=True):
    def m(train, today, day, ctx, bets):
        pool = roi4.dedupe(today) if dedup else today
        return [(c, 1.0, c["pr"]) for c in pool if test(c)]
    return m


def cells_rule(keyfn, test=lambda c: True, **kw):
    """Bet every pick (that passes test) in a cell that qualified on the past."""
    def m(train, today, day, ctx, bets):
        ok = qualify([c for c in train_dedupe(ctx, train, day) if test(c)], keyfn, day, **kw)
        return [(c, 1.0, c["pr"]) for c in roi4.dedupe(today) if test(c) and keyfn(c) in ok]
    return m


def train_dedupe(ctx, train, day):
    """Deduped training picks, cached per day (several cell rules share the work)."""
    if getattr(ctx, "dd_day", None) != day:
        ctx.dd_day, ctx.dd = day, roi4.dedupe(train)
    return ctx.dd


def calibrated(margin, by_sport=True):
    def m(train, today, day, ctx, bets):
        models = ctx.refit(day, lambda: {s: fit_bins([c for c in train if c["sport"] == s]) for s in roi4.SPORTS} if by_sport
                           else {"all": fit_bins(train)})
        out = []
        for c in roi4.dedupe(today):
            b = models.get(c["sport"] if by_sport else "all", {}).get(int(c["prob"] / 0.05))
            if b and b[1] >= 100 and b[0] - c["pr"] >= margin:
                out.append((c, 1.0, c["pr"]))
        return out
    return m


def blended(margin, stake="flat", sports=None):
    def m(train, today, day, ctx, bets):
        models = ctx.refit(day, lambda: {s: fit_logistic(rows) for s in roi4.SPORTS
                                         for rows in [[c for c in train if c["sport"] == s]] if len(rows) >= 1000})
        out = []
        for c in roi4.dedupe(today):
            if sports and c["sport"] not in sports or c["sport"] not in models:
                continue
            q = p_logistic(models[c["sport"]], c)
            if q - c["pr"] >= margin:
                if stake == "kelly":     # quarter Kelly on the blended chance, 100-unit bank, capped
                    st = min(roi4.MAX_BET, max(roi4.MIN_BET, 25 * (q - c["pr"]) / (1 - c["pr"])))
                else:
                    st = 1.0
                out.append((c, round(st, 2), c["pr"]))
        return out
    return m


def roi4_rule(train, today, day, ctx, bets):
    """roi4.py's own rule (segments, quarter Kelly, caps), run through the same harness."""
    p = roi4.plan(train_dedupe(ctx, train, day), day)
    mine = [b for b in getattr(ctx, "r4", [])]
    order = sorted({(c.get("start") or c.get("lk") or "", c["gid"]) for c in today})
    out = []
    for _, gid in order:
        new = roi4.choose([c for c in today if c["gid"] == gid], p, mine)
        mine += new
        idx = {c["key"]: c for c in today}
        out += [(idx[b["key"]], b["stake"], b["price"]) for b in new]
    ctx.r4 = mine
    return out


def moved(sign, cents=3, test=lambda c: True):
    """Bought at the closing price (the only one there is once the move is known)."""
    def m(train, today, day, ctx, bets):
        out = []
        for c in roi4.dedupe(today):
            if c.get("p0") is None or not test(c):
                continue
            if round((c["pr"] - c["p0"]) * 100) * sign >= cents:
                out.append((c, 1.0, c["pr"]))
        return out
    return m


def disagree(gap):
    """Both exchanges quote the side: bet when the other one is gap+ dearer than the price we pay."""
    def m(train, today, day, ctx, bets):
        out = []
        for c in roi4.dedupe(today):
            if c.get("pp") is None or c.get("kp") is None:
                continue
            other = max(c["pp"], c["kp"])
            if other - c["pr"] >= gap:
                out.append((c, 1.0, c["pr"]))
        return out
    return m


def parlays2(base):
    """Two-leg parlays of the base method's bets, the biggest model edges first, legs from different games."""
    def m(train, today, day, ctx, bets):
        legs = sorted(base(train, today, day, ctx, bets), key=lambda x: -edge(x[0]))
        out, used = [], set()
        for i, (a, _, pa) in enumerate(legs):
            if a["key"] in used:
                continue
            for b, _, pb in legs[i + 1:]:
                if b["key"] in used or b["gid"] == a["gid"]:
                    continue
                used |= {a["key"], b["key"]}
                both = dict(a, res="hit" if a["res"] == "hit" and b["res"] == "hit" else "miss", key=a["key"] + "+" + b["key"])
                out.append((both, 1.0, pa * pb))
                break
        return out
    return m


def stop_at_target(base):
    """Bet the base method's picks game by game in start order; once the day's settled bets are up 4%+, stop.
    Optimistic: it assumes each game is settled before the next one locks."""
    def m(train, today, day, ctx, bets):
        picks = base(train, today, day, ctx, bets)
        slots = {}
        for x in picks:
            slots.setdefault(x[0].get("start") or x[0].get("lk") or x[0]["gid"], []).append(x)
        out, pn, st = [], 0.0, 0.0
        for k in sorted(slots):
            if st and pn / st >= TARGET:
                break
            for c, s, pr in slots[k]:
                out.append((c, s, pr))
                pn += s * ret(c, pr)
                st += s
        return out
    return m


def double_after_loss(base, cap=8):
    """Martingale by day: the stake doubles after a losing day and resets after a winning one."""
    def m(train, today, day, ctx, bets):
        mult = getattr(ctx, "mult", 1)
        last = [b for b in bets if b["day"] < day]
        if last:
            prev = max(b["day"] for b in last)
            pn = sum(b["pnl"] for b in last if b["day"] == prev)
            if getattr(ctx, "seen", None) != prev:
                mult = min(cap, mult * 2) if pn < 0 else 1
                ctx.seen = prev
        ctx.mult = mult
        return [(c, s * mult, pr) for c, s, pr in base(train, today, day, ctx, bets)]
    return m


def kelly_seg(base_test, frac=0.25):
    """The base picks staked by Kelly on the model's own chance (no shrinking), capped at MAX_BET."""
    def m(train, today, day, ctx, bets):
        out = []
        for c in roi4.dedupe(today):
            if base_test(c):
                f = max(0.0, (c["prob"] - c["pr"]) / (1 - c["pr"]))
                out.append((c, round(min(roi4.MAX_BET, max(roi4.MIN_BET, 100 * frac * f)), 2), c["pr"]))
        return out
    return m


def edge_prop(base_test):
    def m(train, today, day, ctx, bets):
        return [(c, round(min(2.0, max(0.1, edge(c) * 10)), 2), c["pr"]) for c in roi4.dedupe(today) if base_test(c)]
    return m


def methods():
    E = lambda e, s=None: (lambda c: edge(c) >= e and (s is None or c["sport"] == s))
    nfl_edge = E(0.10, "nfl")
    out = [
        ("Every buyable pick, 1 unit each", "Baseline", flat(lambda c: True)),
        ("Value spots, every sport", "Baseline", flat(lambda c: "V" in c["lists"])),
        ("Top 25 Surest, every sport", "Baseline", flat(lambda c: "T" in c["lists"])),
    ]
    for s in roi4.SPORTS:
        out.append((f"Every {roi4.SPORT_NAME[s]} pick", "Baseline", flat(lambda c, s=s: c["sport"] == s)))
    for e in (0.05, 0.10, 0.15, 0.20, 0.30):
        out.append((f"Model {round(e * 100)}+ points over the price, every sport", "Model edge (fixed)", flat(E(e))))
    for s in roi4.SPORTS:
        for e in (0.10, 0.20):
            out.append((f"{roi4.SPORT_NAME[s]}: model {round(e * 100)}+ points over", "Model edge (fixed)", flat(E(e, s))))
    out.append(("Model 10-20 points over (no wild ones), every sport", "Model edge (fixed)", flat(lambda c: 0.10 <= edge(c) < 0.20)))
    out.append(("NFL model 10+ over, every line (no line shopping)", "Line shopping", flat(nfl_edge, dedup=False)))
    out.append(("NFL model 10+ over, best line per player and stat", "Line shopping", flat(nfl_edge)))
    out.append(("roi4.py rule: proven segments, quarter Kelly, caps", "Walk-forward segments", roi4_rule))
    out.append(("Segments by sport and list, flat", "Walk-forward segments",
                cells_rule(lambda c: (c["sport"], "V" if "V" in c["lists"] else "T" if "T" in c["lists"] else
                                      "E" if edge(c) >= 0.10 else None))))
    out.append(("Sport x stat x side cells that earned it", "Walk-forward cells",
                cells_rule(lambda c: (c["sport"], c["stat"], c["side"]), min_n=200)))
    out.append(("Sport x stat x side cells, model 5+ over only", "Walk-forward cells",
                cells_rule(lambda c: (c["sport"], c["stat"], c["side"]), test=E(0.05), min_n=150)))
    out.append(("Sport x side cells (overs / unders)", "Over / under", cells_rule(lambda c: (c["sport"], c["side"]))))
    for s in ("nfl", "nba", "nhl"):
        for side in ("over", "under"):
            out.append((f"{roi4.SPORT_NAME[s]} {side}s, every one", "Over / under",
                        flat(lambda c, s=s, side=side: c["sport"] == s and c["side"] == side)))
    bands = [(0.10, 0.35), (0.35, 0.50), (0.50, 0.65), (0.65, 0.80), (0.80, 0.90), (0.90, 1.0)]
    for a, b in bands:
        out.append((f"Price {round(a * 100)}-{round(b * 100)}c, every sport", "Price band (favourite / longshot)",
                    flat(lambda c, a=a, b=b: a <= c["pr"] < b)))
    out.append(("Sport x price band cells that earned it", "Price band (favourite / longshot)",
                cells_rule(lambda c: (c["sport"], next((i for i, (a, b) in enumerate(bands) if a <= c["pr"] < b), None)))))
    for m_ in (0.02, 0.04, 0.06):
        out.append((f"Model recalibrated on past results, {round(m_ * 100)}+ points over", "Recalibrated model", calibrated(m_)))
    for m_ in (0.01, 0.02, 0.04):
        out.append((f"Model and market blended (logistic), {round(m_ * 100)}+ points over", "Model + market blend", blended(m_)))
    out.append(("Blend 2+ points over, quarter Kelly on the blend", "Model + market blend", blended(0.02, stake="kelly")))
    for sign, word in ((1, "rose"), (-1, "fell")):
        out.append((f"Price {word} 3c+ before lock (bought at the close)", "Market move", moved(sign)))
        out.append((f"Model 10+ over and price {word} 3c+", "Market move", moved(sign, test=E(0.10))))
    out.append(("Sport x move cells (rose / flat / fell) that earned it", "Market move",
                cells_rule(lambda c: None if c.get("p0") is None else
                           (c["sport"], "rose" if c["pr"] - c["p0"] >= 0.03 else "fell" if c["pr"] - c["p0"] <= -0.03 else "flat"))))
    for g in (0.03, 0.06):
        out.append((f"Other exchange {round(g * 100)}c+ dearer", "Exchanges disagree", disagree(g)))
    out.append(("Model 10+ over, 15+ games of history", "Model confidence",
                flat(lambda c: edge(c) >= 0.10 and (c.get("neff") or 0) >= 15)))
    out.append(("Model 10+ over, narrow range (high - low under 25 points)", "Model confidence",
                flat(lambda c: edge(c) >= 0.10 and c.get("hi") is not None and c.get("lo") is not None and c["hi"] - c["lo"] < 0.25)))
    out.append(("Model 10+ over, its low end above the price", "Model confidence",
                flat(lambda c: edge(c) >= 0.10 and c.get("lo") is not None and c["lo"] > c["pr"])))
    out.append(("Hot cells: sport x stat x side up 10%+ the last 7 days", "Hot streaks",
                cells_rule(lambda c: (c["sport"], c["stat"], c["side"]), min_n=60, min_days=2, recent=7, min_roi=0.10, lo_floor=-1)))
    out.append(("Fade the model: picks it rates 10+ points under the price", "Fade the model", flat(lambda c: edge(c) <= -0.10)))
    out.append(("Two-leg parlays of NFL model 10+ picks", "Parlays", parlays2(flat(nfl_edge))))
    out.append(("Two-leg parlays of every-sport model 10+ picks", "Parlays", parlays2(flat(E(0.10)))))
    out.append(("NFL model 10+ over, flat 1 unit", "Staking", flat(nfl_edge)))
    out.append(("NFL model 10+ over, quarter Kelly on the model's chance", "Staking", kelly_seg(nfl_edge)))
    out.append(("NFL model 10+ over, stake grows with the edge", "Staking", edge_prop(nfl_edge)))
    out.append(("NFL model 10+ over, stop once the day is up 4% (optimistic)", "Money management", stop_at_target(flat(nfl_edge))))
    out.append(("NFL model 10+ over, double the stake after a losing day", "Money management", double_after_loss(flat(nfl_edge))))
    out.append(("roi4.py rule, stop once the day is up 4% (optimistic)", "Money management", stop_at_target(roi4_rule)))
    return out


def botd_summary(test_from=TEST_FROM):
    doc = roi4.edge_report.load("botd.json") or {}
    out = []
    for slot, name in (("value", "Pick of the Day: Value Shot"), ("lock", "Pick of the Day: Safe Pick")):
        bets = []
        for d in doc.get("days") or []:
            p = d.get(slot)
            if d.get("date", "") >= test_from and p and p.get("res") in ("hit", "miss") and p.get("price"):
                pr = roi4.frac(p["price"])
                bets.append({"day": d["date"], "sport": p.get("sport"), "res": p["res"], "stake": 1.0, "price": pr, "key": d["date"],
                             "pnl": (1 - pr) / pr if p["res"] == "hit" else -1.0})
        out.append(summarize(name, "Featured picks", bets, "one a day, as posted"))
    return out


def study(cands, until, test_from=TEST_FROM, only=None):
    """Every method, walk-forward from test_from to the day before `until`. Returns rows, best return first."""
    graded = sorted((c for c in cands if c["res"] in ("hit", "miss") and c["day"] < until), key=lambda c: c["day"])
    by_day = {}
    for c in graded:
        by_day.setdefault(c["day"], []).append(c)
    days = sorted(d for d in by_day if d >= test_from)
    rows = []
    for name, family, m in methods():
        if only and only not in name:
            continue
        rows.append(summarize(name, family, run(m, graded, by_day, days)))
    rows += botd_summary(test_from)
    rows.sort(key=lambda r: (r["n"] < FEW, -(r["roi"] if r["roi"] is not None else -9)))   # too few bets to judge: last
    return {"from": test_from, "until": until, "days": len(days), "rows": rows}


def main():
    until = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(roi4.ET).date().isoformat()
    only = sys.argv[2] if len(sys.argv) > 2 else None
    res = study(roi4.all_candidates(roi4.load_docs()), until, only=only)
    print(f"walk-forward {res['from']} .. {res['until']} ({res['days']} days)")
    for r in res["rows"]:
        roi = "   -   " if r["roi"] is None else f"{r['roi']:+7.2%}"
        rng = "" if r["lo"] is None else f"[{r['lo']:+.1%}, {r['hi']:+.1%}]"
        sp = " ".join(f"{k}:{v[0]}/{v[1]:+.0%}" for k, v in r["by_sport"].items() if v[1] is not None)
        print(f"{roi} {rng:18s} n={r['n']:5d} d={r['days']:2d} 4%+={r['days_hit']:2d} dd={r['max_dd']:6.1f}u  {r['family'][:22]:22s} {r['name']}  | {sp}")
    with open("roi4_study_out.json", "w", encoding="utf-8") as f:
        json.dump(res, f)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Fit the game-context adjustment strengths (build.CTX) on the walk-forward backtest.

For every backtest case it records the inputs the adjustment needs (the player's
usual implied points and spread, this game's implied points and spread, and the
opponent's defense ratio known before that week), then grid-searches betaPts,
betaSpr and gamma per stat family to minimise log loss. Families are independent,
so each is fitted on its own cases. To guard against overfitting it also fits on
odd weeks and scores even weeks (and vice versa) against the no-adjustment baseline.

Run from the repo root (downloads the same nflverse files the build does):
    python tools/tune_context.py
Then paste the printed CTX into build.py AND the CTX in template.html.
"""
import itertools, math, os, sys, collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build as B  # noqa: E402


def load_cases():
    all_rows, seasons = [], []
    for y in B.CANDIDATE_SEASONS:
        rows = B.fetch_csv(B.STATS_URL.format(year=y), f"stats {y}")
        if rows:
            all_rows.extend(rows)
            seasons.append(y)
    sched = B.load_schedule(set(B.CANDIDATE_SEASONS))
    players = [p for p in B.build_players(all_rows, {}, {}, sched) if p["g"]]
    snapshot = B.build_def_timeline(all_rows, set(B.CANDIDATE_SEASONS))
    start = seasons[1]
    cases = []
    for pl in players:
        rows = pl["g"]
        for i, row in enumerate(rows):
            if row[0] < start or i < B.BT_MIN_PRIOR:
                continue
            prior = rows[:i]
            hist = B.hist_context(prior)
            spr, tot = row[19], row[18]
            pts = None if (spr is None or tot is None) else tot / 2.0 + spr / 2.0
            snap = snapshot(row[0], row[1])
            for sk in B.BT_STATS.get(pl["p"], []):
                vals = [B.stat_value(sk, r) for r in prior]
                if B.stat_kind(sk) == "yards" and B.median(vals[-10:]) < B.BT_MIN_YARDS_MEDIAN:
                    continue
                cases.append({"fam": B.stat_family(sk, pl["p"]), "vals": vals, "line": B.seed_line(vals),
                              "kind": B.stat_kind(sk), "hist": hist, "pts": pts, "spr": spr,
                              "dr": B.def_ratio(snap, row[2], pl["p"], sk), "actual": B.stat_value(sk, row),
                              "week": row[1], "season": row[0]})
    return cases


def score(cases, fam, bp, bs, gm):
    B.CTX["betaPts"][fam], B.CTX["betaSpr"][fam], B.CTX["gamma"][fam] = bp, bs, gm
    ll = n = 0
    for c in cases:
        ctx = B.context_scale(fam, c["hist"], c["pts"], c["spr"], c["dr"])
        mp = B.model_prob(c["vals"], c["line"], c["kind"], ctx["scale"])
        side, prob, _, _ = B.side_prob(mp)
        res = B.grade_result(c["actual"], c["line"], side)
        if res == "push":
            continue
        y = 1 if res == "hit" else 0
        ll += -(y * math.log(prob) + (1 - y) * math.log(1 - prob))
        n += 1
    return ll / n if n else float("inf")


GRID_PTS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
GRID_SPR = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
GRID_GAM = [0.0, 0.25, 0.5, 0.75, 1.0]


def fit(cases, fam, passes=2):
    """Coordinate descent over the three grids (the effects are close to independent)."""
    bp, bs, gm = 0.0, 0.0, 0.0
    best = score(cases, fam, bp, bs, gm)
    for _ in range(passes):
        for name, grid in (("gm", GRID_GAM), ("bp", GRID_PTS), ("bs", GRID_SPR)):
            for v in grid:
                cand = {"bp": bp, "bs": bs, "gm": gm}
                cand[name] = v
                s = score(cases, fam, cand["bp"], cand["bs"], cand["gm"])
                if s < best:
                    best, bp, bs, gm = s, cand["bp"], cand["bs"], cand["gm"]
    return best, bp, bs, gm


def main():
    cases = load_cases()
    by_fam = collections.defaultdict(list)
    for c in cases:
        by_fam[c["fam"]].append(c)
    print(f"{len(cases)} cases: " + ", ".join(f"{k}={len(v)}" for k, v in by_fam.items()))
    print("rows with Vegas context:", sum(1 for c in cases if c["pts"] is not None), "| with defense ratio:",
          sum(1 for c in cases if c["dr"] is not None))
    fitted = {}
    for fam, cs in sorted(by_fam.items()):
        base = score(cs, fam, 0, 0, 0)
        s, bp, bs, gm = fit(cs, fam)
        odd = [c for c in cs if c["week"] % 2 == 1]
        even = [c for c in cs if c["week"] % 2 == 0]
        _, obp, obs, ogm = fit(odd, fam)
        ev_base, ev_fit = score(even, fam, 0, 0, 0), score(even, fam, obp, obs, ogm)
        _, ebp, ebs, egm = fit(even, fam)
        od_base, od_fit = score(odd, fam, 0, 0, 0), score(odd, fam, ebp, ebs, egm)
        fitted[fam] = (bp, bs, gm)
        print(f"\n[{fam}] n={len(cs)}  logloss baseline {base:.5f} -> fitted {s:.5f}  "
              f"(betaPts={bp}, betaSpr={bs}, gamma={gm})")
        print(f"   fit on odd weeks ({obp},{obs},{ogm}) -> even weeks: {ev_base:.5f} -> {ev_fit:.5f}")
        print(f"   fit on even weeks ({ebp},{ebs},{egm}) -> odd weeks:  {od_base:.5f} -> {od_fit:.5f}")
    print("\nCTX = {")
    for key, idx in (("betaPts", 0), ("betaSpr", 1), ("gamma", 2)):
        print(f'    "{key}": {{' + ", ".join(f'"{f}": {fitted[f][idx]}' for f in ("pass", "rush", "rec")) + "},")
    print('    "clampLo": 0.6, "clampHi": 1.6}')


if __name__ == "__main__":
    main()

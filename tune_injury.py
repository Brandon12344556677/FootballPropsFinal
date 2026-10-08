#!/usr/bin/env python3
"""
Check and fit next man up (build.NMU_LAMBDA, build.NMU_EMP) on past seasons.

A case is a back or receiver whose team, this game, was missing a teammate of his group
(backs for rushing; backs, receivers and tight ends for receiving) who had taken 20%+ of
that group's carries or targets the game before: as close as box scores get to "ruled out
this week". For each, the model's chance at the site's seeded line is scored (log loss)
three ways, using only earlier games:
  - plain:  the game log as is
  - usage:  plus the snap-share usage adjustment (what the site did before next man up)
  - nmu:    the game log rebuilt as if the missing teammate had sat those games too
            (build.nmu_adds), for a grid of strengths; usage stays off, as on the site
both at the line seeded from the plain log and from the rebuilt one, and on odd and even
weeks separately (a strength fitted on one half should hold on the other).

Run from the repo root (downloads the same nflverse files the build does):
    python tune_injury.py
"""
import collections, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as B  # noqa: E402

STATS = {"rush": ("rush_yds", "rush_att"), "rec": ("rec", "rec_yds")}
GRID_LAM = (0.5, 0.75, 1.0, 1.25)
GRID_EMP = (0.0, 1.0, 2.0)
OUT_SHARE = 0.20


def logloss(mp, actual, line):
    side_p = mp["over"]
    if actual == line:
        return None
    y = 1.0 if actual > line else 0.0
    p = min(1 - 1e-6, max(1e-6, side_p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def main():
    all_rows, seasons = [], []
    for y in B.CANDIDATE_SEASONS:
        rows = B.fetch_csv(B.STATS_URL.format(year=y), f"stats {y}")
        if rows:
            all_rows.extend(rows)
            seasons.append(y)
    sched = B.load_schedule(set(B.CANDIDATE_SEASONS))
    players = [p for p in B.build_players(all_rows, {}, {}, sched) if p["g"]]
    B.SNAPS.update(B.load_snaps(seasons))
    pos_eff = B.position_eff(players)
    by_key = collections.defaultdict(list)
    for pl in players:
        for r in pl["g"]:
            by_key[B._gkey(r)].append((pl, r))
    start = seasons[1] if len(seasons) > 1 else seasons[0]

    # score[(config, line choice, fam, half)] = [sum, n]
    score = collections.defaultdict(lambda: [0.0, 0])
    n_cases = collections.Counter()
    examples = []
    for pl in players:
        rows = pl["g"]
        for n, row in enumerate(rows):
            if row[0] < start or n < B.BT_MIN_PRIOR:
                continue
            prev, key = rows[n - 1], B._gkey(row)
            now_ids = {q["id"] for q, _ in by_key[key]}
            prior = rows[:n]
            for fam, cfg in B.NMU.items():
                if pl["p"] not in cfg["pos"]:
                    continue
                vi = cfg["vol"]
                grp_prev = [(q, r) for q, r in by_key[B._gkey(prev)] if q["p"] in cfg["pos"]]
                tot = sum(r[vi] for _, r in grp_prev)
                if tot <= 0:
                    continue
                outs = [q for q, r in grp_prev if q["id"] != pl["id"] and q["id"] not in now_ids
                        and r[vi] / tot >= OUT_SHARE]
                if not outs:
                    continue
                acts = [q for q, _ in by_key[key] if q["p"] in cfg["pos"]]
                members = outs + acts
                out_ids = {o["id"] for o in outs}
                half = "odd" if row[1] % 2 else "even"
                hist = B.hist_context(prior)
                shares = B.usage_shares(pl["id"], prior)
                usage = B.usage_of(shares)
                gsh = B.game_shares(pl["id"], prior)
                rebuilt = {}
                for lam in GRID_LAM:
                    for w in GRID_EMP:
                        adds = B.nmu_adds(members, out_ids, pos_eff, before=(row[0], row[1]), lam=lam, w_emp=w)
                        a = adds.get(pl["id"], {})
                        rr = []
                        for r in prior:
                            d = a.get(B._gkey(r))
                            if d:
                                r = list(r)
                                for i, v in d.items():
                                    r[i] += v
                            rr.append(r)
                        rebuilt[(lam, w)] = rr
                n_cases[fam] += 1
                for sk in STATS[fam]:
                    kind = B.stat_kind(sk)
                    vals = [B.stat_value(sk, r) for r in prior]
                    vals_ref = [B.stat_value(sk, r) for r in rebuilt[(1.0, 1.0)]]
                    actual = B.stat_value(sk, row)
                    for lc, line in (("plain line", B.seed_line(vals)), ("rebuilt line", B.seed_line(vals_ref))):
                        mp = B.model_prob(vals, line, kind, 1.0, B.CAL.get(sk))
                        ctx = B.context_scale(fam, hist, None, None, None, usage)
                        per = B.game_per(ctx["scale"], usage, shares and shares[0], gsh, fam)
                        mpu = B.model_prob(vals, line, kind, ctx["scale"], B.CAL.get(sk), per)
                        configs = [("plain", mp), ("usage", mpu)]
                        for (lam, w), rr in rebuilt.items():
                            configs.append((f"nmu lam={lam} emp={w}",
                                            B.model_prob([B.stat_value(sk, r) for r in rr], line, kind, 1.0, B.CAL.get(sk))))
                        for name, m in configs:
                            if not m:
                                continue
                            ll = logloss(m, actual, line)
                            if ll is None:
                                continue
                            for h in (half, "all"):
                                s = score[(name, lc, fam, h)]
                                s[0] += ll
                                s[1] += 1
                    if sk in ("rush_yds", "rec_yds") and len(examples) < 12 and row[0] == seasons[-1]:
                        line = B.seed_line(vals)
                        examples.append(f"{pl['n']} {row[0]} wk{row[1]} {sk}: actual {actual}, line {line} | "
                                        f"over: plain {B.model_prob(vals, line, kind, 1.0)['over']:.2f}, "
                                        f"nmu {B.model_prob(vals_ref, line, kind, 1.0)['over']:.2f} | "
                                        f"out: {', '.join(o['n'] for o in outs)}")

    print(f"cases: {dict(n_cases)}")
    for fam in B.NMU:
        for lc in ("plain line", "rebuilt line"):
            print(f"\n[{fam} | {lc}]  mean log loss (lower is better): all / odd weeks / even weeks")
            names = sorted({k[0] for k in score if k[2] == fam and k[1] == lc},
                           key=lambda nm: score[(nm, lc, fam, "all")][0] / max(1, score[(nm, lc, fam, "all")][1]))
            for nm in names:
                cells = []
                for h in ("all", "odd", "even"):
                    s, c = score[(nm, lc, fam, h)]
                    cells.append(f"{s / c:.4f} (n={c})" if c else "-")
                print(f"  {nm:24s} " + "  ".join(cells))
    print("\nexamples (latest season):")
    for e in examples:
        print("  " + e)


if __name__ == "__main__":
    main()

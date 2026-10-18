#!/usr/bin/env python3
"""
Check and fit the trade hand-off (build.TRADE_LAMBDA) on past seasons.

A case is a quarterback, back, receiver or tight end playing for a team that, earlier the same
season, had a player of his group (build.TRADE_FAMS) who then played for another team: traded,
released and signed elsewhere, claimed. For each of the old team's games after the move (the rest
of that season), the model's chance at the site's seeded line is scored (log loss), using only
earlier games, with the game log as is (lam=0) and rebuilt as if the departed player had sat his
games with the team (build.nmu_adds, newly=False) for a grid of strengths; usage stays off for
the rebuilt logs, as on the site. Odd and even weeks separately, as in tune_injury.py.

Run from the repo root (downloads the same nflverse files the build does):
    python tune_trade.py
"""
import collections, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as B  # noqa: E402

STATS = {"pass": ("pass_yds", "pass_cmp", "pass_att"), "qbrush": ("rush_yds", "rush_att"),
         "rush": ("rush_yds", "rush_att"), "rec": ("rec", "rec_yds", "tgt")}
GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def logloss(mp, actual, line):
    if actual == line:
        return None
    y = 1.0 if actual > line else 0.0
    p = min(1 - 1e-6, max(1e-6, mp["over"]))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def main():
    all_rows, seasons = [], []
    for y in B.CANDIDATE_SEASONS:
        rows = B.fetch_csv(B.STATS_URL.format(year=y), f"stats {y}")
        if rows:
            all_rows.extend(rows)
            seasons.append(y)
    sched = B.load_schedule(set(B.CANDIDATE_SEASONS))
    gt = B.game_teams(sched)
    players = [p for p in B.build_players(all_rows, {}, {}, sched) if p["g"]]
    eff = B.position_eff(players, B.TRADE_FAMS)
    by_team_game = collections.defaultdict(list)       # (team, gkey) -> [(player, row)]
    for pl in players:
        for r in pl["g"]:
            t = gt.get(B._gkey(r))
            if t:
                by_team_game[(t, B._gkey(r))].append((pl, r))
    # moves: (player, old team, season, last week with the old team)
    moves = []
    for pl in players:
        for s in seasons:
            teams = [(r[1], gt.get(B._gkey(r))) for r in pl["g"] if r[0] == s and r[3] == "REG"]
            for (w0, a), (w1, b) in zip(teams, teams[1:]):
                if a and b and a != b:
                    moves.append((pl, a, s, w0))
    print(f"moves found: {len(moves)}  e.g. " + ", ".join(f"{m[0]['n']} ({m[1]} {m[2]} wk{m[3]})" for m in moves[:12]))

    score = collections.defaultdict(lambda: [0.0, 0])
    n_cases = collections.Counter()
    for mv, old, s, wk in moves:
        ghost = {"id": mv["id"], "n": mv["n"], "p": mv["p"], "g": [r for r in mv["g"] if gt.get(B._gkey(r)) == old]}
        keys = sorted({k for (t, k) in by_team_game if t == old and k[0] == s and k[1] > wk})
        for key in keys:
            here = [q for q, _ in by_team_game[(old, key)] if q["id"] != mv["id"]]
            rows_now = {q["id"]: r for q, r in by_team_game[(old, key)]}
            before = (key[0], key[1])
            adds = {lam: B.nmu_adds(here + [ghost], {ghost["id"]}, eff, before=before, lam=lam,
                                    fams=B.TRADE_FAMS, heirs_of=B.TRADE_HEIRS, newly=False) for lam in GRID if lam}
            for pl in here:
                prior = [r for r in pl["g"] if (r[0], r[1]) < before]
                if len(prior) < B.BT_MIN_PRIOR:
                    continue
                for fam, cfg in B.TRADE_FAMS.items():
                    if pl["p"] not in cfg["pos"] or mv["p"] not in B.TRADE_HEIRS[fam] \
                            or pl["p"] not in B.TRADE_HEIRS[fam][mv["p"]]:
                        continue
                    if not adds[1.0].get(pl["id"]):
                        continue        # no heir: nothing to score
                    half = "odd" if key[1] % 2 else "even"
                    n_cases[fam] += 1
                    for sk in STATS[fam]:
                        kind = B.stat_kind(sk)
                        vals = [B.stat_value(sk, r) for r in prior]
                        if kind == "yards" and B.median(vals[-10:]) < B.BT_MIN_YARDS_MEDIAN:
                            continue
                        line = B.seed_line(vals)
                        actual = B.stat_value(sk, rows_now[pl["id"]])
                        for lam in GRID:
                            a = adds[lam].get(pl["id"], {}) if lam else {}
                            rr = []
                            for r in prior:
                                d = a.get(B._gkey(r))
                                if d:
                                    r = list(r)
                                    for i, v in d.items():
                                        r[i] += v
                                rr.append(r)
                            m = B.model_prob([B.stat_value(sk, r) for r in rr], line, kind, 1.0, B.CAL.get(sk))
                            ll = m and logloss(m, actual, line)
                            if ll is None or ll is False:
                                continue
                            for h in (half, "all"):
                                for f in (fam, "every"):
                                    c = score[(lam, f, h)]
                                    c[0] += ll
                                    c[1] += 1
    print(f"cases (player-games with an heir): {dict(n_cases)}")
    for f in ("every",) + tuple(B.TRADE_FAMS):
        print(f"\n[{f}]  mean log loss (lower is better): all / odd weeks / even weeks")
        for lam in GRID:
            cells = []
            for h in ("all", "odd", "even"):
                sm, c = score[(lam, f, h)]
                cells.append(f"{sm / c:.4f} (n={c})" if c else "-")
            print(f"  lam={lam:<5} " + "  ".join(cells))


if __name__ == "__main__":
    main()

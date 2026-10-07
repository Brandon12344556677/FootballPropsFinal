"""TEMPORARY (kalshi-probe workflow, working branch only): after the builders run on a runner
(nothing is committed), what each sport's lists look like with Kalshi and the $25 depth rule."""
import json

for sp, fn, cents in (("NFL", "picks.json", 100), ("NBA", "nba_picks.json", 1), ("NHL", "nhl_picks.json", 1),
                      ("MLB", "mlb_picks.json", 1)):
    try:
        d = json.load(open(fn, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(sp, "no picks file", e)
        continue
    ps = [dict(zip(d["cols"], r)) for r in d["picks"]]
    pend = [p for p in ps if p.get("src") == "live" and p.get("res") is None and p.get("vn")]
    has = lambda p, t: t in (p.get("lists") or "")
    V = [p for p in pend if has(p, "V")]
    T = [p for p in pend if has(p, "T")]
    print(f"{sp}: priced {sum(p.get('price') is not None for p in pend)} | on Kalshi {sum(p.get('vn') == 'K' for p in pend)}, "
          f"Polymarket {sum(p.get('vn') == 'P' for p in pend)} | thin {sum(1 for p in pend if p.get('th'))} | "
          f"Top 25 {len(T)} ({sum(p.get('vn') == 'K' for p in T)} Kalshi) | Value {len(V)} ({sum(p.get('vn') == 'K' for p in V)} Kalshi)")
    for p in sorted(V, key=lambda p: -(p["prob"] - p["price"] / cents))[:8]:
        print(f"    V {p['player']} {p['stat']} {p['side']} {p['line']} | model {p['prob']} | pm {p.get('pp')} (${p.get('pd')}) "
              f"kalshi {p.get('kp')} (${p.get('kd')}) -> {p['price']} {p['vn']}")
try:
    s = json.load(open("slate.json", encoding="utf-8"))
    k = s.get("kalshi") or {}
    print("slate.json kalshi:", len(k), "deep sides", sum((v[2] or 0) >= 25 for v in k.values()) + sum((v[3] or 0) >= 25 for v in k.values()),
          list(k.items())[:3], "| bytes", len(json.dumps(k)))
except Exception as e:  # noqa: BLE001
    print("slate.json", e)

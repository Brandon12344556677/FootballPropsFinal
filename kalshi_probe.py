"""TEMPORARY (kalshi-probe workflow, working branch only): after the builders run on a runner
(nothing is committed), what got a Kalshi price and which exchange each pick is judged on."""
import json

for sp, fn in (("NFL", "picks.json"), ("NBA", "nba_picks.json"), ("NHL", "nhl_picks.json"), ("MLB", "mlb_picks.json")):
    try:
        d = json.load(open(fn, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(sp, "no picks file", e)
        continue
    ps = [dict(zip(d["cols"], r)) for r in d["picks"]]
    pend = [p for p in ps if p.get("src") == "live" and p.get("res") is None]
    has = lambda p, t: t in (p.get("lists") or "")
    print(f"{sp}: cols has pp/kp/vn {all(c in d['cols'] for c in ('pp', 'kp', 'vn'))} | pending {len(pend)}, "
          f"priced {sum(p.get('price') is not None for p in pend)}, with Kalshi {sum(p.get('kp') is not None for p in pend)}, "
          f"judged on Kalshi {sum(p.get('vn') == 'K' for p in pend)}, on Polymarket {sum(p.get('vn') == 'P' for p in pend)} | "
          f"Top 25 {sum(has(p, 'T') for p in pend)} ({sum(has(p, 'T') and p.get('vn') == 'K' for p in pend)} on Kalshi), "
          f"Value {sum(has(p, 'V') for p in pend)} ({sum(has(p, 'V') and p.get('vn') == 'K' for p in pend)} on Kalshi)")
    for p in [p for p in pend if p.get("kp") is not None][:6]:
        print("   ", p["player"], p["stat"], p["side"], p["line"], "| pm", p.get("pp"), "kalshi", p.get("kp"),
              "->", p.get("price"), p.get("vn"), p.get("lists") or "-", "| start", p.get("start") or p.get("date"))
    bad = [p for p in pend if p.get("price") is not None and p.get("vn") is None]
    if bad:
        print("   PRICED BUT NO VENUE:", len(bad), bad[0])
try:
    s = json.load(open("slate.json", encoding="utf-8"))
    k = s.get("kalshi") or {}
    print("slate.json kalshi:", len(k), list(k.items())[:6])
except Exception as e:  # noqa: BLE001
    print("slate.json", e)
try:
    t = json.load(open("today.json", encoding="utf-8"))
    print("today.json:", [(p["sport"], p["player"], p["price"], p.get("vn"), p.get("pp"), p.get("kp")) for p in t["picks"][:8]])
except Exception as e:  # noqa: BLE001
    print("today.json", e)

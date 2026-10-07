"""TEMPORARY (kalshi-probe workflow, working branch only): what Kalshi's public API lists for
NFL/NBA/NHL/MLB player props, and what one market looks like, so the builders can be
matched to it. Prints compact lines to the job log; capped at ~90 s; never fails the job."""
import json, re, sys, time, urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"
T0 = time.time()
PROP = re.compile(r"yard|touchdown|reception|pass|rush|point|rebound|assist|three|strikeout|hits?\b|home run|"
                  r"rbi|base|goal|shot|save|player|prop|outs", re.I)


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json", "User-Agent": "propstreaklab-probe"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    series = get("/series?category=Sports").get("series") or []
    print(f"SPORTS SERIES: {len(series)}", flush=True)
    keys = ("NFL", "NBA", "NHL", "MLB")
    hits = [s for s in series if any(k in ((s.get("ticker") or "") + " " + (s.get("title") or "")).upper() for k in keys)]
    print(f"MATCHING SERIES: {len(hits)}", flush=True)
    for s in hits:
        print("S", s.get("ticker"), "|", (s.get("title") or "")[:90], flush=True)
    props = [s for s in hits if PROP.search((s.get("title") or "") + " " + (s.get("ticker") or ""))]
    print(f"PROP-LIKE SERIES: {len(props)}", flush=True)
    shown = 0
    for s in props:
        if time.time() - T0 > 90:
            print("time cap reached", flush=True); break
        t = s.get("ticker")
        try:
            evs = get(f"/events?series_ticker={t}&status=open&with_nested_markets=true&limit=2").get("events") or []
        except Exception as e:
            print("E", t, "failed", e, flush=True); continue
        nm = sum(len(e.get("markets") or []) for e in evs)
        print("E", t, f"open events {len(evs)}, markets {nm}", "|", " / ".join((e.get("title") or "")[:60] for e in evs), flush=True)
        if evs and evs[0].get("markets") and shown < 8:
            e = evs[0]
            print("  EVENT", json.dumps({k: e.get(k) for k in ("event_ticker", "title", "sub_title", "strike_date")}), flush=True)
            for m in e["markets"][:3]:
                print("  MKT", json.dumps({k: m.get(k) for k in m if k not in ("rules_secondary",)}, default=str)[:1500], flush=True)
            shown += 1


try:
    main()
except Exception as e:
    print("probe error", e)
sys.exit(0)

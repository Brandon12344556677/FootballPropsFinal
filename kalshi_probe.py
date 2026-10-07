"""TEMPORARY (kalshi-probe workflow, working branch only): what Kalshi's public API lists for
NFL/NBA/NHL/MLB player props, and what one market looks like, so the builders can be
matched to it. Prints compact lines to the job log; never fails the job."""
import json, sys, time, urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json", "User-Agent": "propstreaklab-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def main():
    try:
        series = get("/series?category=Sports").get("series") or []
    except Exception as e:
        print("series: failed", e); return
    print(f"SPORTS SERIES: {len(series)}")
    keys = ("NFL", "NBA", "NHL", "MLB")
    hits = [s for s in series if any(k in (s.get("ticker") or "").upper() or k in (s.get("title") or "").upper() for k in keys)]
    for s in hits:
        print("S", s.get("ticker"), "|", s.get("title"), "|", s.get("frequency"), "|", ",".join(s.get("tags") or []))
    print(f"MATCHING SERIES: {len(hits)}")
    shown = 0
    for s in hits:
        t = s.get("ticker")
        try:
            evs = get(f"/events?series_ticker={t}&status=open&with_nested_markets=true&limit=3").get("events") or []
        except Exception as e:
            print("E", t, "failed", e); continue
        nm = sum(len(e.get("markets") or []) for e in evs)
        print("E", t, f"open events {len(evs)}, markets {nm}", "|", " / ".join((e.get("title") or "")[:60] for e in evs))
        if evs and evs[0].get("markets") and shown < 12:
            e = evs[0]
            print("  EVENT", json.dumps({k: e.get(k) for k in ("event_ticker", "title", "sub_title", "category", "strike_date")}))
            for m in e["markets"][:4]:
                print("  MKT", json.dumps({k: m.get(k) for k in m if k not in ("rules_secondary",)}, default=str)[:1500])
            shown += 1
        time.sleep(0.2)


try:
    main()
except Exception as e:
    print("probe error", e)
sys.exit(0)

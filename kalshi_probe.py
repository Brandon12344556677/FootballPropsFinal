"""TEMPORARY (kalshi-probe workflow, working branch only): what Kalshi's public API lists for
NFL/NBA/NHL/MLB per-game player props, and what one market looks like, so the builders can be
matched to it. Paced to stay under Kalshi's rate limit; capped; never fails the job."""
import json, sys, time, urllib.error, urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"
T0 = time.time()
CAP = 250
TARGETS = [
    "KXMLBKS", "KXMLBHIT", "KXMLBHRR", "KXMLBTB", "KXMLBHR", "KXMLBRBI", "KXMLBOUTS", "KXMLBSB",
    "KXMLBHA", "KXMLBERA", "KXMLBWA", "KXMLBRUNS", "KXMLBBB",
    "KXNFLRECYDS", "KXNFLRSHYDS", "KXNFLPASSYDS", "KXNFLREC", "KXNFLPASSTDS", "KXNFLANYTD", "KXNFLTD",
    "KXNHLPTS", "KXNHLAST", "KXNHLGOAL", "KXNHLANYGOAL", "KXNHLSAVE", "KXNHLSOG", "KXNHLSHOTS",
    "KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT", "KXNBAPRA", "KXNBASTL", "KXNBABLK",
]
FIELDS = ("ticker", "event_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title", "floor_strike",
          "strike_type", "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
          "last_price_dollars", "volume_fp", "open_interest_fp", "liquidity_dollars", "occurrence_datetime",
          "expected_expiration_time", "custom_strike", "status")


def get(path, tries=3):
    for i in range(tries):
        req = urllib.request.Request(API + path, headers={"Accept": "application/json",
                                                          "User-Agent": "propstreaklab-probe"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(4 * (i + 1)); continue
            raise


def main():
    series = get("/series?category=Sports").get("series") or []
    mine = sorted(s.get("ticker") or "" for s in series
                  if (s.get("ticker") or "").startswith(("KXMLB", "KXNFL", "KXNHL", "KXNBA")))
    print(f"SERIES {len(mine)}:", " ".join(mine), flush=True)
    have = set(mine)
    for t in TARGETS:
        if time.time() - T0 > CAP:
            print("time cap reached", flush=True); break
        if t not in have:
            print("X", t, "not a series", flush=True); continue
        time.sleep(1.2)
        try:
            ms = get(f"/markets?series_ticker={t}&status=open&limit=1000").get("markets") or []
        except Exception as e:
            print("X", t, "failed", e, flush=True); continue
        evs = sorted({m.get("event_ticker") for m in ms})
        print("M", t, f"open markets {len(ms)}, events {len(evs)}:", " ".join(evs[:12]), flush=True)
        for m in ms[:2]:
            print("  MKT", json.dumps({k: m.get(k) for k in FIELDS}, default=str), flush=True)
        if ms:
            print("  NAMES", " | ".join(sorted({m.get("yes_sub_title") or "" for m in ms})[:15]), flush=True)


try:
    main()
except Exception as e:
    print("probe error", e)
sys.exit(0)

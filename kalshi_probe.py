"""TEMPORARY (kalshi-probe workflow, working branch only): what order-book depth Polymarket US and
Polymarket's global book expose for NFL/MLB player props, so thin markets can be filtered."""
import json, time, urllib.error, urllib.request

PMUS = "https://gateway.polymarket.us"
UA = {"Accept": "application/json", "User-Agent": "propstreaklab-probe"}


def get(url):
    time.sleep(0.4)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:300].decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def show(tag, x, n=2500):
    print(tag, json.dumps(x, default=str)[:n], flush=True)


for slug in ("nfl-tb-dal-2026-10-08", "nfl-chi-gb-2026-10-11", "mlb-mil-sd-2026-10-07"):
    st, full = get(f"{PMUS}/v1/events/slug/{slug}")
    ev = (full or {}).get("event") if isinstance(full, dict) else None
    mk = [m for m in (ev or {}).get("markets") or [] if "player" in (m.get("sportsMarketType") or "")]
    print("PMUS", slug, st, "player markets", len(mk), flush=True)
    if not mk:
        continue
    m = mk[len(mk) // 2]
    show("  KEYS", sorted(m.keys()))
    show("  MARKET", {k: v for k, v in m.items() if k not in ("description", "rules")}, 3000)
    ms = m.get("slug")
    st, b = get(f"{PMUS}/v1/markets/{ms}/bbo")
    show(f"  BBO {st}", b)
    for path in (f"/v1/markets/{ms}/book", f"/v1/markets/{ms}/orderbook", f"/v1/markets/{ms}/depth",
                 f"/v1/markets/{ms}/order-book", f"/v1/book/{ms}", f"/v1/markets/slug/{ms}"):
        st, x = get(PMUS + path)
        show(f"  {path} {st}", x, 1200)

st, e2 = get("https://gamma-api.polymarket.com/events/slug/nfl-tb-dal-2026-10-09-player-props")
mk = (e2 or {}).get("markets") if isinstance(e2, dict) else None
print("GAMMA", st, len(mk or []), flush=True)
for m in (mk or [])[:2]:
    show("  GAMMA MARKET", {k: m.get(k) for k in ("question", "liquidityNum", "volumeNum", "volume24hr", "bestBid", "bestAsk",
                                                  "spread", "clobTokenIds", "orderMinSize", "outcomes", "outcomePrices")})
    try:
        tok = json.loads(m.get("clobTokenIds") or "[]")[0]
        st, bk = get(f"https://clob.polymarket.com/book?token_id={tok}")
        show(f"  CLOB BOOK {st}", bk, 1500)
    except Exception as e:  # noqa: BLE001
        print("  clob", e)

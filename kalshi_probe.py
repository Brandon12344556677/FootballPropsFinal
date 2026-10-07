"""TEMPORARY (kalshi-probe workflow, working branch only): what order-book depth Polymarket US,
Polymarket's global book and Kalshi expose for player props, so thin markets can be filtered."""
import json, time, urllib.error, urllib.request

KAL = "https://api.elections.kalshi.com/trade-api/v2"
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


# ---- Polymarket US ----
for tag in ("nfl", "mlb", "nhl"):
    st, d = get(f"{PMUS}/v1/events?tagSlug={tag}&active=true&closed=false&limit=5")
    evs = (d.get("events") if isinstance(d, dict) else None) or []
    print("PMUS", tag, st, "events", len(evs), flush=True)
    ev = next((e for e in evs if "player" in json.dumps(e).lower()), evs[0] if evs else None)
    if not ev:
        continue
    st, full = get(f"{PMUS}/v1/events/slug/{ev['slug']}")
    mk = [m for m in ((full or {}).get("event") or {}).get("markets") or [] if "player" in (m.get("sportsMarketType") or "")]
    print("PMUS", tag, "event", ev["slug"], "player markets", len(mk), flush=True)
    if not mk:
        continue
    m = mk[0]
    show("  PMUS MARKET KEYS", sorted(m.keys()))
    show("  PMUS MARKET", {k: v for k, v in m.items() if k not in ("description", "rules")})
    slug = m.get("slug")
    st, b = get(f"{PMUS}/v1/markets/{slug}/bbo")
    show(f"  PMUS BBO {st}", b)
    for path in (f"/v1/markets/{slug}/book", f"/v1/markets/{slug}/orderbook", f"/v1/markets/{slug}/depth",
                 f"/v1/markets/{slug}", f"/v1/orderbook/{slug}", f"/v1/markets/{slug}/trades"):
        st, x = get(PMUS + path)
        show(f"  PMUS {path} {st}", x, 1500)
    break

# ---- Kalshi ----
st, d = get(f"{KAL}/markets?series_ticker=KXMLBHIT&status=open&limit=3")
ms = (d.get("markets") if isinstance(d, dict) else None) or []
if not ms:
    st, d = get(f"{KAL}/markets?series_ticker=KXNFLRECYDS&status=open&limit=3")
    ms = (d.get("markets") if isinstance(d, dict) else None) or []
print("KALSHI markets", st, len(ms), flush=True)
if ms:
    m = ms[0]
    show("  KALSHI KEYS", sorted(m.keys()))
    show("  KALSHI MARKET", {k: v for k, v in m.items() if not k.startswith("rules")})
    t = m["ticker"]
    for q in ("", "?depth=10"):
        st, ob = get(f"{KAL}/markets/{t}/orderbook{q}")
        show(f"  KALSHI ORDERBOOK{q} {st}", ob, 2000)
    st, tr = get(f"{KAL}/markets/trades?ticker={t}&limit=5")
    show(f"  KALSHI TRADES {st}", tr, 1200)

# ---- Polymarket global (gamma + CLOB), one NFL player prop ----
st, evs = get("https://gamma-api.polymarket.com/events?tag_slug=nfl&closed=false&limit=50")
evs = evs if isinstance(evs, list) else []
ev = next((e for e in evs if "player-props" in (e.get("slug") or "")), None)
print("GAMMA", st, len(evs), ev and ev.get("slug"), flush=True)
if ev:
    st, e2 = get(f"https://gamma-api.polymarket.com/events/slug/{ev['slug']}")
    mk = (e2 or {}).get("markets") or []
    if mk:
        m = mk[0]
        show("  GAMMA MARKET", {k: m.get(k) for k in ("question", "liquidityNum", "volumeNum", "volume24hr", "bestBid", "bestAsk",
                                                      "spread", "clobTokenIds", "orderMinSize", "outcomes", "outcomePrices")})
        try:
            tok = json.loads(m.get("clobTokenIds") or "[]")[0]
            st, bk = get(f"https://clob.polymarket.com/book?token_id={tok}")
            show(f"  CLOB BOOK {st}", bk, 1500)
        except Exception as e:  # noqa: BLE001
            print("  clob", e)

#!/usr/bin/env python3
"""Team audience stats → team/stats.enc, the data behind the password page at /team/.

Pulls aggregate visitor counts from GoatCounter's API (totals only: pages, time-on-page ranges, referrers,
campaigns, countries, browsers, systems, screen sizes; GoatCounter keeps no IPs) and
encrypts them with the team password, so the file can sit in this public repo and the
page shows nothing until the right password is entered.

Needs two secrets, passed in by update.yml: GOATCOUNTER_TOKEN (an API key with only
"Read statistics") and TEAM_DASH_PASSWORD. With either missing it does nothing.

Encryption: `openssl enc -aes-256-cbc -pbkdf2 -md sha256 -iter 600000`, base64. The page
decrypts it with WebCrypto (PBKDF2 → 32-byte key + 16-byte IV after OpenSSL's
"Salted__" + 8-byte salt header). Changing the iteration count means changing
ITERATIONS in team/index.html too.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = "https://propstreaklive.goatcounter.com/api/v0"
OUT = os.path.join("team", "stats.enc")
ITERATIONS = 600000
TOP_N = 15
RANGES = {"d1": 1, "d7": 7, "d30": 30, "d90": 90}
TIME_RANGES = ["0-10s", "10-30s", "30s-1m", "1-3m", "3-10m", "10m+"]   # same labels as app.js
TIME_RE = re.compile(r"(?:^|/)time/([^/?#]+)$")
CLICK_RE = re.compile(r"(?:^|/)click/([a-z0-9-]+)/([a-z0-9-]+)$")   # app.js: click/<what>/<page>
VIEW_RE = re.compile(r"(?:^|/)view/(\d+)$")   # app.js: view/<n>, the visitor's n-th page load today
VISITOR_RE = re.compile(r"(?:^|/)visitor/(new|returning)$")   # app.js: once per visitor per day
DAYS_RE = re.compile(r"(?:^|/)days/(2|3-4|5-9|10\+)$")      # app.js: a returning visitor's days on the site, once a day
REF_RE = re.compile(r"(?:^|/)ref/([a-z0-9-]{2,24})/(new|visit)$")   # app.js: ref/<affiliate code>/<new|visit>
STAY_MARKS = ["0s", "10s", "20s", "1m", "3m", "10m", "30m"]   # same labels as app.js: ref/<code>/stay/<mark>
STAY_SECS = [5, 15, 40, 120, 390, 1200, 1800]   # a visit that left between two marks counts as the middle; 30m+ as 30m
STAY_RE = re.compile(r"(?:^|/)ref/([a-z0-9-]{2,24})/stay/([a-z0-9]+)$")
SPORT_RE = re.compile(r"^/(?:(nfl|nba|nhl|mlb)\.html|(?:games|players)/(nfl|nba|nhl|mlb)/|best/(nfl|nba|nhl|mlb)\.html)")
SPORTS = ("nfl", "nba", "nhl", "mlb")
HIT_PAGES = 4      # /stats/hits returns at most 100 paths a call; page through up to 400
SIZE_NAMES = {"phone": "Phone", "largephone": "Large phone", "tablet": "Tablet",
              "desktop": "Computer", "desktophd": "Large computer screen", "unknown": "(unknown)"}


def get(token, path, **q):
    time.sleep(0.3)  # the API allows 4 requests a second
    url = f"{BASE}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "User-Agent": "propstreaklab-team-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def hour(t):
    return t.strftime("%Y-%m-%dT%H:00:00Z")


def rows(stats, page):
    out = []
    for s in stats or []:
        name = s.get("name") or (SIZE_NAMES.get(s.get("id", "")) if page == "sizes" else None)
        if not name:
            name = s["id"] if s.get("id") and page != "toprefs" else "(unknown)"
        row = {"name": name, "n": int(s.get("count") or 0)}
        if s.get("ref_scheme"):
            row["kind"] = s["ref_scheme"]
        out.append(row)
    return out


def all_hits(token, q):
    """Every path's hits for the range, paging past the API's 100 a call with exclude_paths
    (the path IDs already seen, comma-separated), so low-count events aren't cut off."""
    hits, seen = [], []
    for _ in range(HIT_PAGES):
        extra = {"exclude_paths": ",".join(seen)} if seen else {}
        page = get(token, "/stats/hits", limit=100, **q, **extra)
        got = page.get("hits") or []
        hits += got
        seen += [str(h["path_id"]) for h in got if h.get("path_id") is not None]
        if not page.get("more") or not got:
            break
    return hits


def view_stats(events):
    """Page views and unique visitors from app.js's "view/<n>" events: GoatCounter counts each
    path once per visitor per day, so view/1 = that day's unique visitors and the sum over all n =
    page views (up to app.js's VIEW_CAP a visitor). {"views", "visitors", "daily": [{day, views, visitors}]}"""
    days = {}
    views = visitors = 0
    for h in events:
        m = VIEW_RE.search(h.get("path") or "")
        if not m:
            continue
        first = m.group(1) == "1"
        n = int(h.get("count") or 0)
        views += n
        visitors += n if first else 0
        for s in h.get("stats") or []:
            d = days.setdefault(s["day"], [0, 0])
            k = int(s.get("daily") or 0)
            d[0] += k
            d[1] += k if first else 0
    return {"views": views, "visitors": visitors,
            "daily": [{"day": d, "views": v[0], "visitors": v[1]} for d, v in sorted(days.items())]}


def daily_by(hits, key_of):
    """[{"day", <key>: n, ...}] summing each hit's daily stats under key_of(hit) (None skips it)."""
    days = {}
    for h in hits:
        k = key_of(h)
        if not k:
            continue
        for s in h.get("stats") or []:
            d = days.setdefault(s["day"], {})
            d[k] = d.get(k, 0) + int(s.get("daily") or 0)
    return [dict({"day": d}, **v) for d, v in sorted(days.items())]


def sport_of(h):
    """Which sport a page belongs to: its board, its game pages, player pages and best-props page."""
    if h.get("event"):
        return None
    m = SPORT_RE.match((h.get("path") or "").split("?")[0])
    return next((g for g in m.groups() if g), None) if m else None


def visitor_kind(h):
    m = VISITOR_RE.search(h.get("path") or "") if h.get("event") else None
    return m.group(1) if m else None


def days_kind(h):
    """"2", "3-4", "5-9" or "10+": how many different days a returning visitor has been on the site."""
    m = DAYS_RE.search(h.get("path") or "") if h.get("event") else None
    return m.group(1) if m else None


def click_kind(h):
    """"signup" for Polymarket/Kalshi sign-up clicks, "email" for the daily email sign-up."""
    m = CLICK_RE.search(h.get("path") or "") if h.get("event") else None
    if not m:
        return None
    return "email" if m.group(1) == "email-list" else "signup" if re.search(r"-signup(-|$)", m.group(1)) else None


def time_rows(events):
    """Time-on-page ranges from app.js's "time/<range>" events, in TIME_RANGES order."""
    counts = {}
    for h in events:
        m = TIME_RE.search(h.get("path") or "")
        if m and m.group(1) in TIME_RANGES:
            counts[m.group(1)] = counts.get(m.group(1), 0) + int(h.get("count") or 0)
    return [{"name": k, "n": counts.get(k, 0)} for k in TIME_RANGES] if counts else []


def click_rows(events):
    """Clicks on links that leave the site, from app.js's "click/<what>/<page>" events."""
    out = []
    for h in events:
        m = CLICK_RE.search(h.get("path") or "")
        if m:
            out.append({"what": m.group(1), "page": m.group(2), "n": int(h.get("count") or 0)})
    return sorted(out, key=lambda r: -r["n"])


def ref_rows(events):
    """Affiliate links (the dashboard's Affiliates tab) from app.js's "ref/<code>/new" and "ref/<code>/visit" events:
    [{"code", "new", "visit", "daily": [{"day", "new"}], "stay"?}], most new viewers first; "stay" (stay_summary,
    from "ref/<code>/stay/<mark>") is the time on site. "new" (a first-time
    browser that kept the site on screen 20 seconds) is what affiliates are paid for; the dashboard
    sums "daily" into pay periods and weeks."""
    out = {}
    for h in events:
        m = REF_RE.search(h.get("path") or "")
        if not m:
            continue
        r = out.setdefault(m.group(1), {"code": m.group(1), "new": 0, "visit": 0, "daily": {}})
        r[m.group(2)] += int(h.get("count") or 0)
        if m.group(2) == "new":
            for s in h.get("stats") or []:
                if int(s.get("daily") or 0):
                    r["daily"][s["day"]] = r["daily"].get(s["day"], 0) + int(s["daily"])
    stays = {}
    for h in events:
        m = STAY_RE.search(h.get("path") or "")
        if m and m.group(2) in STAY_MARKS:
            c = stays.setdefault(m.group(1), [0] * len(STAY_MARKS))
            c[STAY_MARKS.index(m.group(2))] += int(h.get("count") or 0)
    for code, c in stays.items():
        r = out.setdefault(code, {"code": code, "new": 0, "visit": 0, "daily": {}})
        r["stay"] = stay_summary(c)
    rows = [dict(r, daily=[{"day": d, "new": n} for d, n in sorted(r["daily"].items())]) for r in out.values()]
    return sorted(rows, key=lambda r: (-r["new"], -r["visit"], r["code"]))


def stay_summary(counts):
    """Time on site for one affiliate from how many of its visits reached each STAY_MARKS mark:
    {"n": timed visits, "avg": estimated average seconds on screen, "marks": counts}. A later mark
    can't be reached by more visits than an earlier one, so counts are capped going down."""
    capped = []
    for c in counts:
        capped.append(min(c, capped[-1]) if capped else c)
    n = capped[0]
    if not n:
        return {"n": 0, "avg": None, "marks": capped}
    left = [a - b for a, b in zip(capped, capped[1:] + [0])]   # visits that ended between this mark and the next
    return {"n": n, "avg": round(sum(k * s for k, s in zip(left, STAY_SECS)) / n), "marks": capped}


def site_tz(token):
    """The GoatCounter account's time zone ("US.America/New_York" → America/New_York). Its
    daily and hourly buckets use it, so "today" has to start at local midnight too."""
    try:
        name = get(token, "/me")["user"]["settings"]["timezone"].split(".", 1)[-1]
        return name, ZoneInfo(name)
    except Exception:
        return "America/New_York", ZoneInfo("America/New_York")


def range_stats(token, now, days, tz=dt.timezone.utc, ago=0):
    """`now` is naive UTC; the range starts at local midnight `days - 1` days ago. With ago > 0 the
    range is shifted back that many whole days and ends at local midnight ("yesterday": days=1, ago=1)."""
    today = now.replace(tzinfo=dt.timezone.utc).astimezone(tz).date() - dt.timedelta(days=ago)
    local_day = today - dt.timedelta(days=days - 1)
    start = dt.datetime.combine(local_day, dt.time(), tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None)
    end = (dt.datetime.combine(today + dt.timedelta(days=1), dt.time(), tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None)
           if ago else now + dt.timedelta(hours=1))
    q = {"start": hour(start), "end": hour(end)}
    total = get(token, "/stats/total", **q)          # rejects a "limit" parameter
    hits = all_hits(token, q)   # every path, including ?v= test URLs (merged on the page) and events
    events = [h for h in hits if h.get("event")]
    # GoatCounter's totals include events (app.js sends "time/<range>" and "click/<what>/<page>"),
    # so take them back out to keep "visits" meaning page visits.
    ev_day, ev_hour = {}, {}
    for h in events:
        for s in h.get("stats") or []:
            ev_day[s["day"]] = ev_day.get(s["day"], 0) + int(s.get("daily") or 0)
            ev_hour[s["day"]] = [a + int(b or 0) for a, b in
                                 zip(ev_hour.get(s["day"], [0] * 24), s.get("hourly") or [0] * 24)]
    # "end" is an hour past now, so late in the evening it reaches past local midnight and
    # GoatCounter adds tomorrow (empty); drop it, or it becomes "today" for the hours chart.
    daily = [d for d in total.get("stats") or [] if d.get("day", "") <= today.isoformat()]
    r = {
        "total": max(0, int(total.get("total") or 0) - int(total.get("total_events") or 0)),
        "daily": [{"day": d["day"], "n": max(0, int(d.get("daily") or 0) - ev_day.get(d["day"], 0))} for d in daily],
        "pages": [{"path": h["path"], "title": h.get("title", ""), "n": int(h.get("count") or 0)}
                  for h in hits if not h.get("event")][:100],
        "time": time_rows(events),
        "clicks": click_rows(events),
        "views": view_stats(events),
        "refs": ref_rows(events),
        # per day, for week-over-week and the by-sport chart
        "sports_daily": daily_by(hits, sport_of),
        "visitors_daily": daily_by(hits, visitor_kind),
        "loyal_daily": daily_by(hits, days_kind),
        "clicks_daily": daily_by(hits, click_kind),
    }
    if days == 1 and daily:
        last = daily[-1]
        r["hourly"] = [max(0, int(a or 0) - b) for a, b in
                       zip(last.get("hourly") or [], ev_hour.get(last["day"], [0] * 24))]
    elif days == 1:
        r["hourly"] = []
    if days == 30:   # each day's hours, for the best-time-to-post heatmap
        r["hours"] = [{"day": d["day"], "h": [max(0, int(a or 0) - b) for a, b in
                                             zip(d.get("hourly") or [0] * 24, ev_hour.get(d["day"], [0] * 24))]}
                      for d in daily]
    for page in ("toprefs", "campaigns", "locations", "browsers", "systems", "sizes"):
        n = 50 if page == "campaigns" else TOP_N   # every tracked link from the team page is a campaign
        r[page] = to_visits(rows(get(token, f"/stats/{page}", limit=n, **q).get("stats"), page), r["total"])
    return r


def to_visits(rows_, visits):
    """GoatCounter's breakdowns (referrers, tracked links, countries, devices) count app.js's events
    too: one visit can send view/<n>, visitor/new|returning and time/<range>, so a source can show
    more "visits" than the site had (Oct 15, 2026: Google 33 + Instagram 26 on a 42-visit day).
    When a breakdown adds up to more than the visits, scale each row down to its share of them."""
    total = sum(r["n"] for r in rows_)
    if not total or total <= visits:
        return rows_
    return [dict(r, n=round(r["n"] * visits / total)) for r in rows_]


SPIKE_X = 2.5      # a source or page counts as spiking at this many times its usual day...
SPIKE_MIN = 15     # ...with at least this many visits today


def spikes(snap):
    """Unusual traffic for the dashboard's alert line: the site, each referrer and each page
    today against its usual day over the last 7 (d7 / 7), plus yesterday against the 7 days
    before it, both ways. [{"kind": "up"|"down", "what", "today", "usual"}], biggest first."""
    out = []
    d1, d7, d30 = snap.get("d1") or {}, snap.get("d7") or {}, snap.get("d30") or {}
    daily = [d["n"] for d in d30.get("daily") or []]
    if len(daily) >= 9:
        y, base = daily[-2], daily[-9:-2]
        usual = sum(base) / 7
        if usual >= 5 and y >= SPIKE_X * usual:
            out.append({"kind": "up", "what": "Visits yesterday", "today": y, "usual": round(usual)})
        elif usual >= 20 and y <= usual / SPIKE_X:
            out.append({"kind": "down", "what": "Visits yesterday", "today": y, "usual": round(usual)})
    for key, label in (("toprefs", "Visits from {}"), ("pages", "Visits to {}")):
        week = {r.get("name") or r.get("path"): r["n"] for r in d7.get(key) or []}
        for r in d1.get(key) or []:
            name = r.get("name") or r.get("path")
            if name == "(unknown)":
                name = "no referrer (direct, apps)"
            usual = week.get(r.get("name") or r.get("path"), r["n"]) / 7
            if r["n"] >= SPIKE_MIN and r["n"] >= SPIKE_X * max(usual, 1):
                out.append({"kind": "up", "what": label.format(name), "today": r["n"], "usual": round(usual, 1)})
    return sorted(out, key=lambda s: -s["today"] / max(s["usual"], 1))[:6]


def email_stats(key):
    """Confirmed and waiting-to-confirm subscriber counts from Buttondown (the daily picks email),
    or None without a key or without its Subscribers: Read permission. Only the two numbers
    are kept, never an address."""
    if not key:
        return None
    out = {}
    for name, kind in (("subscribers", "regular"), ("pending", "unactivated")):
        req = urllib.request.Request(f"https://api.buttondown.com/v1/subscribers?type={kind}",
                                     headers={"Authorization": f"Token {key}", "User-Agent": "propstreaklab-team-stats"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out[name] = int(json.load(r).get("count") or 0)
        except Exception as e:   # 403: the key has no Subscribers permission; the dashboard explains how to add it
            print(f"  team stats: Buttondown {name} count unavailable ({type(e).__name__}: {getattr(e, 'code', e)})")
            return None
    return out


def openssl(args, data, password):
    env = dict(os.environ, TEAM_DASH_PASSWORD=password)
    return subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-md", "sha256",
                           "-iter", str(ITERATIONS), "-pass", "env:TEAM_DASH_PASSWORD",
                           "-base64", "-A", *args],
                          input=data, capture_output=True, env=env, check=True).stdout


def encrypt(plain, password):
    return openssl(["-salt"], plain.encode("utf-8"), password).decode("ascii")


def decrypt(blob, password):
    return openssl(["-d"], blob.encode("ascii"), password).decode("utf-8")


def unchanged(snap, password):
    """True when the file already holds these numbers, so a quiet pass makes no commit
    (the random salt would otherwise change the file every time)."""
    try:
        with open(OUT, encoding="ascii") as f:
            old = json.loads(decrypt(f.read().strip(), password))
    except Exception:
        return False
    strip = lambda s: {k: v for k, v in s.items() if k != "generated_at"}
    return strip(old) == strip(snap)


def main():
    token = os.environ.get("GOATCOUNTER_TOKEN", "").strip()
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    if not token or not password:
        print("team stats: GOATCOUNTER_TOKEN or TEAM_DASH_PASSWORD not set, skipping")
        return 0
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    tz_name, tz = site_tz(token)
    snap = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "site": "propstreaklab.com",
            "source": "GoatCounter", "tz": tz_name}
    for key, days in RANGES.items():
        snap[key] = range_stats(token, now, days, tz)
    snap["y1"] = range_stats(token, now, 1, tz, ago=1)   # yesterday, midnight to midnight
    snap["spikes"] = spikes(snap)
    snap["email"] = email_stats(os.environ.get("BUTTONDOWN_API_KEY", "").strip())
    if unchanged(snap, password):
        print(f"team stats: no new visits since the last pass ({snap['d90']['total']} in 90 days)")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(encrypt(json.dumps(snap, separators=(",", ":")), password) + "\n")
    print(f"team stats: wrote {OUT}, {snap['d30']['total']} visits in 30 days")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never print the token or password; the message is the request/IO error
        print(f"GoatCounter team stats failed ({type(e).__name__}: {e})")  # health.py's FAIL_RE shape
        sys.exit(1)

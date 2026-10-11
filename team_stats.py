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


def time_rows(events):
    """Time-on-page ranges from app.js's "time/<range>" events, in TIME_RANGES order."""
    counts = {}
    for h in events:
        m = TIME_RE.search(h.get("path") or "")
        if m and m.group(1) in TIME_RANGES:
            counts[m.group(1)] = counts.get(m.group(1), 0) + int(h.get("count") or 0)
    return [{"name": k, "n": counts.get(k, 0)} for k in TIME_RANGES] if counts else []


def site_tz(token):
    """The GoatCounter account's time zone ("US.America/New_York" → America/New_York). Its
    daily and hourly buckets use it, so "today" has to start at local midnight too."""
    try:
        name = get(token, "/me")["user"]["settings"]["timezone"].split(".", 1)[-1]
        return name, ZoneInfo(name)
    except Exception:
        return "America/New_York", ZoneInfo("America/New_York")


def range_stats(token, now, days, tz=dt.timezone.utc):
    """`now` is naive UTC; the range starts at local midnight `days - 1` days ago."""
    local_day = now.replace(tzinfo=dt.timezone.utc).astimezone(tz).date() - dt.timedelta(days=days - 1)
    start = dt.datetime.combine(local_day, dt.time(), tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None)
    q = {"start": hour(start), "end": hour(now + dt.timedelta(hours=1))}
    total = get(token, "/stats/total", **q)          # rejects a "limit" parameter
    hits = get(token, "/stats/hits", limit=60, **q)  # room for ?v= test URLs (merged on the page) and events
    hits = hits.get("hits") or []
    events = [h for h in hits if h.get("event")]
    # GoatCounter's totals include events (app.js sends one "time/<range>" event per page
    # view), so take them back out to keep "visits" meaning page visits.
    ev_day, ev_hour = {}, {}
    for h in events:
        for s in h.get("stats") or []:
            ev_day[s["day"]] = ev_day.get(s["day"], 0) + int(s.get("daily") or 0)
            ev_hour[s["day"]] = [a + int(b or 0) for a, b in
                                 zip(ev_hour.get(s["day"], [0] * 24), s.get("hourly") or [0] * 24)]
    daily = total.get("stats") or []
    r = {
        "total": max(0, int(total.get("total") or 0) - int(total.get("total_events") or 0)),
        "daily": [{"day": d["day"], "n": max(0, int(d.get("daily") or 0) - ev_day.get(d["day"], 0))} for d in daily],
        "pages": [{"path": h["path"], "title": h.get("title", ""), "n": int(h.get("count") or 0)}
                  for h in hits if not h.get("event")],
        "time": time_rows(events),
    }
    if days == 1 and daily:
        last = daily[-1]
        r["hourly"] = [max(0, int(a or 0) - b) for a, b in
                       zip(last.get("hourly") or [], ev_hour.get(last["day"], [0] * 24))]
    elif days == 1:
        r["hourly"] = []
    for page in ("toprefs", "campaigns", "locations", "browsers", "systems", "sizes"):
        r[page] = rows(get(token, f"/stats/{page}", limit=TOP_N, **q).get("stats"), page)
    return r


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

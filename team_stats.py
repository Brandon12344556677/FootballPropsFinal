#!/usr/bin/env python3
"""Team audience stats → team/stats.enc, the data behind the password page at /team/.

Pulls aggregate visitor counts from GoatCounter's API (totals only: pages, referrers,
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
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://propstreaklive.goatcounter.com/api/v0"
OUT = os.path.join("team", "stats.enc")
ITERATIONS = 600000
TOP_N = 15
RANGES = {"d1": 1, "d7": 7, "d30": 30, "d90": 90}
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


def range_stats(token, now, days):
    q = {"start": hour(dt.datetime.combine(now.date() - dt.timedelta(days=days - 1), dt.time())),
         "end": hour(now + dt.timedelta(hours=1))}
    total = get(token, "/stats/total", **q)          # rejects a "limit" parameter
    hits = get(token, "/stats/hits", limit=40, **q)  # room for ?v= test URLs, merged on the page
    daily = total.get("stats") or []
    r = {
        "total": int(total.get("total") or 0),
        "daily": [{"day": d["day"], "n": int(d.get("daily") or 0)} for d in daily],
        "pages": [{"path": h["path"], "title": h.get("title", ""), "n": int(h.get("count") or 0)}
                  for h in hits.get("hits") or [] if not h.get("event")],
    }
    if days == 1:
        r["hourly"] = (daily[-1].get("hourly") if daily else None) or []
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
    snap = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "site": "propstreaklab.com",
            "source": "GoatCounter"}
    for key, days in RANGES.items():
        snap[key] = range_stats(token, now, days)
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

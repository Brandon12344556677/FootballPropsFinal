"""
Prop Streak Lab — dashboard watchdog: is the password-protected team dashboard (/team/) working?

Runs every 30 minutes after watchdog.py (.github/workflows/watchdog.yml) and checks, from the
outside:

  - page:   /team/ loads, still has the pieces its script needs (lock form, section menu, date
            range, panels), its scripts (ads.js) load, and it opens in headless Chrome with no
            script errors
  - stats:  team/stats.enc is a valid encrypted file; with TEAM_DASH_PASSWORD it decrypts to the
            numbers the dashboard draws (every date range, with visits, pages, sources, clicks,
            views) and they were refreshed in the last STATS_STALE_H hours
  - edges:  team/edges.enc (the edge tracker) decrypts and was rebuilt in the last EDGES_STALE_H hours
  - feeds:  today.json still carries the fields the dashboard's panels read

A problem opens one "Team dashboard" GitHub issue, updated as it changes and closed when it's
fixed (watchdog.report); the dashboard's health panel doesn't need it, since the issue emails
the repo's watchers. Without the password it checks everything but the decrypted contents.

    python dashboard_check.py

Standard library only (openssl for decryption, as team_stats.py).
"""
import base64
import datetime
import json
import os
import re
import sys

import team_stats
import watchdog
from watchdog import SITE, fetch

TITLE = "Team dashboard: something needs a look"
MARK = "<!-- dashboard-check -->"
STATS_STALE_H = 18     # stats.enc only changes when the numbers do; overnight can be quiet for hours
EDGES_STALE_H = 6      # edges.enc is rebuilt every pass when graded picks change; a quiet night can go hours
RANGES = ("d1", "d7", "d30", "d90")
RANGE_KEYS = ("total", "daily", "pages", "toprefs", "clicks", "views")
PAGE_IDS = ("lockForm", "pw", "app", "views", "tabs", "chart", "sp", "em", "edRows", "posts", "health")
TODAY_KEYS = ("gen", "picks", "last", "promo", "flags", "fast", "live")
HINTS = {
    "page": "The dashboard page itself is broken: the last PR that changed team/index.html (or team/ads.js) is the usual cause.",
    "stats": "The dashboard's numbers aren't being refreshed or can't be read: check team_stats.py in the newest "
             "\"Update NFL data\" run, and the GOATCOUNTER_TOKEN and TEAM_DASH_PASSWORD secrets.",
    "edges": "The edge tracker isn't being rebuilt: check edge_report.py in the newest \"Update NFL data\" run.",
    "feeds": "today.json lost a field the dashboard reads: the last change to build_today.py is the usual cause.",
}


def openssl_blob_ok(text):
    """True when the file is OpenSSL's base64 "Salted__" format, which the dashboard decrypts."""
    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except ValueError:
        return False
    return raw[:8] == b"Salted__" and len(raw) > 32


def parse_time(s):
    return watchdog.parse_time(s)


def check_page():
    out = {}
    st, html = fetch(watchdog.bust("/team/"))
    if st != 200:
        return {"page: load": f"{SITE}/team/ didn't load ({st or html})."}
    missing = [i for i in PAGE_IDS if not re.search(rf'id="{i}"', html)]
    if missing:
        out["page: parts"] = f"{SITE}/team/ is missing parts its script uses: {', '.join(missing)}."
    for src in re.findall(r'<script src="([^"]+)"', html):
        if src.startswith("http"):
            continue
        st, _ = fetch(f"{SITE}/team/{src}")
        if st != 200:
            out[f"page: {src}"] = f"{SITE}/team/{src} returns {st}, so part of the dashboard won't work."
    exe = watchdog.browser()
    if exe:
        dom, errors = watchdog.render(exe, watchdog.bust("/team/"))
        if dom is None:
            out["page: render"] = f"{SITE}/team/ couldn't be opened in the browser ({errors})."
        elif errors:
            out["page: script"] = f"{SITE}/team/ has a script error: " + "; ".join(dict.fromkeys(errors))
        elif 'id="lockForm"' not in dom:
            out["page: render"] = f"{SITE}/team/ opened without its password screen."
    return out


def check_stats(now, password):
    out, notes = {}, []
    st, blob = fetch(watchdog.bust("/team/stats.enc"))
    if st != 200:
        return {"stats: file": f"{SITE}/team/stats.enc didn't load ({st or blob}): the dashboard shows \"No stats have been published yet\"."}, notes
    if not openssl_blob_ok(blob):
        return {"stats: file": f"{SITE}/team/stats.enc isn't a valid encrypted file, so the dashboard can't unlock."}, notes
    if not password:
        notes.append("TEAM_DASH_PASSWORD not set: stats.enc contents not checked")
        return out, notes
    try:
        snap = json.loads(team_stats.decrypt(blob.strip(), password))
    except Exception as e:
        return {"stats: decrypt": f"stats.enc doesn't open with the team password ({type(e).__name__}): the dashboard says the password is wrong."}, notes
    bad = [f"{r}.{k}" for r in RANGES for k in RANGE_KEYS if not isinstance(snap.get(r), dict) or k not in snap[r]]
    if bad:
        out["stats: contents"] = f"stats.enc is missing numbers the dashboard draws: {', '.join(bad[:8])}{'…' if len(bad) > 8 else ''}."
    gen = parse_time(snap.get("generated_at"))
    if gen is None:
        out["stats: fresh"] = "stats.enc has no update time."
    elif now - gen > datetime.timedelta(hours=STATS_STALE_H):
        hours = int((now - gen).total_seconds() // 3600)
        out["stats: fresh"] = f"The dashboard's numbers are {hours} hours old (last refreshed {gen:%Y-%m-%d %H:%M} UTC)."
    return out, notes


def check_edges(now, password):
    st, blob = fetch(watchdog.bust("/team/edges.enc"))
    if st != 200:
        return {"edges: file": f"{SITE}/team/edges.enc didn't load ({st or blob}): the edge tracker is empty."}
    if not openssl_blob_ok(blob):
        return {"edges: file": f"{SITE}/team/edges.enc isn't a valid encrypted file."}
    if not password:
        return {}
    try:
        rep = json.loads(team_stats.decrypt(blob.strip(), password))
    except Exception as e:
        return {"edges: decrypt": f"edges.enc doesn't open with the team password ({type(e).__name__})."}
    gen = parse_time(rep.get("generated_at"))
    if gen is None:
        return {"edges: fresh": "edges.enc has no update time."}
    if now - gen > datetime.timedelta(hours=EDGES_STALE_H):
        hours = int((now - gen).total_seconds() // 3600)
        return {"edges: fresh": f"The edge tracker was last rebuilt {hours} hours ago ({gen:%Y-%m-%d %H:%M} UTC)."}
    if not rep.get("strategies"):
        return {"edges: contents": "The edge tracker has no strategies in it."}
    return {}


def check_feeds():
    st, text = fetch(watchdog.bust("/today.json"))
    try:
        doc = json.loads(text) if st == 200 else None
    except ValueError:
        doc = None
    if doc is None:
        return {}          # watchdog.py already reports a missing or broken today.json
    missing = [k for k in TODAY_KEYS if k not in doc]
    return {"feeds: today": f"today.json is missing {', '.join(missing)}, which the dashboard's panels read."} if missing else {}


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    password = os.environ.get("TEAM_DASH_PASSWORD", "")
    problems = check_page()
    stats, notes = check_stats(now, password)
    problems.update(stats)
    problems.update(check_edges(now, password))
    problems.update(check_feeds())
    for msg in problems.values():
        print(f"::warning title=Team dashboard::{msg}")
    for n in notes:
        print(f"  note: {n}")
    print(f"  dashboard check: {len(problems)} problem(s)")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Team dashboard\n\n" + ("\n".join(f"- {m}" for m in problems.values()) or "Everything passes.") + "\n")
    token = os.environ.get("GITHUB_TOKEN")
    if token and watchdog.report(problems, now, token, title=TITLE, mark=MARK, hints=HINTS, who="The dashboard check"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

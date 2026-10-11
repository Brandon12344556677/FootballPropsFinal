"""
Prop Streak Lab — site watchdog: checks the LIVE site from the outside, every 30 minutes.

health.py runs inside the update job, so it can't notice the update job itself stopping,
GitHub Pages not deploying, a page that won't load, or a script error that leaves a board
blank. This runs as its own workflow (.github/workflows/watchdog.yml) and checks:

  - update:  the "Update NFL data" job is still being scheduled and isn't failing over and over
  - fresh:   the live site's data is recent (today.json "gen" under STALE_MIN minutes old)
  - pages:   every main page loads, isn't truncated, and has no unfilled __DATA__ placeholder
  - assets:  the app.js / app.css version each page asks for exists
  - json:    the live data files parse
  - render:  each page opened in headless Chrome: no script errors, and a board with picks
             in today.json actually draws its pick cards
  - health:  data-source problems health.py has already alerted on

Network checks retry before counting as a failure, so one slow response doesn't alert.

On a problem it opens one GitHub issue ("Site watchdog: ...") and updates it as the list
changes; when everything passes again it comments and closes it. GitHub emails the repo's
watchers for both. The team dashboard reads the same issue for its health panel.

    python watchdog.py           check and print; with GITHUB_TOKEN set, also open/update/close the issue
    WATCHDOG_BROWSER=<path>      the Chrome/Edge to render with (default: google-chrome on PATH)

Standard library only.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SITE = "https://propstreaklab.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "Brandon12344556677/FootballPropsFinal")
API = "https://api.github.com"
TITLE = "Site watchdog: something on the site needs a look"
MARK = "<!-- watchdog -->"         # identifies the watchdog's issue
STALE_MIN = 75                     # the site updates about every 10 min; GitHub sometimes delays a run ~20 min
NO_RUN_MIN = 90                    # no update run created for this long: the schedule has stalled
FAILS_IN_A_ROW = 2                 # completed update runs failing in a row before it's a problem
HEALTH_ALERT_AFTER = 18            # health.py's ALERT_AFTER: only problems it has already alerted on
TRIES, WAIT = 3, 20                # network retries, seconds apart

PAGES = ["/", "/nfl.html", "/nba.html", "/nhl.html", "/mlb.html", "/games/", "/best/", "/best/nfl.html",
         "/guides/", "/players/", "/methodology.html", "/team/"]
BOARDS = {"/": None, "/nfl.html": "nfl", "/nba.html": "nba", "/nhl.html": "nhl", "/mlb.html": "mlb"}   # rendered in Chrome
JSON_FILES = ["/today.json", "/botd.json", "/health.json", "/search.json", "/data.json", "/nba.json", "/nhl.json", "/mlb.json"]
PLACEHOLDER_RE = re.compile(r"__(?:NBA|NHL|MLB)?DATA__")
ASSET_RE = re.compile(r"""(?:src|href)="/?(app\.(?:js|css)\?v=[\w]+)\"""")
# Console lines from a page that mean a script broke or a file it needs is missing.
CONSOLE_RE = re.compile(r'CONSOLE[^\]]*\] "(.*)", source: (\S*)')
JS_ERROR_RE = re.compile(r"Uncaught|TypeError|ReferenceError|SyntaxError|RangeError|is not defined|Failed to load resource")
CONSOLE_IGNORE_RE = re.compile(r"Manifest|Banner not shown|favicon|goatcounter|gc\.zgo\.at|polymarket|kalshi", re.I)

HINTS = {
    "update": "Open the repo's Actions tab → \"Update NFL data\" and read the newest red run's log.",
    "fresh": "The update job ran but the live site didn't change: check the Actions tab for a failed "
             "\"pages build and deployment\" run, and Settings → Pages.",
    "pages": "A page is missing or broken on the live site. If it's a generated page (boards, games/, best/), "
             "the newest update run's log shows why; if it's hand-written, the last merged PR changed it.",
    "assets": "A page asks for an app.js/app.css version that doesn't exist: the last PR's version bump missed a file.",
    "json": "A data file on the site is cut off or invalid; the newest update run probably failed while writing it.",
    "render": "A page threw a script error in the browser (or drew no picks). The last merged PR is the usual cause; "
              "the message shows the file and line.",
    "health": "A data source has been failing for hours; health.json and the update run's \"Data health\" summary have details.",
}


def fetch(url, tries=TRIES, token=None, method="GET", body=None):
    """(status, text) — retried on network errors and 5xx; 4xx comes back at once."""
    headers = {"User-Agent": "prop-streak-lab-watchdog", "Cache-Control": "no-cache"}
    if token:
        headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, e.read().decode("utf-8", "replace")
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError) as e:
            err = str(getattr(e, "reason", e))
        if i + 1 < tries:
            time.sleep(WAIT)
    return None, err


def bust(path):
    return f"{SITE}{path}{'&' if '?' in path else '?'}wd={int(time.time())}"


def parse_time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def check_update(now, token):
    """The update workflow's recent runs: still scheduled, and not failing over and over."""
    st, text = fetch(f"{API}/repos/{REPO}/actions/workflows/update.yml/runs?per_page=10&branch=main", token=token)
    if st != 200:
        return {}   # can't see the runs (rate limit, API hiccup): the freshness check still covers a stall
    runs = json.loads(text).get("workflow_runs") or []
    out = {}
    newest = max((parse_time(r["created_at"]) for r in runs), default=None)
    if newest is None or now - newest > datetime.timedelta(minutes=NO_RUN_MIN):
        ago = "ever" if newest is None else f"{int((now - newest).total_seconds() // 60)} minutes"
        out["update: stalled"] = f"No \"Update NFL data\" run has started in {ago} (normally one every 20 minutes)."
    done = [r for r in runs if r.get("status") == "completed"]
    bad = 0
    for r in done:
        if r.get("conclusion") in ("failure", "timed_out", "startup_failure"):
            bad += 1
        else:
            break
    if bad >= FAILS_IN_A_ROW:
        out["update: failing"] = (f"The last {bad} \"Update NFL data\" runs failed. Newest: {done[0].get('html_url', '')}")
    return out


def check_site(now):
    """(problems, today) for the live pages, assets, data files and freshness."""
    out, pages = {}, {}
    for path in PAGES:
        st, text = fetch(bust(path))
        if st != 200:
            out[f"pages: {path}"] = f"{SITE}{path} didn't load ({st or text})."
            continue
        pages[path] = text
        if len(text) < 1500 or not text.rstrip().lower().endswith(("</html>", "</body>", "</script>")):
            out[f"pages: {path}"] = f"{SITE}{path} looks cut off ({len(text)} bytes, it doesn't end with a closing tag)."
        elif PLACEHOLDER_RE.search(text):
            out[f"pages: {path}"] = f"{SITE}{path} still has its {PLACEHOLDER_RE.search(text).group(0)} placeholder: the data was never filled in."
    for asset in sorted({a for text in pages.values() for a in ASSET_RE.findall(text)}):
        st, _ = fetch(f"{SITE}/{asset}")
        if st != 200:
            users = ", ".join(p for p, t in pages.items() if asset in t)
            out[f"assets: {asset}"] = f"/{asset} returns {st} but {users} load{'s' if ',' not in users else ''} it."
    today = None
    for path in JSON_FILES:
        st, text = fetch(bust(path))
        if st != 200:
            out[f"json: {path}"] = f"{SITE}{path} didn't load ({st or text})."
            continue
        try:
            doc = json.loads(text)
        except ValueError as e:
            out[f"json: {path}"] = f"{SITE}{path} isn't valid JSON ({str(e)[:80]})."
            continue
        if path == "/today.json":
            today = doc
    if today is not None:
        gen = parse_time(today.get("gen"))
        if gen is None:
            out["fresh: today"] = "today.json has no update time (gen)."
        elif now - gen > datetime.timedelta(minutes=STALE_MIN):
            mins = int((now - gen).total_seconds() // 60)
            out["fresh: today"] = (f"The live site's data is {mins // 60} h {mins % 60} min old "
                                   f"(last update {gen:%Y-%m-%d %H:%M} UTC); it normally updates every 10 minutes.")
    return out, today


def browser():
    for b in (os.environ.get("WATCHDOG_BROWSER"), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if b and (os.path.isfile(b) or shutil.which(b)):
            return b
    return None


def render(exe, url):
    """(dom, [site console errors]) after the page's scripts have run, or (None, reason)."""
    prof = tempfile.mkdtemp(prefix="wd-")
    try:
        r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--disable-extensions",
                            f"--user-data-dir={prof}", "--enable-logging=stderr", "--v=0",
                            "--virtual-time-budget=15000", "--dump-dom", url],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    errors = []
    for line in r.stderr.decode("utf-8", "replace").splitlines():
        m = CONSOLE_RE.search(line)
        if not m:
            continue
        msg, src = m.group(1), m.group(2)
        if (src.startswith(SITE) or not src) and JS_ERROR_RE.search(msg) and not CONSOLE_IGNORE_RE.search(msg + " " + src):
            errors.append(f"{msg[:200]} ({src.replace(SITE, '') or 'page'})")
    return r.stdout.decode("utf-8", "replace"), errors


def check_render(today):
    exe = browser()
    if not exe:
        print("  render: no Chrome found, skipped")
        return {}
    listed = {p.get("sport") for p in (today or {}).get("picks") or []}
    out = {}
    for path, sport in BOARDS.items():
        for attempt in range(2):                  # one retry: a slow price API can stall a render
            dom, errors = render(exe, bust(path))
            if dom is None:
                problem = f"{SITE}{path} couldn't be opened in the browser ({errors})."
            elif errors:
                problem = f"{SITE}{path} has a script error: " + "; ".join(dict.fromkeys(errors))
            elif (sport in listed or (sport is None and listed)) and 'class="pc-who"' not in dom:
                problem = f"{SITE}{path} drew no pick cards, though today.json lists {sport.upper() if sport else 'today'}'s picks."
            else:
                problem = None
            if problem is None:
                print(f"  render {path}: ok ({dom.count('class=\"pc-who\"')} pick cards)")
                break
        if problem:
            out[f"render: {path}"] = problem
    return out


def check_health():
    st, text = fetch(bust("/health.json"))
    try:
        problems = (json.loads(text).get("problems") or {}) if st == 200 else {}
    except ValueError:
        return {}
    return {f"health: {k}": f"{p.get('msg', k)} (for {p.get('runs')} update runs in a row)"
            for k, p in problems.items() if (p.get("runs") or 0) >= HEALTH_ALERT_AFTER}


def run_checks():
    now = datetime.datetime.now(datetime.timezone.utc)
    token = os.environ.get("GITHUB_TOKEN")
    problems = check_update(now, token)
    site, today = check_site(now)
    problems.update(site)
    problems.update(check_render(today))
    problems.update(check_health())
    return now, problems


def issue_body(problems, now):
    groups = {}
    for key, msg in sorted(problems.items()):
        groups.setdefault(key.split(":")[0], []).append(msg)
    lines = [MARK, f"<!-- keys:{json.dumps(sorted(problems))} -->",
             f"The site watchdog found {len(problems)} problem{'s' if len(problems) != 1 else ''} "
             f"on its check at {now:%Y-%m-%d %H:%M} UTC.", ""]
    for g, msgs in groups.items():
        lines += [f"**{g}**"] + [f"- {m}" for m in msgs] + [f"  _What to check:_ {HINTS.get(g, '')}", ""]
    lines.append("This issue updates itself while the problems last and closes once everything passes again.")
    return "\n".join(lines)


def report(problems, now, token):
    """Open, update or close the watchdog's issue. Returns True when this run opened a new one."""
    st, text = fetch(f"{API}/repos/{REPO}/issues?state=open&per_page=50", token=token)
    if st != 200:
        print(f"  issue: couldn't list issues ({st})")
        return False
    issue = next((i for i in json.loads(text) if MARK in (i.get("body") or "") and "pull_request" not in i), None)
    if problems and issue is None:
        st, text = fetch(f"{API}/repos/{REPO}/issues", token=token, method="POST",
                         body={"title": TITLE, "body": issue_body(problems, now)})
        print(f"  issue: opened ({st}) {json.loads(text).get('html_url', '') if st == 201 else text[:200]}")
        return st == 201
    if issue is None:
        return False
    url = f"{API}/repos/{REPO}/issues/{issue['number']}"
    if not problems:
        fetch(url + "/comments", token=token, method="POST",
              body={"body": f"All checks pass again as of {now:%Y-%m-%d %H:%M} UTC. Closing."})
        fetch(url, token=token, method="PATCH", body={"state": "closed", "state_reason": "completed"})
        print(f"  issue: #{issue['number']} closed")
        return False
    m = re.search(r"<!-- keys:(.*?) -->", issue.get("body") or "")
    old = set(json.loads(m.group(1))) if m else set()
    if old != set(problems):
        new = sorted(set(problems) - old)
        gone = sorted(old - set(problems))
        note = "\n".join([f"New: {problems[k]}" for k in new] + [f"Fixed: {k}" for k in gone])
        fetch(url, token=token, method="PATCH", body={"body": issue_body(problems, now)})
        fetch(url + "/comments", token=token, method="POST", body={"body": f"The problem list changed:\n\n{note}"})
        print(f"  issue: #{issue['number']} updated")
    return False


def main():
    now, problems = run_checks()
    for key, msg in sorted(problems.items()):
        print(f"::warning title=Watchdog::{msg}")
    print(f"  watchdog: {len(problems)} problem(s)")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Site watchdog\n\n" + ("\n".join(f"- {m}" for m in problems.values()) or "Everything passes.") + "\n")
    token = os.environ.get("GITHUB_TOKEN")
    if token and report(problems, now, token):
        return 1   # a red run on a NEW problem only, so GitHub's failure email fires once, not every 30 minutes
    return 0


if __name__ == "__main__":
    sys.exit(main())

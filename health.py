"""
Prop Streak Lab — health check after each build (every 20 min): is any data source quietly failing?

Every builder already prints "<source>: skipped (<error>)" when a download or step
fails, then carries on so the site still deploys. Nobody reads those lines, which is
how the NFL's ESPN fetch sat at HTTP 403 for weeks. This reads them, plus two things a
log can't show, and keeps a running record in health.json:

  - a source that failed this run: a "  source: skipped (...)" / "failed (...)" line,
    or 3+ per-item skips from one source ("    ESPN box 401..: skipped (...)"),
  - a builder that crashed (a Python traceback in its log),
  - a sport's data file that hasn't updated for 2+ days,
  - picks still ungraded 2-10 days after their game (older ones are left alone, so a
    postponed game ages out instead of alerting forever).

A problem has to show up on ALERT_AFTER runs in a row before it alerts, then it alerts
at most once a day while it lasts. `python health.py --gate` (the workflow's last step,
after the site is pushed) exits 1 when this run raised an alert: the run goes red and
GitHub emails the repo owner. Everything else about the deploy is untouched.

    python health.py [LOG_DIR]   check; reads LOG_DIR/*.log when given, writes health.json
    python health.py --gate      exit 1 if the last check raised an alert

Standard library only. The check itself never fails the build.
"""
import datetime
import glob
import json
import os
import re
import sys

STATE = "health.json"
ALERT_AFTER = 9              # consecutive runs before a problem alerts: ~3 hours at a run every 20 min
REALERT_HOURS = 24           # then at most once a day while it lasts
ITEM_MIN = 3                 # per-item skips from one source in one run that count as a problem
STALE_DAYS = 2               # a data file older than this is stale
UNGRADED_HOURS = (48, 240)   # picks ungraded this long after their game (2-10 days)

DATA = [  # sport, data file, picks file
    ("NFL", "data.json", "picks.json"),
    ("NBA", "nba.json", "nba_picks.json"),
    ("NHL", "nhl.json", "nhl_picks.json"),
    ("MLB", "mlb.json", "mlb_picks.json"),
]

SKIP_RE = re.compile(r"^(\s*)(.+?): (?:\S+ )?skipped \((.*?)\)")
FAIL_RE = re.compile(r"^(\s*)(.+?) failed \((.*?)\)")


def load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def from_logs(log_dir):
    """{key: message} for this run's failures, from the builders' own output."""
    out = {}
    for path in sorted(glob.glob(os.path.join(log_dir, "*.log"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        items = {}
        for i, line in enumerate(lines):
            if line.startswith("Traceback (most recent call last)"):
                last = next((l for l in reversed(lines[i:]) if l.strip()), "")
                out[f"{name}: crashed"] = f"{name}.py crashed: {last.strip()[:200]}"
                continue
            m = SKIP_RE.match(line) or FAIL_RE.match(line)
            if not m:
                continue
            indent, label, err = len(m.group(1)), m.group(2).strip(), m.group(3).strip()
            if indent >= 4:       # one game / week / event: only a problem when it repeats
                src = re.sub(r"\d+", "#", label)
                n, _ = items.get(src, (0, err))
                items[src] = (n + 1, err)
            else:
                out[f"{name}: {label}"] = f"{name}.py: {label} failed ({err[:160]})"
        for src, (n, err) in items.items():
            if n >= ITEM_MIN:
                out[f"{name}: {src}"] = f"{name}.py: {src} failed {n} times this run (e.g. {err[:160]})"
    return out


def parse_time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def from_data(now):
    """{key: message} for stale data files and picks stuck ungraded."""
    out = {}
    lo, hi = (datetime.timedelta(hours=h) for h in UNGRADED_HOURS)
    for sport, data_file, picks_file in DATA:
        db = load(data_file)
        if db is None:
            continue
        gen = str(db.get("gen") or "")[:10]
        try:
            age = (now.date() - datetime.date.fromisoformat(gen)).days
        except ValueError:
            age = None
        if age is not None and age >= STALE_DAYS:
            out[f"{sport}: stale"] = f"{sport}: {data_file} hasn't updated since {gen} ({age} days)"
        doc = load(picks_file)
        if not doc:
            continue
        cols = doc["cols"]
        stuck = 0
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or p.get("res") is not None:
                continue
            # NFL picks carry the ET game date only; count the game as over at the end of that day.
            t = parse_time(p["start"]) if p.get("start") else parse_time(f"{p.get('date')}T23:59:00-04:00")
            if t and lo <= now - t <= hi:
                stuck += 1
        if stuck:
            out[f"{sport}: ungraded"] = f"{sport}: {stuck} pick(s) still ungraded 2+ days after their game"
    return out


def check(log_dir):
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    found = from_data(now)
    if log_dir:
        found.update(from_logs(log_dir))
    old = (load(STATE, {}) or {}).get("problems") or {}
    problems, alerts = {}, []
    for key, msg in sorted(found.items()):
        p = dict(old.get(key) or {"first": stamp, "runs": 0, "alerted": None})
        p["runs"] += 1
        p["msg"] = msg
        last = parse_time(p["alerted"]) if p.get("alerted") else None
        if p["runs"] >= ALERT_AFTER and (last is None or now - last >= datetime.timedelta(hours=REALERT_HOURS)):
            p["alerted"] = stamp
            alerts.append(msg)
        problems[key] = p
    resolved = sorted(set(old) - set(problems))
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"problems": problems, "alert": alerts}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    for key, p in problems.items():
        # A warning annotation on the run page for every open problem, alerting or not.
        print(f"::warning title=Data source problem::{p['msg']} (seen {p['runs']} run(s) in a row since {p['first']})")
    for key in resolved:
        print(f"  health: resolved — {old[key].get('msg', key)}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Data health\n\n")
            f.write("\n".join(f"- {'**ALERT** ' if p['msg'] in alerts else ''}{p['msg']} "
                              f"— {p['runs']} run(s) in a row" for p in problems.values()) or "All sources OK.")
            f.write("\n")
    print(f"  health: {len(problems)} open problem(s), {len(alerts)} alert(s), {len(resolved)} resolved")


def gate():
    alerts = (load(STATE, {}) or {}).get("alert") or []
    if not alerts:
        print("Data health: no alerts.")
        return 0
    print("Data sources failing for several runs in a row (the site still deployed):")
    for msg in alerts:
        print(f"  - {msg}")
    print("Details: health.json in the repo, and the Data health summary on this run's page.")
    return 1


if __name__ == "__main__":
    if "--gate" in sys.argv:
        sys.exit(gate())
    try:
        check(next((a for a in sys.argv[1:] if not a.startswith("-")), None))
    except Exception as e:  # noqa: BLE001 — the health check never fails the build
        print(f"  health check skipped: {e}")
    sys.exit(0)

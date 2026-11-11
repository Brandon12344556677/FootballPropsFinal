#!/usr/bin/env python3
"""
Start a GitHub Actions workflow run and make sure it really started.

    python start_run.py update.yml '{"chain":"1"}'
    python start_run.py watchdog.yml

update.yml uses it to start the next update run (the chain that keeps the site updating every
~10 minutes) and a watchdog check. A workflow_dispatch request can be accepted (HTTP 204) and the
run still never start: on 2026-11-11 at 20:18 UTC, during a GitHub Actions incident, both runs
started that way ended in "startup_failure" with no steps, the chain stopped, and the backup
schedule fired nothing for an hour. So after each request this reads the workflow's runs: a new
run that is queued, waiting or running (or finished any way but startup_failure) means done; a
startup_failure, or no new run at all after CONFIRM_SEC, means ask again. Asking twice is safe:
both workflows' concurrency groups keep at most one run waiting.

Needs GH_TOKEN (the job's GITHUB_TOKEN, with actions: write) and GITHUB_REPOSITORY. Exit 0 once a
run is confirmed, 1 if every try failed. Standard library only.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}"
WAITS = (0, 20, 40, 60, 90)      # seconds before each try (~3.5 minutes of tries in all)
CONFIRM_SEC = 90                # how long to look for the new run after a request
POLL_SEC = 10
SLACK_SEC = 30                  # GitHub's created_at can be a little before our clock's "now"


def _req(url, token, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 method="POST" if data is not None else "GET",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "prop-streak-lab-updater"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:  # noqa: BLE001 — network trouble: a failed try
        return 0, None


def parse_time(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def verdict(runs, since):
    """'ok' (a new run is alive or ran), 'failed' (only startup failures), or 'none' (no new run yet)."""
    new = [r for r in runs or [] if (parse_time(r.get("created_at")) or since) >= since]
    if any(not (r.get("status") == "completed" and r.get("conclusion") == "startup_failure") for r in new):
        return "ok"
    return "failed" if new else "none"


def start(wf, inputs, repo, token, sleep=time.sleep, now=None):
    now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    base = API.format(repo=repo, wf=wf)
    for i, wait in enumerate(WAITS, 1):
        sleep(wait)
        since = now() - datetime.timedelta(seconds=SLACK_SEC)
        code, _ = _req(base + "/dispatches", token, {"ref": "main", "inputs": inputs})
        print(f"{wf}: try {i}: requested, HTTP {code}")
        if code != 204:
            continue
        waited, v = 0, "none"
        while waited < CONFIRM_SEC:
            sleep(POLL_SEC)
            waited += POLL_SEC
            code, d = _req(base + "/runs?event=workflow_dispatch&per_page=10", token)
            if code != 200:
                continue
            v = verdict((d or {}).get("workflow_runs"), since)
            if v == "ok":
                print(f"{wf}: the new run started")
                return True
            if v == "failed":
                print(f"{wf}: the new run failed to start (startup_failure): asking again")
                break
        if v == "none":
            print(f"{wf}: no new run after {CONFIRM_SEC}s: asking again")
    return False


def main(argv):
    wf = argv[1]
    inputs = json.loads(argv[2]) if len(argv) > 2 and argv[2] else {}
    ok = start(wf, inputs, os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    if not ok:
        print(f"::error::Couldn't start {wf}: every try failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

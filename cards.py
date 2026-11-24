"""Link-preview cards (og:image, 1200x630) for every shared link, drawn by og/draw.html in headless Chrome.

  og/site.png     players/, games/, best/, guides: what the site is and how big the record is
  og/<sport>.png  each sport page (nfl, nba, nhl, mlb, tennis): its lists over the last 30 days, losses shown as losses
  og/home.png     the home page: today's Pick of the Day (both picks), or the site card's numbers before it's made
  og/record.png   the Record page: every sport's Value units over 30 days
  p/<sport>/<key>.png  one per Value pick's share page (build_games.py queues them in .cards/queue.json)

Each card is drawn only when it's missing or its data changed (og/state.json keeps a fingerprint of what each
was drawn from), and the daily ones at most once a day, so the repo gets a few new images a day, not one per pass.
A share page's card is drawn once and never redrawn: its price and chance are "as of" the day it was drawn,
and the card says so. Standard library only; with no Chrome the step does nothing and the pages keep the logo.
Non-fatal: update_pass.sh runs it with a time limit after build_games.py.
"""
import datetime
import functools
import hashlib
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import base64

ROOT = os.path.dirname(os.path.abspath(__file__))
OG = "og"
STATE = os.path.join(OG, "state.json")
QUEUE = os.path.join(".cards", "queue.json")
PLAN = os.path.join(".cards", "plan.json")
ET = datetime.timezone(datetime.timedelta(hours=-5))   # date labels only; a DST hour either way never changes the day that matters
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    pass
SPORTS = ("nfl", "nba", "nhl", "mlb", "tennis")
NAME = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB", "tennis": "Tennis"}
DAILY = {"site", "home", "record"} | set(SPORTS)
MAX_PICKS = 40          # share-page cards drawn per run at most (the rest wait for the next pass)
FORMAT = "png8"         # og/draw.html's 256-colour PNG (about 4x smaller than the canvas PNG)


def fingerprint(data):
    return hashlib.sha1(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def day_label(d):
    return d.strftime("%a, %b ") + str(d.day)


def units(u):
    return ("+" if u >= 0 else "−") + f"{abs(u):.1f}u"


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------- what each card shows ----------

def list_row(sport_rec, tag):
    return next((l for l in sport_rec.get("lists") or [] if l.get("tag") == tag), None)


def sport_card(rec, sport):
    """Tiles from record.json: Value over 30 days in units, Top 25's hit rate against what the model said, picks graded."""
    s = next((x for x in (rec or {}).get("sports") or [] if x.get("sport") == sport), None)
    name = NAME[sport]
    title = f"Tennis match picks, priced and graded" if sport == "tennis" else f"Today's {name} player props, priced and graded"
    sub = "The model's chance next to the Polymarket and Kalshi price · updated every 10 minutes"
    tiles = []
    if s:
        v, t = list_row(s, "V"), list_row(s, "T")
        if v and (v.get("d30") or {}).get("n"):
            d = v["d30"]
            tiles.append(["Value · 30 days", units(d.get("units") or 0), "up" if (d.get("units") or 0) >= 0 else "dn",
                          f"{d['hit']} of {d['n']} hit"])
        if t and (t.get("d30") or {}).get("n"):
            d = t["d30"]
            hit = d["hit"] / d["n"]
            tiles.append(["Top 25 · 30 days", f"{round(hit * 100)}% hit", "up" if hit >= (d.get("said") or 0) - 0.02 else "dn",
                          f"model said {round((d.get('said') or 0) * 100)}%"])
        if s.get("graded"):
            since = s.get("since") or ""
            try:
                since = "since " + day_label(datetime.date.fromisoformat(since)).split(", ")[1]
            except ValueError:
                since = ""
            tiles.append(["Picks graded", f"{s['graded']:,}", "", since])
    if not tiles:
        tiles = [["Every prop", "Model vs price", "", "Polymarket and Kalshi"], ["Graded", "In public", "", "losses included"]]
    return {"sport": sport, "title": title, "sub": sub, "tiles": tiles}


def site_card(rec):
    tiles = []
    if rec and rec.get("graded"):
        tiles.append(["Picks graded", f"{rec['graded']:,}", "", "every one in public"])
    up = []
    for s in (rec or {}).get("sports") or []:
        if s.get("test"):
            continue
        v = list_row(s, "V")
        d = (v or {}).get("d30") or {}
        if d.get("n"):
            up.append((s.get("name") or s["sport"].upper(), d.get("units") or 0))
    if up:
        best = max(up, key=lambda r: r[1])
        tiles.append([f"{best[0]} Value · 30 days", units(best[1]), "up" if best[1] >= 0 else "dn", "best list this month"])
        down = [r for r in up if r[1] < 0]
        tiles.append(["Lists down · 30 days", str(len(down)), "dn" if down else "up",
                      ", ".join(r[0] for r in down) if down else "none right now"])
    if not tiles:
        tiles = [["Every prop", "Model vs price", "", ""], ["Record", "In public", "", "losses included"]]
    return {"tiles": tiles}


def record_card(rec):
    rows = []
    for s in (rec or {}).get("sports") or []:
        if s.get("test"):
            continue
        d = ((list_row(s, "V") or {}).get("d30")) or {}
        if d.get("n"):
            rows.append({"label": f"{s.get('name') or s['sport'].upper()} Value", "units": round(d.get("units") or 0, 1)})
    graded = (rec or {}).get("graded") or 0
    since = (rec or {}).get("since") or ""
    try:
        since = day_label(datetime.date.fromisoformat(since)).split(", ")[1]
    except ValueError:
        pass
    return {"title": f"{graded:,} lines graded since {since}" if graded else "Every pick, graded in public",
            "sub": "Value list units over the last 30 days, at the recorded price", "rows": rows}


def slim_pick(p):
    keep = ("player", "side", "line", "statText", "prob", "price", "vn", "l10")
    return {k: p.get(k) for k in keep if p.get(k) is not None}


def potd_card(botd, today):
    day = next((d for d in (botd or {}).get("days") or [] if d.get("date") == today.isoformat()), None)
    if not day or not (day.get("lock") or day.get("value")):
        return None
    slots = []
    for key, title in (("lock", "Safe Pick"), ("value", "Value Shot")):
        p = day.get(key)
        slots.append({"title": title, "sport": (p or {}).get("sport"), "pick": slim_pick(p) if p else None,
                      "empty": "No pick today" if day.get("closed") else "Posts later today"})
    return {"title": day_label(today), "slots": slots}


def plan(today, state, rec, botd, queue):
    """[(name, path, kind, data)]: every card that's missing or out of date."""
    want = [("site", os.path.join(OG, "site.png"), "site", site_card(rec)),
            ("record", os.path.join(OG, "record.png"), "record", record_card(rec))]
    want += [(s, os.path.join(OG, s + ".png"), "sport", sport_card(rec, s)) for s in SPORTS]
    home = potd_card(botd, today)
    want.append(("home", os.path.join(OG, "home.png"), "potd", home) if home else
                ("home", os.path.join(OG, "home.png"), "site", site_card(rec)))
    todo = []
    for name, path, kind, data in want:
        fp = fingerprint([kind, data])
        st = state.get(name) or {}
        if os.path.exists(path) and st.get("fp") == fp:
            continue
        # a daily card is redrawn at most once a day, except the home card when the day's pick arrives
        if os.path.exists(path) and st.get("day") == today.isoformat() and not (name == "home" and kind == "potd" and st.get("kind") != "potd"):
            continue
        todo.append((name, path, kind, data))
    n = 0
    for q in queue or []:
        if n >= MAX_PICKS:
            break
        sport, key = q.get("sport"), q.get("key")
        if sport not in SPORTS or not key or not re.fullmatch(r"[\w.\-]+", key):
            continue
        path = os.path.join("p", sport, key + ".png")
        if os.path.exists(path) or not os.path.isdir(os.path.join("p", sport)) or any(t[1] == path for t in todo):
            continue
        todo.append((f"p/{sport}/{key}", path, "pick",
                     {"sport": sport, "label": "Value pick", "pick": slim_pick(q["pick"]), "game": q.get("game") or "",
                      "asOf": q.get("asOf") or ""}))
        n += 1
    return todo


# ---------- drawing ----------

def browser():
    for b in (os.environ.get("CARDS_BROWSER"), os.environ.get("WATCHDOG_BROWSER"), "google-chrome", "google-chrome-stable",
              "chromium", "chromium-browser",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if b and (os.path.isfile(b) or shutil.which(b)):
            return b
    return None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def draw(todo):
    """{name: PNG bytes} for the cards that drew; og/draw.html does the drawing."""
    exe = browser()
    if not exe:
        print("  cards: no Chrome found (set CARDS_BROWSER): pages keep their current images")
        return {}
    os.makedirs(os.path.dirname(PLAN), exist_ok=True)
    with open(PLAN, "w", encoding="utf-8") as f:
        json.dump({"format": FORMAT, "cards": [{"name": n, "kind": k, "data": d} for n, _, k, d in todo]}, f)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/{OG}/draw.html?plan=/{PLAN.replace(os.sep, '/')}"
    prof = tempfile.mkdtemp(prefix="cards-")
    try:
        r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--disable-extensions",
                            "--hide-scrollbars", f"--user-data-dir={prof}", "--virtual-time-budget=20000", "--dump-dom", url],
                           capture_output=True, timeout=150)
        m = re.search(r'<pre id="out"[^>]*>(.*?)</pre>', r.stdout.decode("utf-8", "replace"), re.S)
        if not m or not m.group(1).strip():
            print("  cards: draw.html drew nothing")
            return {}
        out = json.loads(html.unescape(m.group(1)))
        if not out.get("ok"):
            print("  cards: draw.html failed: " + str(out.get("error"))[:300])
            return {}
        got = {}
        for name, v in out["cards"].items():
            if isinstance(v, str) and v.startswith("data:image/"):
                got[name] = base64.b64decode(v.split(",", 1)[1])
            else:
                print(f"  cards: {name} not drawn ({(v or {}).get('error') if isinstance(v, dict) else v})")
        return got
    finally:
        srv.shutdown()
        shutil.rmtree(prof, ignore_errors=True)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(ET).date()
    state = load(STATE, {}) or {}
    todo = plan(today, state, load("record.json"), load("botd.json"), load(QUEUE, []))
    if not todo:
        print("  cards: all up to date")
        return 0
    got = draw(todo)
    for name, path, kind, data in todo:
        png = got.get(name)
        if not png:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png)
        if not name.startswith("p/"):
            state[name] = {"fp": fingerprint([kind, data]), "day": today.isoformat(), "kind": kind}
    os.makedirs(OG, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"), sort_keys=True)
    sizes = [len(v) for v in got.values()]
    print(f"  cards: drew {len(got)} of {len(todo)}" + (f", {sum(sizes) // 1024} KB" if sizes else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"cards failed ({e})")    # health.py's FAIL_RE shape; never blocks the deploy
        sys.exit(0)

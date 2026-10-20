"""
Prop Streak Lab — the daily TikTok drafts: three short videos and one photo carousel.

Runs once a day in its own workflow (.github/workflows/tiktok.yml), after POST_HOUR_ET:

    python tiktok_post.py render   picks today's drafts, draws them, writes tiktok/<day>/
    python tiktok_post.py send     uploads them to the TikTok inbox as drafts

The workflow commits the carousel's JPEGs between the two steps: TikTok pulls photo posts
from a verified URL on our site (https://propstreaklab.com/tiktok/), while the videos are
uploaded straight from the runner and never committed.

Drafts, not posts: they land in the TikTok app's inbox, where the owner adds a sound,
checks the copy and taps Post. That works before TikTok reviews the app, and nothing about
betting goes out without a person reading it. TikTok allows about 5 drafts waiting in the
inbox per 24 hours, and this sends 4 a day, so post (or delete) each day's drafts.

The three videos follow the sports playing today, each from a different angle, for a
different kind of fan (ANGLES): the biggest model-vs-market gaps, hit streaks, or the season
record. plan_day() rotates through every (sport, angle) pair: one video per sport when three or
more sports play, a new angle before a repeated one, and otherwise whichever pair has gone
longest without a video. The carousel covers every sport playing: the Pick of the Day, one
value pick per sport, the top streak and the calibration chart.

Copy follows the Meta ad rules in team/ads.js: no "bet", "lock" or exchange names, 18+ on every post.

Secrets (repository secrets, passed in by tiktok.yml; without them `send` does nothing):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET   the TikTok for Developers app
  TIKTOK_REFRESH_TOKEN                      from tiktok_auth.py, run once (and again about yearly)
TikTok can hand back a new refresh token on each use; the newest one is kept encrypted (with the
client secret) as tiktok_token.enc on the team-data branch, through the GitHub API (GITHUB_TOKEN).

tiktok/posted.json remembers what was sent today, so a rerun only resends what failed, and the
last KEEP_DAYS of videos for the rotation; the team dashboard's Social tab shows it, with each
draft's caption to copy. POST_NOW=1 skips the hour and already-sent checks; `--dry-run` draws
everything and prints the uploads instead of sending them. Standard library only (plus Chrome
and ffmpeg on the runner); never fails the workflow.
"""
import base64
import datetime
import glob
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
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from zoneinfo import ZoneInfo

SITE = "https://propstreaklab.com"
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = "tiktok"
STATE = os.path.join(OUT_DIR, "posted.json")
POST_HOUR_ET = 11           # same as post_daily.py: after the overnight grading, before the early games
SLATE_END_HOUR_ET = 6       # "today's games" run until 6 AM ET the next morning (late West Coast games)
KEEP_DAYS = 14
VIDEOS = 3
ET = ZoneInfo("America/New_York")
UA = "PropStreakLab/1.0 (+https://propstreaklab.com)"
SPORTS = ("nfl", "nba", "nhl", "mlb")
NAME = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB"}
# Each angle is one kind of fan, drawn with that ads.js card: value hunters (gap), streak chasers
# (streak), and the "do your picks even hit?" crowd (record + calibration).
ANGLES = ("gap", "streak", "record")
MIN_STREAK = 5              # ads.js streak options
MIN_RECORD = 30             # ads.js record options: graded Top 25 picks before a sport's record is shown
PER_VIDEO = 3               # cards per video after the title card
SLIDE_SEC, FADE_SEC = 3.2, 0.35
API = "https://open.tiktokapis.com"
GH_API = "https://api.github.com"
TOKEN_BRANCH, TOKEN_PATH = "team-data", "tiktok_token.enc"
# Copy rules for every caption, checked by test_tiktok_post.py (player names aside: Drew Lock is fine)
BANNED = re.compile(r"\b(bet|bets|betting|lock|locks|polymarket|kalshi)\b", re.I)
TAGS = {"nfl": "#NFL #NFLProps", "nba": "#NBA #NBAProps", "nhl": "#NHL #NHLProps", "mlb": "#MLB #MLBProps"}
FOOT = "Free research, link in bio. Model chance, not a guarantee. 18+."


def load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def parse_utc(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def slate_end(now):
    """Today's games: everything starting before 6 AM ET tomorrow."""
    day = now.astimezone(ET).date() + datetime.timedelta(days=1)
    return datetime.datetime(day.year, day.month, day.day, SLATE_END_HOUR_ET, tzinfo=ET)


def on_today(start, now):
    t = parse_utc(start)
    return t is not None and now < t < slate_end(now)


# ---------- what to make ----------

def candidates(doc, now):
    """{sport: {angle: [indexes into today.json picks/streaks]}} for every sport playing today."""
    picks, streaks, out = doc.get("picks") or [], doc.get("streaks") or [], {}
    playing = {x.get("sport") for k in ("picks", "streaks", "live", "moves") for x in doc.get(k) or []
               if on_today(x.get("start"), now)}
    for s in SPORTS:
        if s not in playing:
            continue
        a = {}
        gap = [i for i, p in enumerate(picks) if p.get("sport") == s and p.get("kind") == "value" and p.get("price")
               and on_today(p.get("start"), now)]
        gap.sort(key=lambda i: -(picks[i]["prob"] - picks[i]["price"]))   # biggest gap first
        if gap:
            a["gap"] = gap[:PER_VIDEO]
        st = [i for i, x in enumerate(streaks) if x.get("sport") == s and (x.get("streak") or 0) >= MIN_STREAK
              and on_today(x.get("start"), now)]
        st.sort(key=lambda i: -streaks[i]["streak"])
        if st:
            a["streak"] = st[:PER_VIDEO]
        if has_record(doc, s):
            a["record"] = []
        if a:
            out[s] = a
    return out


def has_record(doc, s):
    return (((doc.get("record") or {}).get(s) or {}).get("T") or {}).get("n", 0) >= MIN_RECORD


def plan_day(doc, history, now, n=VIDEOS):
    """Today's n videos: [{sport, angle, items}]. history: [{date, sport, angle}] of videos sent before.

    A sport without a video yet today comes first (while one is left), then an angle not used yet
    today, then whichever (sport, angle) pair, sport and angle has gone longest without a video."""
    cands = candidates(doc, now)
    pairs = [(s, a) for s in cands for a in cands[s]]
    if not pairs:   # no games today: the season record of the sports graded most recently
        last = doc.get("last") or {}
        ss = sorted((s for s in SPORTS if has_record(doc, s)), key=lambda s: (last.get(s) or {}).get("day") or "", reverse=True)
        cands = {s: {"record": []} for s in ss}
        pairs = [(s, "record") for s in ss]
    today = now.astimezone(ET).date()

    def age(match):
        days = [(today - datetime.date.fromisoformat(h["date"])).days for h in history if match(h)]
        return min(days) if days else 999

    order = {p: i for i, p in enumerate(pairs)}   # last tie-break: sport order, or newest results first with no games
    chosen = []
    while pairs and len(chosen) < n:
        used_s, used_a = {s for s, _ in chosen}, {a for _, a in chosen}
        new_sport_left = any(s not in used_s for s, _ in pairs)
        best = min(pairs, key=lambda p: (new_sport_left and p[0] in used_s, p[1] in used_a,
                                         -age(lambda h: (h["sport"], h["angle"]) == p),
                                         -age(lambda h: h["sport"] == p[0]), -age(lambda h: h["angle"] == p[1]), order[p]))
        pairs.remove(best)
        chosen.append(best)
    return [{"sport": s, "angle": a, "items": cands[s][a]} for s, a in chosen]


def carousel_plan(doc, now, day):
    cands = candidates(doc, now)
    sports = [s for s in SPORTS if s in cands]
    gap = [cands[s]["gap"][0] for s in sports if "gap" in cands[s]][:4]
    streaks = doc.get("streaks") or []
    top = sorted((i for s in sports for i in cands[s].get("streak", [])), key=lambda i: -streaks[i]["streak"])[:1]
    return {"day": day, "potd": True, "gap": gap, "streak": top, "proof": True, "sports": sports}


# ---------- captions ----------

def pct(v):
    return round(v * 100)


def bet_text(p):
    return f"{p['player']} {p['side']} {p['line']} {p['statText']}"


def video_caption(doc, v):
    s, n = v["sport"], len(v["items"])
    if v["angle"] == "gap":
        p = doc["picks"][v["items"][0]]
        text = (f"{n} {NAME[s]} player prop{'s' if n > 1 else ''} where our model and the market disagree today 👀 "
                f"Biggest gap: {bet_text(p)}, model {pct(p['prob'])}% vs. market {pct(p['price'])}%.")
    elif v["angle"] == "streak":
        x = doc["streaks"][v["items"][0]]
        text = (f"{n} {NAME[s]} hit streak{'s' if n > 1 else ''} on the line today 🔥 Longest: {x['player']}, "
                f"{x['streak']} straight games {x['side']} {x['line']} {x['statText'].lower()}. Will it keep going?")
    else:
        t = doc["record"][s]["T"]
        text = (f"Do our {NAME[s]} picks actually hit? Top 25: {t['hit']:,} of {t['n']:,} this season ({pct(t['hit'] / t['n'])}%), "
                f"every pick recorded before the game and graded after ✅")
    return f"{text} {FOOT} {TAGS[s]} #PlayerProps #SportsAnalytics"


def carousel_caption(doc, botd, c):
    day = next((d for d in (botd or {}).get("days") or [] if d.get("date") == c["day"]), {})
    p = day.get("lock") or day.get("value")
    sports = ", ".join(NAME[s] for s in c["sports"]) or "today's"
    lead = f"Pick of the Day: {bet_text(p)} ({pct(p['prob'])}% model chance). " if p else ""
    tags = " ".join(TAGS[s] for s in c["sports"])
    return {"title": "Pick of the Day + today's best props" if p else "Today's best player props",
            "description": f"{lead}Swipe for today's best {sports} props →  {FOOT} {tags} #PlayerProps".replace("  ", " ")}


# ---------- drawing (headless Chrome on team/render.html) and the videos (ffmpeg) ----------

def browser():
    for b in (os.environ.get("TIKTOK_BROWSER"), os.environ.get("WATCHDOG_BROWSER"), "google-chrome", "google-chrome-stable",
              "chromium", "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if b and (os.path.isfile(b) or shutil.which(b)):
            return b
    return None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def draw(plan):
    """{"c": [data URLs], "v1": [...], ...} from team/render.html, served from this checkout."""
    exe = browser()
    if not exe:
        raise RuntimeError("no Chrome found (set TIKTOK_BROWSER)")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/team/render.html?plan=" + urllib.parse.quote(json.dumps(plan, separators=(",", ":")))
    prof = tempfile.mkdtemp(prefix="tt-")
    try:
        for attempt in range(2):
            r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--disable-extensions",
                                f"--user-data-dir={prof}", "--virtual-time-budget=30000", "--dump-dom", url],
                               capture_output=True, timeout=240)
            m = re.search(r'<pre id="out"[^>]*>(.*?)</pre>', r.stdout.decode("utf-8", "replace"), re.S)
            if m and m.group(1).strip():
                out = json.loads(html.unescape(m.group(1)))
                if not out.get("ok"):
                    raise RuntimeError("render.html: " + str(out.get("error"))[:300])
                return out["sets"]
        raise RuntimeError("render.html drew nothing")
    finally:
        srv.shutdown()
        shutil.rmtree(prof, ignore_errors=True)


def data_url_bytes(u):
    return base64.b64decode(u.split(",", 1)[1])


def ffmpeg_cmd(frames, out):
    """A slideshow: SLIDE_SEC per frame with crossfades, 1080x1920 H.264 at 30 fps, and a silent
    audio track (the owner adds a sound in the TikTok app; music can't be added through the API)."""
    n = len(frames)
    total = n * SLIDE_SEC - (n - 1) * FADE_SEC
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for f in frames:
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{SLIDE_SEC}", "-i", f]
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    fc = [f"[{i}:v]format=yuv420p,setsar=1[s{i}]" for i in range(n)]
    last = "s0"
    for i in range(1, n):
        fc.append(f"[{last}][s{i}]xfade=transition=fade:duration={FADE_SEC}:offset={i * (SLIDE_SEC - FADE_SEC):.2f}[x{i}]")
        last = f"x{i}"
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", f"{n}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out]
    return cmd


def prune(today):
    for d in glob.glob(os.path.join(OUT_DIR, "????-??-??")):
        try:
            if (today - datetime.date.fromisoformat(os.path.basename(d))).days > KEEP_DAYS:
                shutil.rmtree(d, ignore_errors=True)
        except ValueError:
            pass


# ---------- TikTok and GitHub APIs ----------

class TikTokError(Exception):
    pass


def http_json(url, body=None, headers=None, method=None, form=False, timeout=60):
    if form:
        data, ctype = urllib.parse.urlencode(body).encode(), "application/x-www-form-urlencoded"
    else:
        data, ctype = (json.dumps(body).encode() if body is not None else None), "application/json; charset=UTF-8"
    h = {"User-Agent": UA, "Content-Type": ctype}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:   # TikTok and GitHub both say why in the body
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            raise TikTokError(f"HTTP {e.code} from {url.split('?')[0]}")


def refresh(key, secret, token):
    """New access token (and maybe a new refresh token) from a refresh token."""
    j = http_json(f"{API}/v2/oauth/token/", {"client_key": key, "client_secret": secret,
                                            "grant_type": "refresh_token", "refresh_token": token}, form=True)
    if not j.get("access_token"):
        raise TikTokError(f"token refresh refused: {j.get('error')} {j.get('error_description', '')}".strip())
    return j


def api(path, body, access):
    j = http_json(API + path, body, headers={"Authorization": f"Bearer {access}"})
    err = j.get("error") or {}
    if isinstance(err, str):
        raise TikTokError(f"{err}: {j.get('error_description', '')}".strip())
    if err.get("code") not in (None, "ok"):
        raise TikTokError(f"{err.get('code')}: {err.get('message', '')}".strip())
    return j.get("data") or {}


def video_init_body(size):
    # One chunk: TikTok takes a whole file up to 64 MB in one piece; these are a few MB.
    return {"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}


def photo_init_body(urls, caption):
    return {"media_type": "PHOTO", "post_mode": "MEDIA_UPLOAD",
            "post_info": {"title": caption["title"][:90], "description": caption["description"][:4000]},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": urls,
                            "auto_add_music": True}}


def send_video(access, path):
    with open(path, "rb") as f:
        blob = f.read()
    d = api("/v2/post/publish/inbox/video/init/", video_init_body(len(blob)), access)
    req = urllib.request.Request(d["upload_url"], data=blob, method="PUT",
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(len(blob)),
                                          "Content-Range": f"bytes 0-{len(blob) - 1}/{len(blob)}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        r.read()
    return d["publish_id"]


def send_photos(access, urls, caption):
    return api("/v2/post/publish/content/init/", photo_init_body(urls, caption), access)["publish_id"]


def wait_for(access, publish_id, tries=24, pause=5):
    """Until TikTok has put the draft in the inbox (SEND_TO_USER_INBOX) or says why not."""
    for _ in range(tries):
        d = api("/v2/post/publish/status/fetch/", {"publish_id": publish_id}, access)
        st = d.get("status")
        if st in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return
        if st == "FAILED":
            raise TikTokError(f"TikTok couldn't process it: {d.get('fail_reason') or 'no reason given'}")
        time.sleep(pause)
    raise TikTokError("still processing after 2 minutes (it may still arrive)")


def wait_live(urls, local_paths, tries=40, pause=15):
    """GitHub Pages serves a pushed file a minute or two later: wait until every image is the new one."""
    for _ in range(tries):
        ok = True
        for u, p in zip(urls, local_paths):
            try:
                req = urllib.request.Request(u + "?t=" + str(int(time.time())), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    ok = ok and len(r.read()) == os.path.getsize(p)
            except (urllib.error.URLError, OSError):
                ok = False
        if ok:
            return True
        time.sleep(pause)
    return False


def stored_token(gh, repo, secret):
    """(refresh token, file sha) from team-data:tiktok_token.enc, or (None, None)."""
    import team_stats
    j = http_json(f"{GH_API}/repos/{repo}/contents/{TOKEN_PATH}?ref={TOKEN_BRANCH}",
                  headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
    if not j.get("content"):
        return None, None
    blob = base64.b64decode(j["content"]).decode("ascii").strip()
    return json.loads(team_stats.decrypt(blob, secret)).get("refresh_token"), j.get("sha")


def save_token(gh, repo, secret, token, sha):
    import team_stats
    blob = team_stats.encrypt(json.dumps({"refresh_token": token, "saved": now_iso()}), secret)
    body = {"message": "Update the TikTok token", "branch": TOKEN_BRANCH,
            "content": base64.b64encode(blob.encode("ascii")).decode("ascii")}
    if sha:
        body["sha"] = sha
    j = http_json(f"{GH_API}/repos/{repo}/contents/{TOKEN_PATH}", body, method="PUT",
                  headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
    if not (j.get("content") or {}).get("sha"):
        raise TikTokError(f"couldn't save the new TikTok token: {j.get('message', 'no reason given')}")


def access_token(env):
    """Access token from the newest refresh token we have; saves a rotated one. Raises TikTokError."""
    key, secret = env["TIKTOK_CLIENT_KEY"], env["TIKTOK_CLIENT_SECRET"]
    gh, repo = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_REPOSITORY", "")
    stored, sha = None, None
    if gh and repo:
        try:
            stored, sha = stored_token(gh, repo, secret)
        except Exception as e:
            print(f"  tiktok: couldn't read the saved token ({type(e).__name__}), using the secret")
    tried, last = [], None
    for tok in dict.fromkeys(t for t in (stored, env.get("TIKTOK_REFRESH_TOKEN", "").strip()) if t):
        try:
            j = refresh(key, secret, tok)
        except TikTokError as e:
            tried.append(tok)
            last = e
            continue
        new = j.get("refresh_token")
        if new and new != stored and gh and repo:
            try:
                save_token(gh, repo, secret, new, sha)
            except Exception as e:
                print(f"  tiktok: {e}")
        return j["access_token"]
    raise TikTokError(f"reconnect TikTok: {last}" if tried else "reconnect TikTok: no refresh token set")


# ---------- the two steps ----------

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def todays_state(today):
    st = load(STATE, {}) or {}
    if st.get("date") != today.isoformat():
        st = {"date": today.isoformat(), "drafts": {}, "history": st.get("history") or []}
    cut = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    st["history"] = [h for h in st.get("history") or [] if h.get("date", "") >= cut]
    return st


def save_state(st):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
        f.write("\n")


DRAFTS = [f"v{i + 1}" for i in range(VIDEOS)] + ["c"]


def missing(st):
    sent = {k for k, d in (st.get("drafts") or {}).items() if d.get("ok")}
    return [k for k in DRAFTS if k not in sent]


def wanted(st, force):
    """The drafts still to send today; forced after a full day, all of them again."""
    m = missing(st)
    if not m and force:
        st["drafts"] = {}
        return list(DRAFTS)
    return m


def gate(et, st, force, what):
    if force:
        return True
    if et.hour < POST_HOUR_ET:
        print(f"  tiktok {what}: waits until {POST_HOUR_ET}:00 ET")
        return False
    if not missing(st):
        print(f"  tiktok {what}: today's drafts are already in the inbox")
        return False
    return True


def render(now, force):
    et = now.astimezone(ET)
    today = et.date()
    st = todays_state(today)
    if not gate(et, st, force, "render"):
        return
    doc, botd = load("today.json", {}) or {}, load("botd.json", {}) or {}
    need = wanted(st, force)
    vkeys = [k for k in need if k != "c"]
    videos = plan_day(doc, st["history"], now, len(vkeys))   # history includes the videos already sent today
    plan = {"videos": videos}
    if "c" in need:
        plan["carousel"] = carousel_plan(doc, now, today.isoformat())
    sets = draw(plan)

    day_dir = os.path.join(OUT_DIR, today.isoformat())
    os.makedirs(day_dir, exist_ok=True)
    made = {}
    if "c" in need and sets.get("c"):
        for old in glob.glob(os.path.join(day_dir, "c*.jpg")):
            os.remove(old)
        files = []
        for i, u in enumerate(sets["c"]):
            p = os.path.join(day_dir, f"c{i + 1}.jpg")
            with open(p, "wb") as f:
                f.write(data_url_bytes(u))
            files.append(p)
        made["c"] = {"files": files, "caption": carousel_caption(doc, botd, plan["carousel"])}
    has_ffmpeg = bool(shutil.which("ffmpeg"))
    for i, (k, v) in enumerate(zip(vkeys, videos)):
        frames = sets.get(f"v{i + 1}") or []
        if not frames:
            continue
        cap = video_caption(doc, v)
        entry = {"sport": v["sport"], "angle": v["angle"], "caption": cap, "file": os.path.join(day_dir, f"{k}.mp4")}
        if not has_ffmpeg:
            print(f"  tiktok render: no ffmpeg, so no {k} video ({NAME[v['sport']]} {v['angle']})")
            continue
        tmp = tempfile.mkdtemp(prefix="ttf-")
        try:
            paths = []
            for j, u in enumerate(frames):
                p = os.path.join(tmp, f"{j}.png")
                with open(p, "wb") as f:
                    f.write(data_url_bytes(u))
                paths.append(p)
            subprocess.run(ffmpeg_cmd(paths, entry["file"]), check=True, capture_output=True, timeout=300)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        made[k] = entry
    with open(os.path.join(day_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(made, f, indent=1, ensure_ascii=False)
    prune(today)
    what = [f"{k} ({NAME[d['sport']]} {d['angle']})" if k != "c" else "carousel" for k, d in made.items()]
    print(f"  tiktok render: {', '.join(what) or 'nothing to draw'}")


def send(now, force, dry):
    et = now.astimezone(ET)
    today = et.date()
    st = todays_state(today)
    env = {k: os.environ.get(k, "") for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN",
                                               "GITHUB_TOKEN", "GITHUB_REPOSITORY")}
    if not dry and not (env["TIKTOK_CLIENT_KEY"] and env["TIKTOK_CLIENT_SECRET"]):
        print("  tiktok send: no TikTok secrets set — skipped")
        return
    if not gate(et, st, force, "send"):
        return
    wanted(st, force)
    made = load(os.path.join(OUT_DIR, today.isoformat(), "plan.json"), {}) or {}
    if not made:
        print("  tiktok send: nothing drawn today (run render first)")
        return
    urls = []
    if "c" in made:
        urls = [f"{SITE}/{p.replace(os.sep, '/')}" for p in made["c"]["files"]]
    if dry:
        for k, d in made.items():
            body = photo_init_body(urls, d["caption"]) if k == "c" else video_init_body(os.path.getsize(d["file"]) if os.path.exists(d["file"]) else 0)
            print(f"----- {k} -----\n{json.dumps(body, indent=1, ensure_ascii=False)}\ncaption: {d['caption']}")
        return

    try:
        access = access_token(env)
        st.pop("error", None)
        st["reconnect"] = False
    except TikTokError as e:
        st.update(error=str(e), reconnect=str(e).startswith("reconnect"), at=now_iso())
        save_state(st)
        print(f"  tiktok send: {e}")
        return
    for k, d in made.items():
        if k in st["drafts"] and st["drafts"][k].get("ok"):
            continue
        rec = {kk: d[kk] for kk in ("sport", "angle", "caption") if kk in d}
        try:
            if k == "c":
                if not wait_live(urls, d["files"]):
                    raise TikTokError("the carousel images never showed up on the site")
                pid = send_photos(access, urls, d["caption"])
            else:
                pid = send_video(access, d["file"])
            wait_for(access, pid)
            rec.update(ok=True, id=pid)
            if k != "c":
                st["history"].append({"date": today.isoformat(), "sport": d["sport"], "angle": d["angle"]})
        except Exception as e:
            rec.update(ok=False, error=str(e)[:300])
            print(f"  tiktok send: {k} failed ({e})")
        st["drafts"][k] = rec
    st["at"] = now_iso()
    save_state(st)
    sent = [k for k, d in st["drafts"].items() if d.get("ok")]
    print(f"  tiktok send: {len(sent)} of {VIDEOS + 1} drafts in the inbox ({', '.join(sent) or 'none'})")


def main(argv):
    step = argv[1] if len(argv) > 1 else ""
    dry = "--dry-run" in argv
    force = dry or os.environ.get("POST_NOW", "").strip() in ("1", "true", "yes")
    now = datetime.datetime.now(datetime.timezone.utc)
    if step == "render":
        render(now, force)
    elif step == "send":
        send(now, force, dry)
    else:
        print("usage: python tiktok_post.py render|send [--dry-run]")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as e:
        print(f"  tiktok skipped: {type(e).__name__}: {e}")
    sys.exit(0)

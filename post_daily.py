"""
Prop Streak Lab — once-a-day post of the picks to Discord and/or Telegram.

Runs in the hourly workflow after build_today.py. The first run at or after
POST_HOUR_ET (Eastern) each day posts:

  - yesterday's Value spots results per sport (graded, wins and losses), and
  - today's best value from today.json, each linking straight to its prop,
  - the referral code.

Channels come from repository secrets; a channel whose secret is unset is skipped,
and with none set the script does nothing:

  DISCORD_WEBHOOK_URL                  Discord: Server settings → Integrations → Webhooks
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  Telegram: a bot from @BotFather, added to the channel

posted.json remembers the last day posted so the hourly runs post once. POST_NOW=1
(the workflow's "post" input) posts right away, for testing. `--dry-run` prints both
messages and posts nothing. Standard library only; never fails the deploy.
"""
import datetime
import html
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

SITE = "https://propstreaklab.com"
REFERRAL = "https://polymarket.us/join/propstreaklab"
REFERRAL_KALSHI = "https://kalshi.com/sign-up/?referral=4373e9f9-0304-498c-8ca7-fccd3714b808&m=true&utm_source=mobile_app&utm_medium=share&utm_campaign=referral&utm_content=share_button&utm_term=referrals_pill"
STATE = "posted.json"
POST_HOUR_ET = 11           # late morning: after the overnight grading, before the early games
MAX_PICKS = 5
ET = ZoneInfo("America/New_York")
UA = "PropStreakLab/1.0 (+https://propstreaklab.com)"
SPORT = {"nfl": "🏈 NFL", "nba": "🏀 NBA", "nhl": "🏒 NHL", "mlb": "⚾ MLB"}
PICK_FILES = {"nfl": "picks.json", "nba": "nba_picks.json", "nhl": "nhl_picks.json", "mlb": "mlb_picks.json"}


def load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def slug(s):
    import re, unicodedata
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def pick_link(p):
    """Same format as PS.hashFor() in app.js, so the link opens that exact prop."""
    from urllib.parse import quote
    return f"{SITE}/{p['sport']}.html#player/{quote(str(p['pid']), safe='')}/{p['stat']}/{p['line']}/{p['side']}/{slug(p['player'])}"


def parse_utc(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def when(start, today):
    t = parse_utc(start)
    if t is None:
        return ""
    t = t.astimezone(ET)
    clock = t.strftime("%I:%M %p").lstrip("0") + " ET"
    return clock if t.date() == today else t.strftime("%a ") + clock


FAIR_W = 0.1   # the model's weight in the fair chance; read from today.json


def todays_picks(now):
    global FAIR_W
    doc = load("today.json", {}) or {}
    FAIR_W = ((doc.get("fair") or {}).get("w")) or FAIR_W
    ahead = [p for p in doc.get("picks") or [] if (parse_utc(p.get("start")) or now) > now]
    value = [p for p in ahead if p.get("kind") == "value"]
    return (value or ahead)[:MAX_PICKS], bool(value)


def yesterdays_results(yday):
    """Per sport: yesterday's graded Value spots (ET game day) — hits, count, units at the recorded price."""
    out = []
    for sport, path in PICK_FILES.items():
        doc = load(path)
        if not doc:
            continue
        cols = doc["cols"]
        n = hit = 0
        units = 0.0
        for row in doc["picks"]:
            p = dict(zip(cols, row))
            if p.get("src") != "live" or "V" not in (p.get("lists") or "") or p.get("res") not in ("hit", "miss"):
                continue
            t = parse_utc(p.get("start")) if p.get("start") else None
            day = t.astimezone(ET).date().isoformat() if t else p.get("date")   # NFL dates are already ET
            if day != yday.isoformat():
                continue
            n += 1
            price = p.get("price")
            if price:
                price = price / 100.0 if sport == "nfl" else price             # NFL records cents
            if p["res"] == "hit":
                hit += 1
                units += (1.0 / price - 1) if price else 0
            elif price:
                units -= 1
        if n:
            out.append((sport, hit, n, units))
    return out


def messages(picks, is_value, results, today):
    """(discord_markdown, telegram_html). Empty strings when there is nothing to say."""
    if not picks and not results:
        return "", ""
    d, t = [], []
    head = "⚡ Today's best value" if is_value else "🎯 Today's surest picks that still pay"
    d.append(f"**{head} — Prop Streak Lab**")
    t.append(f"<b>{head} — Prop Streak Lab</b>")
    for p in picks:
        bet = f"{p['player']} {p['side']} {p['line']} {p['statText']}"
        fair = FAIR_W * p["prob"] + (1 - FAIR_W) * p["price"]
        venue = "Kalshi" if p.get("vn") == "K" else "Polymarket"      # the cheaper of the two
        tail = f"model {round(p['prob'] * 100)}% · fair {round(fair * 100)}% · {round(p['price'] * 100)}¢ on {venue}"
        tail += f" · {when(p['start'], today)}"
        url = pick_link(p)
        d.append(f"{SPORT[p['sport']]} [**{bet}**](<{url}>) — {tail}")
        t.append(f"{SPORT[p['sport']]} <a href=\"{html.escape(url)}\"><b>{html.escape(bet)}</b></a> — {html.escape(tail)}")
    if not picks:
        d.append("No value spots on the board yet today — they post as the markets open.")
        t.append("No value spots on the board yet today — they post as the markets open.")
    if results:
        parts = [f"{SPORT[s]} {h}/{n} hit · {'+' if u >= 0 else '−'}{abs(u):.1f}u" for s, h, n, u in results]
        d.append("")
        d.append("📊 **Yesterday's Value spots:** " + " · ".join(parts))
        t.append("")
        t.append("📊 <b>Yesterday's Value spots:</b> " + html.escape(" · ".join(parts)))
    d.append("")
    d.append(f"Every pick is recorded before the game and graded in public → <{SITE}>")
    d.append(f"🎁 $25 free on Polymarket with code **PROPSTREAKLAB** → <{REFERRAL}>")
    d.append(f"🎁 $25 free on Kalshi → <{REFERRAL_KALSHI}>")
    d.append("-# Research, not betting advice. 18+.")
    t.append("")
    t.append(f"Every pick is recorded before the game and graded in public → {SITE}")
    t.append(f"🎁 $25 free on Polymarket with code <b>PROPSTREAKLAB</b> → {REFERRAL}")
    t.append(f"🎁 $25 free on Kalshi → {html.escape(REFERRAL_KALSHI)}")
    t.append("<i>Research, not betting advice. 18+.</i>")
    return "\n".join(d)[:1990], "\n".join(t)[:4000]


def send(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def main():
    dry = "--dry-run" in sys.argv
    force = dry or os.environ.get("POST_NOW", "").strip() in ("1", "true", "yes")
    now = datetime.datetime.now(datetime.timezone.utc)
    et = now.astimezone(ET)
    today = et.date()
    discord = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not dry and not (discord or (tg_token and tg_chat)):
        print("  daily post: no Discord/Telegram secrets set — skipped")
        return
    state = load(STATE, {}) or {}
    if not force:
        if et.hour < POST_HOUR_ET:
            print(f"  daily post: waits until {POST_HOUR_ET}:00 ET")
            return
        if state.get("date") == today.isoformat():
            print("  daily post: already posted today")
            return

    picks, is_value = todays_picks(now)
    results = yesterdays_results(today - datetime.timedelta(days=1))
    d_msg, t_msg = messages(picks, is_value, results, today)
    if not d_msg:
        print("  daily post: nothing to post yet")
        return
    if dry:
        print("----- Discord -----\n" + d_msg + "\n----- Telegram -----\n" + t_msg)
        return

    sent = []
    if discord:
        try:
            # flags 4 = no link previews, so five links don't become five embeds
            send(discord, {"content": d_msg, "flags": 4, "allowed_mentions": {"parse": []}})
            sent.append("Discord")
        except Exception as e:
            print(f"  daily post: Discord failed ({e})")
    if tg_token and tg_chat:
        try:
            send(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                 {"chat_id": tg_chat, "text": t_msg, "parse_mode": "HTML",
                  "disable_web_page_preview": True, "link_preview_options": {"is_disabled": True}})
            sent.append("Telegram")
        except Exception as e:
            print(f"  daily post: Telegram failed ({e})")
    if sent:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump({"date": today.isoformat(), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": sent}, f)
        print(f"  daily post: sent to {', '.join(sent)} ({len(picks)} pick(s))")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"  daily post skipped: {e}")
    sys.exit(0)

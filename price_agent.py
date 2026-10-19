"""
Prop Streak Lab — the price-move agent (team only, never on the public site).

today.json's "fastAll" (build_today.py) lists every upcoming pick whose price moved 10c+ in about
an hour, each with "why": what the site's own news feeds already say (ESPN injury status, MLB
lineups, NFL practice reports), or None. For Value spots the feeds can't explain, this asks Claude
(with web search) why the price moved, and keeps the answer, its confidence and its sources in
team/why.enc, encrypted with TEAM_DASH_PASSWORD like team/parlays.enc. The dashboard's Moving fast
panel shows the reason under each pick.

Cost control: at most PER_RUN picks a pass and PER_DAY a day (ET), each researched once per
direction of move per day. About $0.10-0.25 a pick (Claude Opus 5.5 tokens plus up to MAX_SEARCHES
web searches at $10 per 1,000).

Uses the anthropic package (installed by the update workflow; the builders stay standard library
only). Without ANTHROPIC_API_KEY, TEAM_DASH_PASSWORD or the package it does nothing. Never fails
the deploy.
"""
import datetime
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

import build_today
import team_stats

OUT = os.path.join("team", "why.enc")
TODAY_JSON = "today.json"
ET = ZoneInfo("America/New_York")
MODEL = "claude-opus-5-5"
PER_RUN = 3
PER_DAY = 15
MAX_SEARCHES = 5
MAX_CONTINUES = 3          # pause_turn resumes per pick
KEEP_DAYS = 3
SPORT = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB"}

SYSTEM = """You research sudden price moves in player-prop prediction markets (Polymarket, Kalshi) \
for a sports analytics team. You get one prop whose price moved 10 cents or more in about an hour. \
Search for news from the last few hours that explains it: an injury, a player ruled out or upgraded, \
a lineup, rotation or line change, a goalie or starting pitcher change, a teammate's absence, \
weather, a trade. Prefer team, league and beat-reporter sources.

Answer in two or three plain sentences: what happened, when it was reported, and how it explains \
the direction of the move. If nothing you find explains it, say so plainly instead of guessing. \
End with exactly one line: "Confidence: high", "Confidence: medium" or "Confidence: low"."""


def move_key(m):
    """One research per pick per direction of move per day."""
    return build_today.ckey(m) + ("|up" if m["price"] > m["was"] else "|down")


def to_do(fast_all, state, today):
    """The Value spots in fastAll that the site's feeds can't explain and that aren't researched
    yet, biggest move first, within today's budget."""
    done = state.get("days", {}).get(today, {})
    left = min(PER_RUN, PER_DAY - len(done))
    todo = [m for m in fast_all or [] if "V" in (m.get("lists") or "") and not m.get("why")
            and move_key(m) not in done]
    todo.sort(key=lambda m: -abs(m["price"] - m["was"]))
    return todo[:max(0, left)]


def prompt(m, now):
    et = lambda s: build_today.parse_start(s).astimezone(ET).strftime("%b %d, %I:%M %p ET").replace(" 0", " ")
    return (f"{SPORT.get(m['sport'], m['sport'])}: {m['player']} ({m.get('team')} vs {m.get('opp')}), "
            f"{m['side']} {m['line']} {m.get('statText') or m['stat']}. The game starts {et(m['start'])}.\n"
            f"The price to bet this side moved from {round(m['was'] * 100)}c to {round(m['price'] * 100)}c "
            f"in the last hour (now {now.astimezone(ET).strftime('%b %d, %I:%M %p ET').replace(' 0', ' ')}). "
            f"A higher price means the market now thinks this side is more likely.")


def parse(content, stop_reason):
    """(reason, confidence, sources) from a response's content blocks."""
    if stop_reason == "refusal":
        return "Claude declined to research this one.", "low", []
    text, sources = [], []
    for b in content:
        if getattr(b, "type", None) == "text":
            text.append(b.text)
            for c in getattr(b, "citations", None) or []:
                if getattr(c, "url", None):
                    sources.append({"title": getattr(c, "title", None) or c.url, "url": c.url})
    if not sources:   # no inline citations: the top search results
        for b in content:
            if getattr(b, "type", None) == "web_search_tool_result" and isinstance(b.content, list):
                sources += [{"title": getattr(r, "title", None) or r.url, "url": r.url} for r in b.content[:3]]
    body = " ".join("".join(text).split())
    m = re.search(r"Confidence:\s*(high|medium|low)\b\.?", body, re.I)
    conf = m.group(1).lower() if m else "low"
    if m:
        body = (body[:m.start()] + body[m.end():]).strip()
    seen, uniq = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"]); uniq.append(s)
    return (body or "No answer.")[:700], conf, uniq[:4]


def research(client, m, now):
    messages = [{"role": "user", "content": prompt(m, now)}]
    for _ in range(MAX_CONTINUES + 1):
        r = client.beta.messages.create(
            model=MODEL, max_tokens=8000, system=SYSTEM, messages=messages,
            output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}],
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if r.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": r.content}]   # resume the paused turn
    return parse(r.content, r.stop_reason), r.model


def read_state(password):
    try:
        with open(OUT, encoding="ascii") as f:
            return json.loads(team_stats.decrypt(f.read().strip(), password))
    except FileNotFoundError:
        return {"days": {}}


def main():
    password, key = os.environ.get("TEAM_DASH_PASSWORD", ""), os.environ.get("ANTHROPIC_API_KEY", "")
    if not password or not key:
        print("price agent: TEAM_DASH_PASSWORD or ANTHROPIC_API_KEY not set, skipping")
        return 0
    try:
        import anthropic
    except ImportError:
        print("price agent: the anthropic package isn't installed, skipping")
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(ET).date().isoformat()
    with open(TODAY_JSON, encoding="utf-8") as f:
        fast_all = json.load(f).get("fastAll") or []
    state = read_state(password)    # an unreadable file raises: never start over and lose the record
    days = state.setdefault("days", {})
    old = (now.astimezone(ET).date() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    changed = False
    for d in [d for d in days if d <= old]:
        del days[d]; changed = True
    todo = to_do(fast_all, state, today)
    client = anthropic.Anthropic(timeout=90.0, max_retries=1)
    for m in todo:
        try:
            (reason, conf, sources), model = research(client, m, now)
        except anthropic.APIError as e:
            print(f"price agent: research skipped ({type(e).__name__}: {str(e)[:150]})")   # health.py flags it
            break      # an outage or a limit: try again next pass
        days.setdefault(today, {})[move_key(m)] = {
            "key": build_today.ckey(m), "sport": m["sport"], "player": m["player"], "stat": m["stat"],
            "line": m["line"], "side": m["side"], "was": m["was"], "price": m["price"],
            "at": now.strftime("%Y-%m-%dT%H:%MZ"), "reason": reason, "conf": conf, "sources": sources, "model": model}
        changed = True
        print(f"price agent: {m['player']} {m['side']} {m['line']} {m['stat']} "
              f"{round(m['was'] * 100)}c -> {round(m['price'] * 100)}c: {conf}")
    if not changed:
        print(f"price agent: nothing to research ({len(todo)} new Value move(s))")
        return 0
    state["gen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="ascii") as f:
        f.write(team_stats.encrypt(json.dumps(state, separators=(",", ":")), password) + "\n")
    print(f"price agent: wrote {OUT} ({len(days.get(today, {}))} researched today)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"price agent failed ({type(e).__name__}: {e})")
        sys.exit(0)

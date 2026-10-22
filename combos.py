"""
Prop Streak Lab — which player props Polymarket US lets you put in a parlay.

Every Polymarket US market carries "comboEnabled". On Oct 22, 2026 it was off for every NHL assists
market (over and under alike) and on for every other prop type we price, so a parlay with an NHL
assists leg couldn't actually be placed. The flag is set by prop type, so this reads a few of each
sport's upcoming games once per run and returns the (sport, stat) pairs where no market allows
parlays. parlay.py and tpod.py keep those out of parlay legs.

Standard library only; never fatal: a sport that can't be read falls back to KNOWN.
"""
import datetime
import json
import urllib.request

LIST = ("https://gateway.polymarket.us/v1/events?tagSlug={tag}&active=true&closed=false"
        "&startDateMin={a}T00:00:00Z&startDateMax={b}T00:00:00Z&limit=20")
EVENT = "https://gateway.polymarket.us/v1/events/slug/{slug}"
UA = {"Accept": "application/json", "User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}
GAMES = 3          # games read per sport: the flag is the same for every market of a type
# Polymarket's prop type (after "_player_") -> our stat key, per sport.
STAT = {
    "nhl": {"goals": "g", "assists": "a", "points": "pts", "shots_on_goal": "sog"},
    "nba": {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "tpm", "steals": "stl", "blocks": "blk",
            "points_rebounds_assists": "pra", "points_rebounds": "pr", "points_assists": "pa", "rebounds_assists": "ra"},
    "nfl": {"passing_yards": "pass_yds", "passing_touchdowns": "pass_td", "passing_completions": "pass_cmp",
            "passing_attempts": "pass_att", "interceptions_thrown": "pass_int", "rushing_yards": "rush_yds",
            "rushing_attempts": "rush_att", "receiving_yards": "rec_yds", "receptions": "rec",
            "scrimmage_yards": "rush_rec_yds", "touchdowns": "scrim_td"},
    "mlb": {"hits": "h", "home_runs": "hr", "rbis": "rbi", "runs": "r", "walks": "bb", "total_bases": "tb",
            "hits_runs_rbis": "hrr", "stolen_bases": "sb", "strikeouts": "k", "outs": "outs", "hits_allowed": "ha",
            "earned_runs_allowed": "er", "walks_allowed": "pbb"},
}
KNOWN = {("nhl", "a")}     # what was seen on Oct 22, 2026: used for a sport that can't be read
_cache = {}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def blocked_types(markets, sport):
    """{our stat key} of the prop types in these markets where none allows parlays."""
    seen = {}
    for m in markets:
        smt = m.get("sportsMarketType") or ""
        if "_player_" not in smt or m.get("closed"):
            continue
        t = smt.split("_player_", 1)[1]
        seen[t] = seen.get(t, False) or bool(m.get("comboEnabled"))
    return {STAT.get(sport, {}).get(t, t) for t, ok in seen.items() if not ok}


def blocked(sport, today=None):
    """{stat key} of this sport's player props Polymarket US won't put in a parlay (cached per run)."""
    if sport in _cache:
        return _cache[sport]
    today = today or datetime.date.today()
    out = {s for sp, s in KNOWN if sp == sport}
    try:
        lst = _get(LIST.format(tag=sport, a=today.isoformat(), b=(today + datetime.timedelta(days=7)).isoformat()))
        markets = []
        for ev in (lst.get("events") or [])[:GAMES]:
            markets += (_get(EVENT.format(slug=ev["slug"])).get("event") or {}).get("markets") or []
        if markets:
            out = blocked_types(markets, sport)
    except Exception as e:  # noqa: BLE001
        print(f"  combos {sport}: couldn't read Polymarket US ({e}); using the last known list")
    _cache[sport] = out
    return out


def allowed(sport, stat, today=None):
    return stat not in blocked(sport, today)

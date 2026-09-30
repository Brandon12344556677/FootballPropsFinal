"""
Prop Streak Lab — pre-game news feeds, in TEST MODE.

Each builder calls into this after its picks are made. Nothing here changes a chance the
site shows or a list a pick is on: the news is recorded on each pending pick (the "nw"
column) and refreshed every run until its game starts, next to "p2", the chance the pick
would have with the news applied at the strength the backtest found. Each build logs how
the recorded chances compare with p2 on graded picks, so a feed is switched on only after
its data shows up and p2 predicts better.

  - ESPN injury reports (NBA, NFL): each player's status; for the NBA, the usual minutes of
    regular teammates listed Out ("om"). Backtest (2025-26 box scores, a regular's absence
    known from the box score): points, assists, threes and PRA rose ~5% per 48 missing
    minutes, better on both halves of the season.
  - MLB confirmed lineups (statsapi.mlb.com): a hitter's spot, 0 = his team's lineup is
    posted and he isn't in it.
  - Weather (open-meteo.com) at outdoor NFL stadiums and MLB parks: temperature (F), wind
    (mph), precipitation (mm) for the start hour. Backtest (nflverse's game-day wind,
    2025-26): passing yards, completions and receptions fall ~10% per 10 mph over 10 mph,
    better on both halves; rushing and cold showed nothing.

Standard library only. Every fetch is non-fatal: a feed that can't be reached prints
"news test: <feed> unavailable (...)" and records nothing.
"""
import datetime
import json
import math
import urllib.request

UA = {"User-Agent": "prop-streak-lab/2.0 (+https://propstreaklab.com)"}
TIMEOUT = 15

# Test-mode strengths (from the backtests above).
NBA_OUT_BOOST = 0.05          # scale x (1 + this * missing minutes / 48)
NBA_OUT_STATS = {"pts", "ast", "tpm", "pra"}
WIND_PER_10 = -0.10           # scale x (1 + this * max(0, wind - 10) / 10)
WIND_STATS = {"pass_yds", "pass_cmp", "rec"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _log(msg):
    print(f"  news test: {msg}")


# ---------------------------------------------------------------------------
# ESPN injury reports
# ---------------------------------------------------------------------------
def espn_injuries(league):
    """league 'basketball/nba' or 'football/nfl' -> [{"id", "name", "status"}], or None.
    The feed lists teams, each with its injured players; ids are ESPN athlete ids."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{league}/injuries"
    try:
        d = get_json(url)
    except Exception as e:  # noqa: BLE001
        _log(f"{league} injuries unavailable ({e})")
        return None
    out = []
    for team in d.get("injuries") or []:
        for inj in team.get("injuries") or []:
            ath = inj.get("athlete") or {}
            aid = str(ath.get("id") or "")
            if not aid:                       # some payloads only carry the id in a link
                for ln in ath.get("links") or []:
                    href = ln.get("href") or ""
                    if "/id/" in href:
                        aid = href.split("/id/")[1].split("/")[0]
                        break
            status = inj.get("status") or (inj.get("type") or {}).get("description") or ""
            name = ath.get("displayName") or ath.get("fullName") or ""
            if name or aid:
                out.append({"id": aid, "name": name, "status": str(status)})
    _log(f"{league} injuries: {len(out)} player(s) listed")
    return out


def is_out(status):
    return (status or "").strip().lower() in ("out", "injured reserve", "suspension", "suspended", "doubtful")


# ---------------------------------------------------------------------------
# MLB confirmed lineups
# ---------------------------------------------------------------------------
STATSAPI_TEAM = {"AZ": "ARI", "CWS": "CHW", "OAK": "ATH", "WAS": "WSH"}   # statsapi -> ESPN codes


def mlb_lineups(dates, key):
    """{date: {team code: [player keys in batting order]}} for lineups MLB has posted, or None.
    key normalizes a name the way the builder does (pkey)."""
    out = {}
    try:
        for d in sorted(set(dates)):
            doc = get_json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}&hydrate=lineups,team")
            for day in doc.get("dates") or []:
                for g in day.get("games") or []:
                    lu = g.get("lineups") or {}
                    for side in ("away", "home"):
                        players = lu.get(f"{side}Players") or []
                        team = ((g.get("teams") or {}).get(side) or {}).get("team") or {}
                        code = team.get("abbreviation") or ""
                        code = STATSAPI_TEAM.get(code, code)
                        if players and code:
                            out.setdefault(d, {})[code] = [key(p.get("fullName") or "") for p in players]
    except Exception as e:  # noqa: BLE001
        _log(f"MLB lineups unavailable ({e})")
        return None
    _log(f"MLB lineups: {sum(len(v) for v in out.values())} posted")
    return out


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
# Outdoor NFL stadiums by name, as nflverse's schedule spells them (incl. neutral sites).
NFL_STADIUMS = {
    "M&T Bank Stadium": (39.278, -76.623), "Highmark Stadium": (42.774, -78.787),
    "Bank of America Stadium": (35.226, -80.853), "Soldier Field": (41.862, -87.617),
    "Paycor Stadium": (39.095, -84.516), "Huntington Bank Field": (41.506, -81.700),
    "Empower Field at Mile High": (39.744, -105.020), "Lambeau Field": (44.501, -88.062),
    "EverBank Stadium": (30.324, -81.638), "GEHA Field at Arrowhead Stadium": (39.049, -94.484),
    "Hard Rock Stadium": (25.958, -80.239), "Gillette Stadium": (42.091, -71.264),
    "MetLife Stadium": (40.814, -74.074), "Lincoln Financial Field": (39.901, -75.168),
    "Acrisure Stadium": (40.447, -80.016), "Levi's Stadium": (37.403, -121.970),
    "Lumen Field": (47.595, -122.332), "Raymond James Stadium": (27.976, -82.503),
    "Nissan Stadium": (36.166, -86.771), "Northwest Stadium": (38.908, -76.864),
    "Tottenham Hotspur Stadium": (51.604, -0.066), "Wembley Stadium": (51.556, -0.280),
    "Estadio Banorte": (19.303, -99.150), "Bernabeu": (40.453, -3.688),
}
# MLB parks by home team: (lat, lon, roof) with roof "open", "retractable" or "dome".
MLB_PARKS = {
    "ARI": (33.445, -112.067, "retractable"), "ATL": (33.891, -84.468, "open"), "BAL": (39.284, -76.622, "open"),
    "BOS": (42.346, -71.097, "open"), "CHC": (41.948, -87.656, "open"), "CHW": (41.830, -87.634, "open"),
    "CIN": (39.097, -84.507, "open"), "CLE": (41.496, -81.685, "open"), "COL": (39.756, -104.994, "open"),
    "DET": (42.339, -83.049, "open"), "HOU": (29.757, -95.355, "retractable"), "KC": (39.051, -94.480, "open"),
    "LAA": (33.800, -117.883, "open"), "LAD": (34.074, -118.240, "open"), "MIA": (25.778, -80.220, "retractable"),
    "MIL": (43.028, -87.971, "retractable"), "MIN": (44.982, -93.278, "open"), "NYM": (40.757, -73.846, "open"),
    "NYY": (40.829, -73.926, "open"), "ATH": (38.580, -121.514, "open"), "PHI": (39.906, -75.166, "open"),
    "PIT": (40.447, -80.006, "open"), "SD": (32.707, -117.157, "open"), "SF": (37.778, -122.389, "open"),
    "SEA": (47.591, -122.332, "retractable"), "STL": (38.623, -90.193, "open"), "TB": (27.768, -82.653, "dome"),
    "TEX": (32.747, -97.084, "retractable"), "TOR": (43.641, -79.389, "retractable"), "WSH": (38.873, -77.007, "open"),
}
_WX = {}
_WX_DOWN = []    # set on the first failed request: the rest of the run skips weather


def forecast(lat, lon, start_iso):
    """[temp F, wind mph, precip mm] for the hour a game starts ('2026-10-04T17:00Z'), or None.
    One request per location per run."""
    try:
        t = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except (AttributeError, ValueError):
        return None
    k = (round(lat, 2), round(lon, 2))
    if k not in _WX and _WX_DOWN:
        return None
    if k not in _WX:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%.3f&longitude=%.3f"
               "&hourly=temperature_2m,wind_speed_10m,precipitation&temperature_unit=fahrenheit"
               "&wind_speed_unit=mph&timezone=GMT&forecast_days=10" % (lat, lon))
        try:
            _WX[k] = get_json(url).get("hourly") or {}
        except Exception as e:  # noqa: BLE001
            _log(f"weather unavailable ({e})")
            _WX[k] = {}
            _WX_DOWN.append(1)
    h = _WX[k]
    try:
        i = (h.get("time") or []).index(t.strftime("%Y-%m-%dT%H:00"))
        return [round(h["temperature_2m"][i], 1), round(h["wind_speed_10m"][i], 1), round(h["precipitation"][i], 1)]
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def wind_factor(wind):
    return 1 + WIND_PER_10 * max(0.0, wind - 10.0) / 10.0


# ---------------------------------------------------------------------------
# The log line that decides when a feed goes live
# ---------------------------------------------------------------------------
def report(picks, label):
    """Log loss of the recorded chance vs p2 (the chance with the news) on graded picks."""
    rows = [(p["prob"], p["nw"]["p2"], 1.0 if p["res"] == "hit" else 0.0) for p in picks
            if p.get("res") in ("hit", "miss") and isinstance(p.get("nw"), dict)
            and p["nw"].get("p2") is not None and p.get("prob") is not None]
    if not rows:
        _log(f"{label}: no graded picks with a news chance yet")
        return

    def ll(q, y):
        q = min(0.999, max(0.001, q))
        return -(y * math.log(q) + (1 - y) * math.log(1 - q))
    a = sum(ll(r[0], r[2]) for r in rows) / len(rows)
    b = sum(ll(r[1], r[2]) for r in rows) / len(rows)
    _log(f"{label}: {len(rows)} graded picks, log loss live {a:.4f} vs with news {b:.4f}"
         f" ({'news better' if b < a else 'live better'})")

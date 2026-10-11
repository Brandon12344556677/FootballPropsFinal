"""
Prop Streak Lab — one static page per upcoming game, for search engines and for browsing by game.

The boards are organized by prop and by player; a search for "Capitals Kraken props" or a
fan who thinks in games has nothing to land on. This writes:

  games/<sport>/<away>-at-<home>-<date>.html   every modeled prop for that game, by team
                                               (model chance, market price, verdict), each
                                               linking into the board's full breakdown
  games/index.html                             the upcoming games, by sport and start time
  sitemap.xml                                  the game pages added (build.py rewrites it each run)

Rebuilt every run from the picks files the builders just wrote: a page lives until its game
starts, then it's removed. Shares the page style and price rules with build_players.py.
Standard library only; never fails the deploy.
"""
import datetime
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

import build_today as T
import build_players as P

SITE = "https://propstreaklab.com"
OUT = "games"
ET = ZoneInfo("America/New_York")
PER_PLAYER = 3     # props per player on a game page
PER_TEAM = 14      # players per team
VERDICT_RANK = {"value": 0, "t25": 1, "fair": 2, "skip": 3, "none": 4}


def teams_of(sport, gid, db):
    """(away, home) for a game id. NFL ids are season_week_AWAY_HOME (nflverse); the others
    are date-AWAY-HOME. The NFL week schedule is checked first when it has the game."""
    if sport == "nfl":
        for g in (db.get("week") or {}).get("games") or []:
            if g.get("id") == gid and g.get("away") and g.get("home"):
                return g["away"], g["home"]
        parts = str(gid).split("_")
        return (parts[2], parts[3]) if len(parts) >= 4 else (None, None)
    m = re.match(r"^\d{4}-\d{2}-\d{2}-([A-Z0-9]+)-([A-Z0-9]+)$", str(gid))
    return (m.group(1), m.group(2)) if m else (None, None)


def board_tag(lists, prob, price):
    """The same calls the board makes: Value and Top 25 only when the builder put the prop on
    that list (it also checks the money offered and how far the model is from the market);
    otherwise the price comparison, never "Value"."""
    if "V" in lists:
        return "Value", "value"
    if "T" in lists:
        return "Top 25", "t25"
    label, cls = P.verdict(prob, price)
    return ("Fair", "fair") if cls == "value" else (label, cls)


def game_props(sport, db, picks_doc, labels, now):
    """gid -> {"start", "away", "home", "props": [...]} for every game that hasn't started."""
    cols = picks_doc["cols"]
    kick = T.nfl_kickoffs(db) if sport == "nfl" else {}
    cents = 100.0 if sport == "nfl" else 1.0
    games = {}
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") is not None or p.get("prob") is None or not p.get("gid"):
            continue
        start = kick.get(p["gid"]) if sport == "nfl" else T.parse_start(p.get("start"))
        timed = start is not None
        if start is None and sport != "nfl":
            # some picks are saved without a start time (NHL preseason): the game id's date, kept
            # through the end of that day, with the time shown as TBA
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-", p["gid"])
            if m:
                start = datetime.datetime.fromisoformat(m.group(1) + "T23:59").replace(tzinfo=ET)
        if start is None or start <= now:
            continue
        g = games.get(p["gid"])
        if g is None:
            away, home = teams_of(sport, p["gid"], db)
            if not away:
                continue
            g = games[p["gid"]] = {"start": start, "timed": timed, "away": away, "home": home, "props": []}
        elif timed and not g["timed"]:      # a pick with the real start time beats the date-only guess
            g["start"], g["timed"] = start, True
        price = None if p.get("price") is None else float(p["price"]) / cents
        prob = T.cap(p["prob"])
        label, cls = board_tag(p.get("lists") or "", prob, price)
        g["props"].append({"pid": str(p["pid"]), "player": p["player"], "team": p.get("team"), "stat": p["stat"],
                           "statText": labels.get(p["stat"], p["stat"]), "line": p["line"], "side": p.get("side") or "over",
                           "prob": prob, "price": price, "edge": None if price is None else prob - price,
                           "verdict": label, "cls": cls})
    return games


def by_team(props, team):
    """A team's players, best first, each with up to PER_PLAYER props: one line per stat and
    side (the one closest to a coin flip, the informative one), Value first, then priced, then
    by model chance."""
    players = {}
    for c in props:
        if c["team"] != team:
            continue
        best = players.setdefault(c["pid"], {})
        k = (c["stat"], c["side"])
        if k not in best or abs(c["prob"] - 0.5) < abs(best[k]["prob"] - 0.5):
            best[k] = c
    rank = lambda c: (VERDICT_RANK[c["cls"]], -(c["edge"] or 0), -c["prob"])
    rows = [sorted(b.values(), key=rank)[:PER_PLAYER] for b in players.values()]
    rows.sort(key=lambda lst: rank(lst[0]))
    return rows[:PER_TEAM]


def page_slug(g):
    return f"{g['away']}-at-{g['home']}-{g['start'].astimezone(ET).date().isoformat()}".lower()


def when(start, timed=True):
    t = start.astimezone(ET)
    day = t.strftime("%a, %b ") + str(t.day)
    return day + ", " + t.strftime("%I:%M %p").lstrip("0") + " ET" if timed else day + ", time TBA"


def prop_row(sport, c, show_player=True):
    pct = f"{round(c['prob'] * 100)}%"
    px = "—" if c["price"] is None else f"{round(c['price'] * 100)}¢"
    who = f'<a href="{P.esc(P.pick_link(sport, c))}">{P.esc(c["player"])}</a>' if show_player else ""
    return (f"<tr><td>{who}</td><td><span class=\"side {c['side']}\">{c['side']}</span> {P.esc(c['line'])} {P.esc(c['statText'])}</td>"
            f"<td class=\"n\">{pct}</td><td class=\"n\">{px}</td><td><span class=\"tag {c['cls']}\">{P.esc(c['verdict'])}</span></td></tr>")


GAME_CSS = "\n.tag.t25{background:rgba(232,181,74,.18);color:#f3cd7a}"
# cookieless visit counts (GoatCounter, as on the boards) for the game and best-props pages
GC_TAG = '<script data-goatcounter="https://propstreaklive.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>\n'
TABLE_HEAD = '<div class="card scroll"><table class="props"><thead><tr><th>Player</th><th>Prop</th><th class="n">Model</th><th class="n">Price</th><th>Verdict</th></tr></thead><tbody>'


def game_page(sport, g, built):
    name, away, home = P.SPORT_NAME[sport], g["away"], g["home"]
    url = f"{SITE}/{OUT}/{sport}/{page_slug(g)}.html"
    n = len(g["props"])
    values = sorted((c for c in g["props"] if c["cls"] in ("value", "t25")), key=lambda c: (VERDICT_RANK[c["cls"]], -(c["edge"] or 0), -c["prob"]))
    title = f"{away} @ {home} player props, {g['start'].astimezone(ET).strftime('%b')} {g['start'].astimezone(ET).day} | {name} | Prop Streak Lab"
    desc = (f"{away} @ {home} ({name}, {when(g['start'], g.get('timed', True))}): {n} player props with the model's chance, the market price"
            f"{f', {len(values)} on the Value and Top 25 lists' if values else ''}. Free, updated every 10 minutes.")
    h = P.HEAD.format(title=P.esc(title), desc=P.esc(desc), url=url, og_title=P.esc(f"{away} @ {home} player props"),
                      site=SITE, css=P.CSS + GAME_CSS, crumbs=f'<a href="/{OUT}/">Games</a> · {name}').replace('content="profile"', 'content="website"').replace('</head>', GC_TAG + '</head>', 1)
    h += f"  <h1>{P.esc(away)} @ {P.esc(home)} player props</h1>\n"
    h += f'  <p class="sub">{name} · {P.esc(when(g["start"], g.get("timed", True)))} · {n} props modeled · updated {P.esc(built)}</p>\n'
    h += f'  <p><a class="cta" href="/{sport}.html">Open the {name} board →</a></p>\n'
    if values:
        h += "  <h2>On the boards for this game</h2>\n  " + TABLE_HEAD
        h += "".join(prop_row(sport, c) for c in values[:10]) + "</tbody></table></div>\n"
        h += ('  <p class="note">This game\'s props on the board\'s Value and Top 25 Surest lists. Value: the model rates it well '
              'above a price of 30¢ or more. Top 25: among the surest props on the slate.</p>\n')
    for team in (away, home):
        rows = by_team(g["props"], team)
        if not rows:
            continue
        h += f"  <h2>{P.esc(team)} props</h2>\n  " + TABLE_HEAD
        for lst in rows:
            h += "".join(prop_row(sport, c, show_player=(i == 0)) for i, c in enumerate(lst))
        h += "</tbody></table></div>\n"
    h += ('  <p class="note">Model: the chance the prop hits, from the player\'s game logs. Price: the cheaper of Polymarket and Kalshi '
          'at the last update. Tap a player for the full breakdown on the board. Picks leave this page when the game starts.</p>\n')
    return h + P.FOOT.replace('<a href="/players/">All players</a>', f'<a href="/players/">All players</a> · <a href="/{OUT}/">All games</a>'), url


def index_page(listing, built):
    h = P.HEAD.format(title="Upcoming games: player props by game | Prop Streak Lab",
                      desc="Every upcoming NFL, NBA, NHL and MLB game with its player props, the model's chance and the market price. Free.",
                      url=f"{SITE}/{OUT}/", og_title="Player props by game", site=SITE, css=P.CSS,
                      crumbs="Games").replace('content="profile"', 'content="website"').replace('</head>', GC_TAG + '</head>', 1)
    h += "  <h1>Player props by game</h1>\n"
    h += f'  <p class="sub">Every upcoming game with modeled props · updated {P.esc(built)}</p>\n'
    if not listing:
        h += '  <p>No upcoming games with props right now. Games appear here once the next slate is posted.</p>\n'
    for sport in ("nfl", "nba", "nhl", "mlb"):
        games = listing.get(sport)
        if not games:
            continue
        h += f"  <h2>{P.SPORT_NAME[sport]}</h2>\n  <div class=\"card\"><table><tbody>"
        for g, href in games:
            h += (f'<tr><td><a href="{href}">{P.esc(g["away"])} @ {P.esc(g["home"])}</a></td>'
                  f'<td>{P.esc(when(g["start"], g.get("timed", True)))}</td><td class="n">{len(g["props"])} props</td></tr>')
        h += "</tbody></table></div>\n"
    return h + P.FOOT.replace('<a href="/players/">All players</a>', f'<a href="/players/">All players</a> · <a href="/{OUT}/">All games</a>')


BEST = "best"      # best/<sport>.html: today's Value and Top 25 picks for one sport (fixed address, rebuilt each run)
SHARE = "p"        # p/<sport>/<pid>-<stat>-<line>-<side>.html: a link preview for one listed pick (noindex)
SHARE_DAYS = 14    # a share page outlives its game by this many days, so links already sent keep working
GUIDES = ["guides/", "guides/what-is-a-player-prop.html", "guides/polymarket-and-kalshi.html",
          "guides/how-to-read-the-model.html"]   # hand-written pages, listed here for the sitemap


def share_key(c):
    """Matches app.js shareKey(): pid-stat-line-side, the line written like JavaScript's String(n)."""
    return f"{c['pid']}-{c['stat']}-{float(c['line']):g}-{c['side']}"


def best_page(sport, rows, built, today):
    """rows: [(prop, game)] across the sport's upcoming games, Value first, then Top 25."""
    name = P.SPORT_NAME[sport]
    url = f"{SITE}/{BEST}/{sport}.html"
    day = today.strftime("%a, %b ") + str(today.day)
    values = [r for r in rows if r[0]["cls"] == "value"]
    tops = [r for r in rows if r[0]["cls"] == "t25"]
    title = f"Best {name} player props today ({day}) | Prop Streak Lab"
    desc = (f"Today's best {name} player props: {len(values)} value spot{'' if len(values) == 1 else 's'} and the surest props on the "
            f"slate, with the model's chance and the market price. Free, updated every 10 minutes.")
    h = P.HEAD.format(title=P.esc(title), desc=P.esc(desc), url=url, og_title=P.esc(f"Best {name} player props today"),
                      site=SITE, css=P.CSS + GAME_CSS, crumbs=f'<a href="/{BEST}/">Best props</a> · {name}').replace('content="profile"', 'content="website"').replace('</head>', GC_TAG + '</head>', 1)
    h += f"  <h1>Best {name} player props today</h1>\n"
    h += f'  <p class="sub">{P.esc(day)} · from every upcoming {name} game · updated {P.esc(built)}</p>\n'
    h += f'  <p><a class="cta" href="/{sport}.html">Open the {name} board →</a></p>\n'
    head = ('<div class="card scroll"><table class="props"><thead><tr><th>Player</th><th>Prop</th><th>Game</th>'
            '<th class="n">Model</th><th class="n">Price</th></tr></thead><tbody>')

    def row(c, g):
        px = "—" if c["price"] is None else f"{round(c['price'] * 100)}¢"
        game = f'<a href="/{OUT}/{sport}/{page_slug(g)}.html">{P.esc(g["away"])} @ {P.esc(g["home"])}</a>'
        return (f'<tr><td><a href="{P.esc(P.pick_link(sport, c))}">{P.esc(c["player"])}</a></td>'
                f'<td><span class="side {c["side"]}">{c["side"]}</span> {P.esc(c["line"])} {P.esc(c["statText"])}</td>'
                f'<td>{game}</td><td class="n">{round(c["prob"] * 100)}%</td><td class="n">{px}</td></tr>')
    if not rows:
        h += f"  <p>No {name} picks on the board right now. They appear here once the next slate's markets open.</p>\n"
    if values:
        h += '  <h2>Value spots</h2>\n  <p class="note">The model rates these well above a price of 30¢ or more: the best bets for the money.</p>\n  ' + head
        h += "".join(row(c, g) for c, g in values[:20]) + "</tbody></table></div>\n"
    if tops:
        h += '  <h2>Top 25 Surest</h2>\n  <p class="note">The props the model is surest about: smaller payouts, the highest hit rate.</p>\n  ' + head
        h += "".join(row(c, g) for c, g in tops[:25]) + "</tbody></table></div>\n"
    h += ('  <p class="note">Model: the chance the prop hits. Price: the cheaper of Polymarket and Kalshi at the last update. '
          'Every pick is recorded before the game and graded in public.</p>\n')
    return h + P.FOOT.replace('<a href="/players/">All players</a>', f'<a href="/players/">All players</a> · <a href="/{OUT}/">All games</a>'), url


def best_index(counts, built):
    h = P.HEAD.format(title="Best player props today: NFL, NBA, NHL, MLB | Prop Streak Lab",
                      desc="Today's best player props for every sport: value spots and the surest props, with the model's chance and the market price.",
                      url=f"{SITE}/{BEST}/", og_title="Best player props today", site=SITE, css=P.CSS + GAME_CSS,
                      crumbs="Best props").replace('content="profile"', 'content="website"').replace('</head>', GC_TAG + '</head>', 1)
    h += "  <h1>Best player props today</h1>\n"
    h += f'  <p class="sub">Updated {P.esc(built)}</p>\n  <div class="card"><table><tbody>'
    for sport in ("nfl", "nba", "nhl", "mlb"):
        n = counts.get(sport)
        label = f"{n} pick{'' if n == 1 else 's'} today" if n else "no picks right now"
        h += f'<tr><td><a href="/{BEST}/{sport}.html">Best {P.SPORT_NAME[sport]} player props</a></td><td class="n">{label}</td></tr>'
    h += "</tbody></table></div>\n"
    return h + P.FOOT.replace('<a href="/players/">All players</a>', f'<a href="/players/">All players</a> · <a href="/{OUT}/">All games</a>')


def share_page(sport, c, g):
    """A link preview for one pick: the title and description a chat app shows, then straight on to
    the pick on its board. noindex: it's a doorway for shared links, not a page to rank."""
    target = SITE + P.pick_link(sport, c)
    title = f"{c['player']} {c['side']} {float(c['line']):g} {c['statText']}"
    price = "" if c["price"] is None else f" · {round(c['price'] * 100)}¢ at the market"
    desc = (f"Model: {round(c['prob'] * 100)}% chance{price} · {g['away']} @ {g['home']}, {when(g['start'], g.get('timed', True))}. "
            f"The game log and the full breakdown, free on Prop Streak Lab.")
    e, t, d = P.esc, P.esc(title), P.esc(desc)
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{t} | Prop Streak Lab</title>\n<meta name=\"description\" content=\"{d}\">\n"
            "<meta name=\"robots\" content=\"noindex\">\n"
            f"<link rel=\"canonical\" href=\"{e(target)}\">\n"
            "<meta property=\"og:type\" content=\"website\">\n"
            f"<meta property=\"og:url\" content=\"{e(target)}\">\n<meta property=\"og:title\" content=\"{t}\">\n"
            f"<meta property=\"og:description\" content=\"{d}\">\n<meta property=\"og:site_name\" content=\"Prop Streak Lab\">\n"
            f"<meta property=\"og:image\" content=\"{SITE}/icon-512.png\">\n<meta name=\"twitter:card\" content=\"summary\">\n"
            f"<meta name=\"twitter:title\" content=\"{t}\">\n<meta name=\"twitter:description\" content=\"{d}\">\n"
            f"<meta http-equiv=\"refresh\" content=\"0; url={e(target)}\">\n"
            f"<script>location.replace({json.dumps(target)});</script>\n</head>\n"
            "<body style=\"background:#0a1628;color:#dfe6ef;font-family:system-ui,sans-serif;padding:24px\">\n"
            f"<p><a style=\"color:#22d07f\" href=\"{e(target)}\">Open {t} on Prop Streak Lab →</a></p>\n</body>\n</html>\n")


def update_sitemap(urls, day):
    try:
        with open("sitemap.xml", "r", encoding="utf-8") as f:
            sm = f.read()
    except OSError:
        return
    sm = re.sub(r"\s*<url>\s*<loc>[^<]*/(games|best|guides)/[^<]*</loc>.*?</url>", "", sm, flags=re.S)
    add = "".join(f"\n  <url><loc>{u}</loc><lastmod>{day}</lastmod><changefreq>hourly</changefreq><priority>0.6</priority></url>" for u in urls)
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sm.replace("</urlset>", add + "\n</urlset>"))


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    built = now.astimezone(ET).strftime("%b ") + str(now.astimezone(ET).day) + now.astimezone(ET).strftime(", %I:%M %p ET").replace(" 0", " ")
    try:
        P.FAIR_W = T.fair_weight([(sp, T.load(pf)) for sp, _, pf, _ in T.SPORTS if os.path.exists(pf)])["w"]
    except Exception as e:
        print(f"  fair weight: default ({e})")
    listing, keep, best_counts = {}, set(), {}
    try:   # {sport: {share key: expiry date}}: every share page still kept, so old links don't break
        with open(os.path.join(SHARE, "keys.json"), encoding="utf-8") as f:
            kept = json.load(f)
    except (OSError, ValueError):
        kept = {}
    today = now.astimezone(ET).date().isoformat()
    kept = {sp: {k: d for k, d in keys.items() if isinstance(d, str) and d >= today} for sp, keys in kept.items() if isinstance(keys, dict)}
    urls = [f"{SITE}/{OUT}/", f"{SITE}/{BEST}/"] + [f"{SITE}/{g}" for g in GUIDES]
    for sport, data_file, picks_file, template in T.SPORTS:
        if not all(os.path.exists(f) for f in (data_file, picks_file, template)):
            continue
        try:
            games = game_props(sport, T.load(data_file), T.load(picks_file), T.stat_labels(template), now)
            listed = sorted(((p, g) for g in games.values() for p in g["props"] if p["cls"] in ("value", "t25")),
                            key=lambda r: (VERDICT_RANK[r[0]["cls"]], -(r[0]["edge"] or 0) if r[0]["cls"] == "value" else -r[0]["prob"]))
            os.makedirs(BEST, exist_ok=True)
            page, url = best_page(sport, listed, built, now.astimezone(ET).date())
            with open(os.path.join(BEST, sport + ".html"), "w", encoding="utf-8") as f:
                f.write(page)
            urls.append(url)
            best_counts[sport] = len(listed)
            os.makedirs(os.path.join(SHARE, sport), exist_ok=True)
            for p, g in listed:
                k = share_key(p)
                with open(os.path.join(SHARE, sport, k + ".html"), "w", encoding="utf-8") as f:
                    f.write(share_page(sport, p, g))
                expires = (g["start"].astimezone(ET).date() + datetime.timedelta(days=SHARE_DAYS)).isoformat()
                kept.setdefault(sport, {})[k] = max(expires, kept.get(sport, {}).get(k, ""))
            os.makedirs(os.path.join(OUT, sport), exist_ok=True)
            for g in sorted(games.values(), key=lambda g: g["start"]):
                page, url = game_page(sport, g, built)
                path = os.path.join(OUT, sport, page_slug(g) + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(page)
                keep.add(os.path.normpath(path))
                urls.append(url)
                listing.setdefault(sport, []).append((g, f"/{OUT}/{sport}/{page_slug(g)}.html"))
            print(f"  {sport}: {len(games)} game page(s)")
        except Exception as e:     # one bad sport never blanks the others
            print(f"  {sport} game pages: skipped ({e})")
    # games that have started (or dropped off the schedule) lose their page
    for sport in P.SPORT_NAME:
        d = os.path.join(OUT, sport)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                path = os.path.normpath(os.path.join(d, fn))
                if fn.endswith(".html") and path not in keep:
                    os.remove(path)
        d = os.path.join(SHARE, sport)        # share pages go only once expired
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".html") and fn[:-5] not in kept.get(sport, {}):
                    os.remove(os.path.join(d, fn))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(listing, built))
    os.makedirs(BEST, exist_ok=True)
    with open(os.path.join(BEST, "index.html"), "w", encoding="utf-8") as f:
        f.write(best_index(best_counts, built))
    os.makedirs(SHARE, exist_ok=True)
    with open(os.path.join(SHARE, "keys.json"), "w", encoding="utf-8") as f:   # which picks have a share page (app.js reads it too)
        json.dump(kept, f, separators=(",", ":"), sort_keys=True)
    update_sitemap(urls, now.astimezone(ET).date().isoformat())
    print(f"  {OUT}/: {sum(len(v) for v in listing.values())} game page(s), sitemap updated")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"game pages failed ({e})")   # health.py's FAIL_RE shape
        sys.exit(0)

"""
Prop Streak Lab — one static page per player, for search engines and link previews.

The sport boards are single pages that draw everything in the browser, so a search
for "Aaron Judge hits prop" has nothing to land on and a shared link previews as the
site logo. This writes a small, plain page for each of the most-bet players:

  players/<sport>/<name>.html   title, description and share preview for that player;
                                this week's props (model chance, price, edge, verdict),
                                the last 10 games, and a link into the full model
  players/index.html            every player page, by sport
  sitemap.xml                   the player pages added to the one build.py wrote

Up to PER_SPORT players per sport: first the ones on the Polymarket boards lately (by
how many props they had), then the most active players in the game logs. It rebuilds
once a day, after 11 AM ET (players/.built holds the date) so the hourly job doesn't rewrite 240 pages
every hour; `--force` rebuilds now. Standard library only; never fails the deploy.
"""
import datetime
import html
import json
import os
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo

import build_today as T   # sport list, picks loading, stat labels and per-game formulas

SITE = "https://propstreaklab.com"
OUT = "players"
PER_SPORT = 60
REBUILD_HOUR_ET = 11   # the day's markets are up by late morning
ET = ZoneInfo("America/New_York")
SPORT_NAME = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB"}
# The stats a page's game log shows, by sport and position (first = the headline stat).
COLUMNS = {
    "nfl": {"QB": ["pass_yds", "pass_td", "pass_int", "rush_yds"], "RB": ["rush_yds", "rush_att", "rec", "rec_yds"],
            "FB": ["rush_yds", "rec", "rec_yds"], "WR": ["rec_yds", "rec", "tgt", "rec_td"], "TE": ["rec_yds", "rec", "tgt", "rec_td"]},
    "nba": {"*": ["pts", "reb", "ast", "tpm", "min"]},
    "nhl": {"G": ["sv", "toi"], "*": ["pts", "g", "a", "sog", "hit"]},
    "mlb": {"SP": ["k", "outs", "ha", "er"], "RP": ["k", "outs", "ha", "er"], "P": ["k", "outs", "ha", "er"], "*": ["h", "tb", "r", "rbi", "hr"]},
}


def slug(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def cols_for(sport, pos):
    c = COLUMNS[sport]
    return c.get(pos) or c.get("*") or next(iter(c.values()))


def pick_link(sport, p):
    from urllib.parse import quote
    return f"/{sport}.html#player/{quote(str(p['pid']), safe='')}/{p['stat']}/{p['line']}/{p['side']}/{slug(p['player'])}"


FAIR_W = 0.1   # replaced in main() by the weight build_today fits on the graded record


def fair(prob, price):
    return None if price is None else FAIR_W * prob + (1 - FAIR_W) * price


def verdict(prob, price):
    """The site's rules: Value = price 30c+ and model 15+ points better; Skip = overpriced."""
    if price is None:
        return "No price", "none"
    if price >= 0.30 and prob - price >= 0.15:
        return "Value", "value"
    if prob - price <= -0.03:
        return "Skip", "skip"
    return "Fair", "fair"


def choose(sport, db, picks_doc):
    """Up to PER_SPORT players: most props on the boards in the last 21 days, then the
    most games in the latest season of the logs."""
    players = [p for p in db.get("players") or [] if len(p.get("g") or []) >= 5]
    cols = picks_doc["cols"]
    cut = (datetime.date.today() - datetime.timedelta(days=21)).isoformat()
    seen = {}
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") == "live" and (p.get("date") or "") >= cut:
            seen[str(p["pid"])] = seen.get(str(p["pid"]), 0) + 1
    latest = max((g[0] for p in players for g in p["g"]), default=0)
    def activity(p):
        return sum(1 for g in p["g"] if g[0] == latest)
    ranked = sorted(players, key=lambda p: (-seen.get(str(p["id"]), 0), -activity(p), p["n"]))
    return ranked[:PER_SPORT]


def upcoming_props(sport, db, picks_doc, labels, now):
    """pid -> this week's props that still lie ahead (model chance, price, edge), best first."""
    out = {}
    for c in T.upcoming(sport, db, picks_doc, labels, {}, now):
        out.setdefault(c["pid"], []).append(c)
    # T.upcoming keeps only priced props; add unpriced ones too, so a page shows the model's view
    cols = picks_doc["cols"]
    kick = T.nfl_kickoffs(db) if sport == "nfl" else {}
    for row in picks_doc["picks"]:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") is not None or p.get("prob") is None or p.get("price") is not None:
            continue
        start = kick.get(p.get("gid")) if sport == "nfl" else T.parse_start(p.get("start"))
        if start is None or start <= now:
            continue
        out.setdefault(str(p["pid"]), []).append({"pid": str(p["pid"]), "player": p["player"], "stat": p["stat"],
            "statText": labels.get(p["stat"], p["stat"]), "line": p["line"], "side": p.get("side") or "over",
            "prob": T.cap(p["prob"]), "price": None, "edge": None, "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "opp": p.get("opp")})
    for pid, lst in out.items():
        # one line per stat and side: the one closest to a coin flip is the informative one
        best = {}
        for c in lst:
            k = (c["stat"], c["side"])
            if k not in best or abs(c["prob"] - 0.5) < abs(best[k]["prob"] - 0.5):
                best[k] = c
        out[pid] = sorted(best.values(), key=lambda c: (c["edge"] is None, -(c["edge"] or 0), -c["prob"]))[:8]
    return out


CSS = """:root{color-scheme:dark;--green:#22d07f;--gold:#e8b54a;--red:#eb6f7d;--line:#22354f;--muted:#9fb0c6}
*{box-sizing:border-box}
body{margin:0;background:#0a1628;color:#dfe6ef;font-family:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.6;font-size:16px}
a{color:var(--green)}
.wrap{max-width:900px;margin:0 auto;padding:20px 18px 70px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0 16px;border-bottom:1px solid #1c2c46;margin-bottom:24px}
.brand{display:flex;align-items:center;gap:10px;font-family:"Archivo","Inter",sans-serif;font-weight:800;color:#fff;text-decoration:none;font-size:18px}
.crumbs{font-size:13.5px;color:var(--muted)} .crumbs a{color:var(--muted)}
h1{font-family:"Archivo","Inter",sans-serif;font-weight:800;letter-spacing:-.03em;font-size:40px;line-height:1.05;color:#fff;margin:6px 0 6px}
.sub{color:var(--muted);margin:0 0 20px}
h2{font-family:"Archivo","Inter",sans-serif;font-weight:800;letter-spacing:-.02em;font-size:22px;color:#fff;margin:30px 0 10px}
.cta{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;border-radius:999px;background:var(--green);color:#06210b;font-weight:700;text-decoration:none}
.card{background:#0f2038;border:1px solid var(--line);border-radius:16px;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:14.5px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #1c2c46}
th{font-family:"Barlow Condensed",sans-serif;text-transform:uppercase;letter-spacing:.1em;font-size:12.5px;color:var(--muted);font-weight:700}
tr:last-child td{border-bottom:0}
td.n{text-align:right} th.n{text-align:right}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.04em}
.value{background:var(--green);color:#06210b} .fair{background:rgba(134,230,182,.15);color:#86e6b6} .skip{background:rgba(235,111,125,.16);color:#f3a4ae} .none{background:rgba(159,176,198,.15);color:#c9d4e2}
.side{font-weight:700;text-transform:uppercase;font-size:12.5px;letter-spacing:.06em} .over{color:#86e6b6} .under{color:#f3a4ae}
.note{color:var(--muted);font-size:13.5px;margin:10px 2px 0}
.avg{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 6px}
.avg div{background:#0f2038;border:1px solid var(--line);border-radius:14px;padding:10px 14px;min-width:120px}
.avg b{display:block;font-size:24px;font-weight:800;color:#fff;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.avg span{font-family:"Barlow Condensed",sans-serif;text-transform:uppercase;letter-spacing:.1em;font-size:12px;color:var(--muted)}
.scroll{overflow-x:auto}
footer{margin-top:44px;padding-top:16px;border-top:1px solid #1c2c46;color:var(--muted);font-size:13.5px}
footer a{color:var(--muted)}
@media(max-width:620px){h1{font-size:32px}th,td{padding:9px 8px}.props th:nth-child(5),.props td:nth-child(5){display:none}}"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="profile">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{desc}">
<meta property="og:site_name" content="Prop Streak Lab">
<meta property="og:image" content="{site}/icon-512.png">
<meta name="twitter:card" content="summary">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0a1628">
<link rel="stylesheet" href="/fonts.css">
<script src="/halloween.js?v=20261008a"></script>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="brand" href="/"><svg width="26" height="26" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0f2038"></rect><path d="M32,6 Q32,32 54,32 Q32,32 32,58 Q32,32 10,32 Q32,32 32,6 Z" fill="#22d07f"></path></svg>Prop Streak Lab</a>
    <span class="crumbs">{crumbs}</span>
  </div>
"""

FOOT = """  <footer>
    Research, not betting advice. For adults 18+. If gambling stops being fun, call 1-800-522-4700.
    <br><a href="/">Home</a> · <a href="/players/">All players</a> · <a href="/methodology.html">How the model works</a> · <a href="/privacy.html">Privacy</a> · <a href="/terms.html">Terms</a>
  </footer>
</div>
</body>
</html>
"""


def player_page(sport, p, props, getters, labels, built):
    S = SPORT_NAME[sport]
    name, team, pos = p["n"], p.get("t") or "", p.get("p") or ""
    cols = [c for c in cols_for(sport, pos) if c in getters]
    rows = p["g"]
    if sport == "mlb":
        rows = T.mlb_games(rows, cols[0])
    last = rows[-10:]
    def val(g, c):
        try:
            return float(getters[c](g))
        except (TypeError, ValueError, IndexError):
            return None
    main = [labels.get(c, c) for c in cols[:2]]
    title = f"{name} Props: {', '.join(main)} & Model Odds | Prop Streak Lab"
    og_title = f"{name} ({team}) — player props, game log and model chances"
    nxt = props[0] if props else None
    vs = f" vs {nxt['opp']}" if nxt and nxt.get("opp") else ""
    desc = (f"{name} ({team}, {pos}) {S} player props: the last 10 games, recent averages, and the model's chance "
            f"for this week's lines{vs}, priced against Polymarket. Every pick graded in public.")
    url = f"{SITE}/{OUT}/{sport}/{slug(name)}.html"
    out = [HEAD.format(title=esc(title), desc=esc(desc), url=url, og_title=esc(og_title), site=SITE, css=CSS,
                       crumbs=f'<a href="/players/">Players</a> · <a href="/{sport}.html">{S}</a>')]
    out.append(f'  <h1>{esc(name)} player props</h1>\n  <p class="sub">{esc(team)} · {esc(pos)} · {S}'
               + (f" · next: {esc(nxt['opp'])}, {esc(datetime.datetime.fromisoformat(nxt['start'].replace('Z','+00:00')).astimezone(ET).strftime('%a %b %-d, %-I:%M %p ET'))}" if nxt else "")
               + "</p>\n")
    # recent averages
    avg = []
    for c in cols[:4]:
        vs10 = [v for v in (val(g, c) for g in last) if v is not None]
        vs5 = vs10[-5:]
        if vs10:
            avg.append(f'<div><b>{num(sum(vs5)/len(vs5))}</b><span>{esc(labels.get(c, c))} · last 5</span></div>')
    if avg:
        out.append('  <div class="avg">' + "".join(avg) + "</div>\n")
    # this week's props
    out.append("  <h2>This week's props</h2>\n")
    if props:
        trs = []
        for c in props:
            lab, cls = verdict(c["prob"], c["price"])
            px = f"{round(c['price']*100)}¢" if c["price"] is not None else "—"
            fc = fair(c["prob"], c["price"])
            ed = f"{round(fc*100)}%" if fc is not None else "—"
            trs.append(f'<tr><td><a href="{esc(pick_link(sport, c))}">{esc(c["statText"])}</a></td>'
                       f'<td><span class="side {esc(c["side"])}">{esc(c["side"])}</span> {esc(num(float(c["line"])))}</td>'
                       f'<td class="n">{round(c["prob"]*100)}%</td><td class="n">{px}</td><td class="n">{ed}</td>'
                       f'<td><span class="tag {cls}">{lab}</span></td></tr>')
        out.append('  <div class="card scroll"><table class="props"><thead><tr><th>Prop</th><th>Line</th><th class="n">Model</th><th class="n">Price</th>'
                   '<th class="n">Fair</th><th>Call</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table></div>\n")
        out.append(f'  <p class="note">Prices from Polymarket US as of {esc(built)}. <b>Fair</b> is the model blended with the price '
                   f'({round(FAIR_W*100)}% model, {round((1-FAIR_W)*100)}% market — the mix that has predicted graded picks best); '
                   'the market usually knows more than the game logs. Tap a prop for the live price and the full breakdown.</p>\n')
        cta = pick_link(sport, props[0])
    else:
        out.append('  <p class="note">No props posted for this player right now — they appear here once the market lists the next game.</p>\n')
        cta = f"/{sport}.html#player/{p['id']}/{cols[0]}/0.5/over/{slug(name)}" if cols else f"/{sport}.html"
    out.append(f'  <p style="margin:18px 0 0"><a class="cta" href="{esc(cta)}">Open {esc(name)} in the full model →</a></p>\n')
    # last 10 games
    if last:
        head = "".join(f'<th class="n">{esc(labels.get(c, c))}</th>' for c in cols)
        body = []
        for g in reversed(last):
            when = f"Wk {g[1]}" if sport == "nfl" else datetime.date.fromisoformat(g[1]).strftime("%b %-d")
            cells = "".join(f'<td class="n">{num(v) if (v := val(g, c)) is not None else "—"}</td>' for c in cols)
            body.append(f"<tr><td>{esc(when)}{' ' + str(g[0]) if sport == 'nfl' else ''}</td><td>{esc(g[2])}</td>{cells}</tr>")
        out.append(f"  <h2>Last {len(last)} games</h2>\n  <div class=\"card scroll\"><table><thead><tr><th>Game</th><th>Opp</th>{head}</tr></thead><tbody>"
                   + "".join(body) + "</tbody></table></div>\n")
    out.append('  <p class="note">The model weights recent games more, adjusts for the matchup and is calibrated on its own graded record — '
               '<a href="/methodology.html">how it works</a>. Research, not betting advice.</p>\n')
    out.append(FOOT)
    return "".join(out), url


def index_page(entries):
    out = [HEAD.format(title="Player Props by Player — NFL, NBA, NHL, MLB | Prop Streak Lab",
                       desc="Player prop pages for the most-bet NFL, NBA, NHL and MLB players: recent games, averages and the model's chance for this week's lines.",
                       url=f"{SITE}/{OUT}/", og_title="Player props, player by player", site=SITE, css=CSS,
                       crumbs='<a href="/">Home</a>')]
    out.append('  <h1>Players</h1>\n  <p class="sub">The most-bet players on each board — recent games, averages and this week\'s props.</p>\n')
    for sport in ("nfl", "nba", "nhl", "mlb"):
        lst = sorted(entries.get(sport, []), key=lambda e: e[0])
        if not lst:
            continue
        out.append(f"  <h2>{SPORT_NAME[sport]}</h2>\n  <p>" + " · ".join(f'<a href="{esc(u)}">{esc(n)}</a>' for n, u in lst) + "</p>\n")
    out.append(FOOT)
    return "".join(out)


def update_sitemap(urls, day):
    try:
        with open("sitemap.xml", "r", encoding="utf-8") as f:
            sm = f.read()
    except OSError:
        return
    sm = re.sub(r"\s*<url>\s*<loc>[^<]*/players/[^<]*</loc>.*?</url>", "", sm, flags=re.S)
    add = "".join(f"\n  <url><loc>{u}</loc><lastmod>{day}</lastmod><changefreq>daily</changefreq><priority>0.5</priority></url>" for u in urls)
    sm = sm.replace("</urlset>", add + "\n</urlset>")
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sm)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(ET).date().isoformat()
    stamp = os.path.join(OUT, ".built")
    # Rebuild once a day at the first run after REBUILD_HOUR_ET, when the day's markets are
    # up; other runs only re-add the pages to the sitemap.
    done_today = os.path.exists(stamp) and open(stamp).read().strip() == today
    update_sitemap_only = "--force" not in sys.argv and (done_today or now.astimezone(ET).hour < REBUILD_HOUR_ET)
    if update_sitemap_only:
        print("  player pages: " + ("already built today" if done_today else f"rebuild waits until {REBUILD_HOUR_ET}:00 ET"))
    built = now.astimezone(ET).strftime("%b %-d, %-I:%M %p ET")
    global FAIR_W
    try:
        FAIR_W = T.fair_weight([(sp, T.load(pf)) for sp, _, pf, _ in T.SPORTS if os.path.exists(pf)])["w"]
    except Exception as e:   # keep the default
        print(f"  fair weight: default ({e})")
    entries, urls, written, keep = {}, [f"{SITE}/{OUT}/"], 0, set()
    if update_sitemap_only:
        # the pages the day's rebuild wrote, not today's top lists, which drift between runs
        for sport in SPORT_NAME:
            d = os.path.join(OUT, sport)
            if os.path.isdir(d):
                urls += [f"{SITE}/{OUT}/{sport}/{fn}" for fn in sorted(os.listdir(d)) if fn.endswith(".html")]
    for sport, data_file, picks_file, template in T.SPORTS:
        if not all(os.path.exists(f) for f in (data_file, picks_file, template)):
            continue
        try:
            db, picks_doc = T.load(data_file), T.load(picks_file)
            labels, getters = T.stat_labels(template), T.stat_getters(template)
            props = upcoming_props(sport, db, picks_doc, labels, now)
            os.makedirs(os.path.join(OUT, sport), exist_ok=True)
            names = set()
            for p in choose(sport, db, picks_doc):
                s = slug(p["n"])
                if s in names:          # two players, one name: keep the first
                    continue
                names.add(s)
                path = os.path.join(OUT, sport, s + ".html")
                keep.add(path)
                url = f"{SITE}/{OUT}/{sport}/{s}.html"
                entries.setdefault(sport, []).append((p["n"], f"/{OUT}/{sport}/{s}.html"))
                if update_sitemap_only:
                    continue
                urls.append(url)
                page, _ = player_page(sport, p, props.get(str(p["id"]), []), getters, labels, built)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(page)
                written += 1
        except Exception as e:     # one bad sport never blanks the others
            print(f"  player pages {sport}: skipped ({e})")
    if not update_sitemap_only:
        # drop pages for players who fell out of the top lists
        for sport in SPORT_NAME:
            d = os.path.join(OUT, sport)
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    fp = os.path.join(d, fn)
                    if fn.endswith(".html") and fp not in keep:
                        os.remove(fp)
        with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_page(entries))
        with open(stamp, "w") as f:
            f.write(today)
    update_sitemap(urls, today)    # build.py rewrites the sitemap every run, so re-add them every run
    print(f"  player pages: {written} written, {len(urls) - 1} in the sitemap")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"  player pages not rebuilt: {e}")
    sys.exit(0)

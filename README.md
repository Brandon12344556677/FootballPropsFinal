# Prop Streak Lab

An NFL player-prop research site. Pick a player, a stat and a line, and get a
calibrated chance of clearing it — with the raw last 5 / 10 / 15 / 20 hit rates, a
color-coded game log, this week's matchup, injury status, and live Polymarket
prices. Every pick the site makes is recorded before kickoff and graded afterwards,
so the **Past picks** tab shows exactly how well it has done.

Data comes from [nflverse](https://github.com/nflverse) public releases (weekly
player stats, snap counts, schedules, injury reports, rosters). Prices come from Polymarket's
public API.

**It updates itself.** A GitHub Action pulls fresh data every 10 minutes, grades
finished games, records the upcoming picks with their prices, and redeploys the site.

## What's on the page
Every sport page has two views. **Simple**, the default, shows each pick's player, line, chance, both exchanges' prices
and the payout, and last 10 games, one line per list header, and the This week / Player / Past picks tabs. **Pro** adds the
model's edge, opening prices and moves, sorting, each list's full rules and the Tools tab.
After the 18+ check, a new visitor is asked which one they want (anyone who passed the check earlier is asked once). The
Simple | Pro buttons in the header switch views, and the choice is saved in `localStorage` (`psl_view`). `app.js` sets
`<html data-view>`; `app.css` hides `.pro-only` parts and the extra card numbers (`.edgebit`, `.pxmove`, the second
exchange chip) in Simple.

### Research tab
- **Model chance** — the headline number. Instead of "hit 7 of the last 10", the
  model takes the last 30 games, weights recent ones more (half-life 8 games; the
  NBA, NHL and MLB pages use their own, see methodology.html), smooths the values
  into a distribution and reads off the probability of clearing the line. Small samples are shrunk toward 50/50 and every chance comes with an
  80% range. The Last 5/10/15/20 tiles show the plain hit rates for comparison.
- **Game-context adjustment** — before reading off the chance, the distribution is
  scaled for this game: the Vegas implied team points (from the total and spread)
  versus the player's usual, and how much the opponent's defense allows to the
  position versus the league average. The strengths were fitted on the backtest
  with `tools/tune_context.py` and validated on held-out weeks (they're small:
  implied points to the 0.25 power; defense to the 0.75 power for passing, 0.5 for
  receiving, 0.25 for rushing). It also reads the player's role from nflverse
  snap counts: offensive snap share over the last two games against their usual
  (recency-weighted, last eight), to the 0.5 power — a back who just took over the
  job, or a starter who lost it, moves before the box score catches up. On held-out
  weeks that lowered log loss in every stat family (0.5960 -> 0.5924 over 16,993
  cases). For everything but passing stats, each past game is put on the recent
  share by its own snap share, so games already played at the new share aren't
  cut twice (log loss 0.55471 -> 0.55431 on odd weeks, 0.55707 -> 0.55635 on
  even). It's skipped when the injury boost already raises that stat. The tile
  shows the multiplier, and a checkbox turns the adjustment off so you can see the
  raw history.
- **Trades** — a quarterback, back, receiver or tight end who played for a team this
  season and is now on another (traded, released and signed, claimed: found from the
  game log's teams against the current roster, no hand-kept list) leaves his work to
  his old team for good. Each teammate's games with him are rebuilt as if he had sat
  them, handing on half his carries and targets (a quarter of a quarterback's passes and
  carries) by how the group split the work; he's projected from his own log in his new
  team's games. On 45 such moves in 2024-26 that lowered log loss for receiving
  (0.6211 -> 0.6174) and rushing (0.6467 -> 0.6405) props; `tune_trade.py` re-fits it.
  The page shows it as "Volume ▲ ... (now HOU)".
- **This week strip** — opponent, kickoff, Vegas spread and total from the schedule.
- **Badges** — official injury report status, injured reserve / practice squad,
  offseason team changes ("now with X, log from Y"), rookies, small samples.
- **Trend & usage** — last-5 vs last-20 average, current streak against your line,
  target share (or carries / pass attempts) trend.
- **Share** — every prop has its own link (`nfl.html#player/<id>/<stat>/<line>/<side>/<name>`,
  same on every sport page). The address bar follows what you're researching, and the
  🔗 Share button copies it (or opens the phone's share sheet). Opening one loads that
  exact player, prop, line and side.
- **My bets** — tap **+ Track this bet** on a pick's details or the Player tab's verdict card and it's
  listed in the Tools tab, graded from the box score (the game is matched by its exact date — or NFL
  season and week — and opponent), with your record and units at the price you tracked it at. Saved
  on the device only.
- **Bet calculator** — type your Polymarket price to get the multiplier, edge,
  expected value and a quarter-Kelly stake.
- **Parlay builder** — combined model chance, real payout at your prices, and a
  warning when legs come from the same game (they're correlated).
- **Distribution, matchup & splits, game log** — histogram of the last 20 with
  your line, home/away splits, history vs the opponent (auto-selected for this
  week) and the opponent's defense-vs-position rank, blended across this season
  and last.
- **Why this number** — under the tiles, the model shows its work: the
  recency-weighted average and spread, how many standard deviations your line sits
  from it, what the Vegas number, the opponent's defense and the snap share scaled it by, how much
  a thin sample was shrunk toward 50/50, and the calibration temperature — each
  step with the running probability. "Show the math" prints the whole chain on one
  line.
- **Top 25 Surest** — the 25 player props on this week's Polymarket board with the
  highest model chance, regardless of payout, each with the **live Polymarket US
  price** for that side and the model's edge over it.
- **Value spots** — two rules, both stated on the panel itself so readers know what
  qualifies: **(1)** Polymarket gives it at least a **30% chance** (an ask of 30¢ or
  more) and **(2)** the model puts it at least **15 points higher** — so a 30¢ ask
  needs 45%, a 50¢ ask needs 65%, a 70¢ ask needs 85%. Rule 1 is what keeps penny
  longshots off the list: a 6¢ ask against an 11% model chance is a huge percentage
  edge and a bad bet. Everything clearing both is listed, ranked by that edge in
  points — no fixed top 25 — and props still need 6+ effective games of history.
  **Both sides of every market are tested**, so an under appears whenever its ask is
  the cheap one. Both rules are judged on the **live Polymarket US price shown in the
  row** — the price you'd actually pay — so the edge printed is always the edge the
  row qualified on, and a prop leaves the list as soon as its price moves against it.
  This matters more than it sounds: the global book's Under prices are derived from
  `1 - bestBid` on a mostly one-sided NFL book, so they run far too rich and were
  quietly keeping unders off the list. On a live board it roughly doubled the list and
  took it from all-overs to about half unders. `build.py` prices its recorded picks
  the same way (see below), so Past picks and the board agree.
- **Hit streak leaderboard** (Tools tab) — longest active over streaks, now alongside the
  model's chance that the streak extends and the live Polymarket price for it.

The **Polymarket** column on those three boards reads Polymarket US, the exchange
the site's links point to. One request per game prices every prop in it, so the
three boards share a single refresh about once a minute. A price is only ever used
for the **same line** — where Polymarket US lists a prop at a different number (the
hit-streak board uses the site's own seeded lines, so this is common there) the row
says so and shows that price as context, with no edge, since an edge against a
different bet is meaningless.

### Past picks tab
- **Live picks** — everything the auto-updater recorded before kickoff (all modeled
  props, tagged Top 25 Surest / Value where they qualified), graded from the
  box score: hit, miss, push, or DNP.
- **Backtest** — what the model would have said before every past game using
  only earlier games, at the site's auto-seeded line, graded. This is what makes
  the calibration chart meaningful from day one.
- **Filters** — source, list, season, week, team, opponent, position, prop, side,
  result, player search. Summary tiles, a calibration chart ("when it said 80%,
  how often did it hit?"), hit rate by week, a breakdown by recommendation list
  and by prop type, and a sortable table. The live record of each list also shows
  next to its heading on the Research tab.

## Polymarket and Kalshi links
The links to Polymarket and Kalshi are plain links to `https://polymarket.us` and
`https://kalshi.com`, with no referral codes: the "Find this prop on…" buttons in a pick's
details (`REF` in `app.js`) and `guides/polymarket-and-kalshi.html`. (The sport pages' header
buttons for the two exchanges were removed on Oct 15, 2026.) The boards' "Join our Polymarket
group" button links to the Prop Streak Lab squad, also without a referral tag.

---

## What's in this folder

| File | What it does |
|------|--------------|
| `index.html` | The website. Self-contained with the current dataset baked in. |
| `template.html` | The same page with a `__DATA__` placeholder. The builder fills it in. Don't delete it. |
| `build.py` | Downloads nflverse and Polymarket data, rebuilds everything below. Standard library only. |
| `data.json` | The dataset (player game logs, this week's schedule, injuries, defense ranks). |
| `slate.json` | This week's Polymarket player-prop events, used by the board scan. |
| `picks.json` | Every recorded pick, live and backtest, with grades. Read by the Past picks tab. |
| `build_today.py` | Runs after the four builders and writes `today.json` from their picks and season records, plus `live` (every Value and Top 25 pick in today's games, which the home page's "Live now" section follows from ESPN's live box scores, with your tracked bets) and three agent feeds: `fast` (featured props whose price moved 10¢+ in the last hour, from snapshots in `fast_hist.json`; shown on the home page and in the board's pick details), `flags` (featured picks whose player is on an injury report or missing from a posted lineup) and `promo` (today's Value spots against a usual day), both for the team dashboard. Standard library only; never fails the deploy. |
| `today.json` | The home page's cross-sport **Today** feed (the best upcoming value spots, at most 3 per sport up top, each linking to its prop) and the season records on the sport tiles. |
| `botd.py` | **Pick of the Day** for the home page (renamed from "Bet of the Day", its Lock now "Safe Pick", for Meta ad review), run by `build_today.py`: a **Safe Pick** (`lock` in the data) (Polymarket price 90–96¢ and a model chance of 90%+: 135 of 138 graded picks like that hit) and a **Value Shot** (price 30–50¢, so 2x or more, and a model chance of 70–80%), from every sport's upcoming picks. Picked from 11 AM ET, never swapped once posted, "No bet today" if nothing qualifies by 7:30 PM ET. Skips players the news flags (injury status, limited practice, not in a posted lineup) and props with under 6 effective games. Graded from each sport's own picks file; a DNP is a void. |
| `botd.json` | Every Bet of the Day ever posted (that's the record), its results, the running record per slot, and how picks inside each slot's price/chance window have done on the whole graded record (the "picks like this" rate the home page quotes). |
| `post_daily.py` | Once a day, posts yesterday's Value results and today's best value (with links) to Discord and/or Telegram, and emails it (with Bet of the Day) to the daily picks list through Buttondown (`BUTTONDOWN_API_KEY`). Needs the secrets below; does nothing without them. |
| `health.py` | Last in every run (every 10 minutes): reads every step's log for a data source that failed (`skipped (…)`), a builder that crashed, a stale data file or picks stuck ungraded, and keeps `health.json`. A problem that lasts 18 runs in a row (~3 hours) turns the run red, so GitHub emails you (then at most once a day while it lasts). The site still deploys either way. |
| `news.py` | Pre-game news in **test mode**, used by the NFL, NBA and MLB builders: ESPN injury reports, MLB's posted lineups, and Open-Meteo forecasts at outdoor NFL stadiums and MLB parks. It's recorded on each pending pick (`nw`) with `p2`, the chance the pick would have with the news at the strength the backtest found. It changes no chance or list. Each build logs `news test: ...` lines, including how `p2` compares with the live chance on graded picks. A feed that can't be reached records nothing. |
| `test_news.py` | Unit tests for `news.py` and the builders' `news_test` steps, on payloads shaped like the real feeds: `python -m unittest test_news`. |
| `test_botd.py` | Unit tests for `botd.py`: the slot rules, the news filter, posting at 11 AM ET without ever swapping, closing empty days, grading and the record: `python -m unittest test_botd`. |
| `methodology.html` | "How the model works" — the public write-up of the model, the matchup adjustments, calibration, the list rules and how picks are graded. Linked from every footer and the trust line under each hero. |
| `build_players.py` → `players/` | One static page per most-bet player (up to 60 per sport): title, description and share preview, this week's props with model chance, price, edge and call, the last 10 games, and a link into the full model; plus `players/index.html`. Rebuilt once a day (`--force` rebuilds now); the pages are re-added to `sitemap.xml` every run, since `build.py` rewrites it. |
| `app.js` / `app.css` | Shared look and behavior for every page: fonts (Archivo headlines, Inter body and numbers), colors, icons (Lucide, swapped in for emoji at runtime), the verdict card, pick-details sheet, one-time 18+ check, explainers, share links, ticker (no page shows it since Oct 13, 2026) and trust line. |
| `fonts/` | Self-hosted fonts (Barlow Condensed for labels, Archivo, Inter), with their SIL Open Font License files. |
| `LICENSE-lucide-icons.txt` | License notice for the Lucide icon shapes bundled in `app.js`. |
| `.github/workflows/update.yml` | The update job: two update passes 10 minutes apart per run, and each run starts the next when it ends, so the site updates about every 10 minutes even when GitHub's scheduler stalls. The 20-minute schedule restarts the chain if a run is ever lost. |
| `watchdog.py` | Its own workflow (`.github/workflows/watchdog.yml`), every 30 minutes: checks the live site from the outside. Is the update job still running and passing, is the data fresh, does every main page and data file load, and does each board open in headless Chrome without script errors? A problem opens one GitHub issue ("Site watchdog: …"), updated as it changes and closed once everything passes; the team dashboard's health panel shows it too. |
| `dashboard_check.py` | Runs after `watchdog.py` every 30 minutes: the team dashboard loads with no script errors and has every part its script uses, `team/stats.enc` and `team/edges.enc` open with the team password and are fresh, and `today.json` still has the fields its panels read. Problems open one "Team dashboard" GitHub issue. |
| Affiliate links | Private affiliate program (no public page): affiliates the team recruits share `propstreaklab.com/?ref=<code>` and are paid $0.20 per new viewer (a first-time browser that keeps the site on screen 20 seconds), every two weeks once they reach $10. `app.js` counts these as `ref/<code>/new` events; `team_stats.py` and the dashboard's Affiliates tab total them per pay period and week. Every arrival through a link also sends `ref/<code>/stay/<mark>` as the visit passes 0s, 10s, 20s, 1, 3, 10 and 30 minutes on screen, which the tab turns into each affiliate's average time on site. |
| `site_checks.py` | Its own workflow (`.github/workflows/site_checks.yml`), once a day: every sitemap page loads and has a title, description, heading and canonical link (and no stray noindex); robots.txt allows crawling; links on the hand-written pages work. Problems open one "Site checks" GitHub issue. |
| `edge_report.py` | Every update pass (~10 minutes, rewritten only when the numbers change): grades every recorded pick with a market price as a flat $1 bet for a fixed set of strategies (each list, NHL Value since the regular season, the Pick of the Day's Value Shot and Safe Pick from `botd.json`, what was losing) plus the team's private strategies, kept encrypted in `rules.enc` on the `team-data` branch and edited from the dashboard (`team/rules.js`), with a likely range and the last 7 days, into `team/edges.enc` for the team dashboard. |
| `parlay.py` | Every pass, team only: three a day from 11 AM ET (never sharing a player), 2-4 leg parlays from the NHL priced on Polymarket, that the model puts at 35-55% and that pay at least 3x the stake, frozen once made and graded from its legs' picks, into `team/parlays.enc` (encrypted) for the dashboard's Model parlays panel and the edge tracker. Never on the public site. In that panel, `team/parlaylive.js` follows today's legs live (each leg's number against its line, the game clock, whether the parlay is still alive) from ESPN's public box scores every 30 seconds; display only, the record stays parlay.py's grading. |
| `update_pass.sh` | One update pass: every builder, the health check, commit + push. Only the NFL build is fatal. |
| `tests/` | Unit tests for the model, market parsing, grading, and a check that the JavaScript model matches the Python one. |
| `tune_trade.py` | Re-fits the trade hand-off (`TRADE_LAMBDA` in `build.py`) on every mid-season team change of the last seasons. |
| `tools/tune_context.py` | Re-fits the game-context adjustment strengths on the backtest. Run it when a season of new data has accumulated. |

## How the pipeline works

1. `build.py` downloads the last three seasons of weekly stats and snap counts, the
   schedule, the current season's injury reports and roster.
2. It builds `data.json`: per-player game logs (regular season + playoffs), current
   team from the roster, injury status, this week's games with kickoff and Vegas
   lines, and blended defense-vs-position ranks.
3. It grades any pending live picks whose game is final **and** whose box score is
   in the stats file.
4. It fetches this week's Polymarket board, prices every prop off **Polymarket US**
   where that exchange lists the same prop at the same line (one request per game;
   the global book is the fallback), models them, assigns the Top 25 Surest / Value
   tags, and upserts them into `picks.json` (a pick is refreshed on every run until
   kickoff, then frozen and graded). Picks are keyed by side, so the opposite side of
   a market is recorded too when it is a value candidate. The slate dates Sunday- and
   Monday-night games a day later than the schedule does, so the schedule date is
   tried first when building the Polymarket US slug.
5. It regenerates the walk-forward backtest, refuses to publish if the dataset
   shrank suspiciously, and writes `index.html`.

The workflow runs **daily at 09:00 UTC** (5 AM EDT / 4 AM EST) — it grades any
finished games, refreshes this week's pending picks, and freezes each pick at
kickoff. Run it any time from the Actions tab with "Run workflow".

## Running it yourself
```
python build.py                                  # rebuilds everything
python -m unittest discover -s tests -v          # unit tests
node tests/model_sync.mjs                        # JS model == Python model
python -m http.server 8000                       # then open http://localhost:8000
```
The board scan and the Past picks tab fetch `slate.json` / `picks.json`, so open
the site through a web server (or the hosted URL) rather than as a file. The
Polymarket API also has to be reachable from where you run the build; if it
isn't, the build keeps the previous `slate.json` and skips recording new live
picks but still updates stats, grades, and the backtest.

## Daily Discord / Telegram post (optional)
The update job can post once a day, after 11 AM ET: yesterday's Value spots results
(wins and losses) and today's best value, each linking straight to its prop. Add either or both as **Settings → Secrets and variables → Actions →
New repository secret**:
- **Discord:** in your server, *Server settings → Integrations → Webhooks → New
  webhook*, pick the channel, *Copy Webhook URL*, save it as `DISCORD_WEBHOOK_URL`.
- **Telegram:** message @BotFather, send `/newbot`, save the token as
  `TELEGRAM_BOT_TOKEN`. Add the bot to your channel as an admin, and save the
  channel's `@username` (or its numeric id) as `TELEGRAM_CHAT_ID`.

To test right away: **Actions → Update NFL data → Run workflow**, set *post* to `1`.
`python post_daily.py --dry-run` prints the message without sending it.

## One-time GitHub setup
1. Create a **public** repository and upload everything in this folder, including
   the `.github/workflows/update.yml` file (create it via *Add file → Create new
   file* if the folder doesn't drag in).
2. **Settings → Pages**: deploy from branch `main`, folder `/ (root)`.
3. **Settings → Actions → General → Workflow permissions**: *Read and write*.
4. **Actions** tab → enable workflows → run "Update NFL data" once.

## Honest limits
- Backward-looking. The model knows the game log, the Vegas line, the opponent's
  defense, snap counts and the injury report, but not weather, a coaching change,
  or who else is out on the team. The backtest lines are self-seeded from history, so the
  edge the adjustments show there is larger than against a real market, which
  already prices the line and the matchup.
- Rookies and returning players appear in search right away but have no chance
  until their first box score.
- Polymarket's global book can differ from Polymarket US. Always check your price.
- Calibration is measured, not promised. Look at the Past picks tab before trusting
  a number.
- Research aid, **not betting advice**.

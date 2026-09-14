# Prop Streak Lab

An NFL player-prop research site. Pick a player, a stat and a line, and get a
calibrated chance of clearing it — with the raw last 5 / 10 / 15 / 20 hit rates, a
color-coded game log, this week's matchup, injury status, and live Polymarket
prices. Every pick the site makes is recorded before kickoff and graded afterwards,
so the **Past picks** tab shows exactly how well it has done.

Data comes from [nflverse](https://github.com/nflverse) public releases (weekly
player stats, schedules, injury reports, rosters). Prices come from Polymarket's
public API.

**It updates itself.** A GitHub Action pulls fresh data every morning at 5 AM ET
during the season, grades finished games, records this week's picks, and redeploys
the site.

## What's on the page

### Research tab
- **Model chance** — the headline number. Instead of "hit 7 of the last 10", the
  model takes the last 20 games, weights recent ones more (half-life 6 games),
  smooths the values into a distribution and reads off the probability of clearing
  the line. Small samples are shrunk toward 50/50 and every chance comes with an
  80% range. The Last 5/10/15/20 tiles show the plain hit rates for comparison.
- **Game-context adjustment** — before reading off the chance, the distribution is
  scaled for this game: the Vegas implied team points (from the total and spread)
  versus the player's usual, and how much the opponent's defense allows to the
  position versus the league average. The strengths were fitted on the backtest
  with `tools/tune_context.py` and validated on held-out weeks (they're small:
  implied points to the 0.25 power; defense to the 0.75 power for passing, 0.5 for
  receiving, 0.25 for rushing). The tile shows the multiplier, and a checkbox
  turns the adjustment off so you can see the raw history.
- **This week strip** — opponent, kickoff, Vegas spread and total from the schedule.
- **Badges** — official injury report status, injured reserve / practice squad,
  offseason team changes ("now with X, log from Y"), rookies, small samples.
- **Trend & usage** — last-5 vs last-20 average, current streak against your line,
  target share (or carries / pass attempts) trend.
- **Bet calculator** — type your Polymarket price to get the multiplier, edge,
  expected value and a quarter-Kelly stake.
- **Parlay builder** — combined model chance, real payout at your prices, and a
  warning when legs come from the same game (they're correlated).
- **Distribution, matchup & splits, game log** — histogram of the last 20 with
  your line, home/away splits, history vs the opponent (auto-selected for this
  week) and the opponent's defense-vs-position rank, blended across this season
  and last.
- **25 Guaranteed** — the 25 player props on this week's Polymarket board with the
  highest model chance, regardless of payout.
- **Value spots** — the top 25 props where even the low end of the model's range
  beats the ask, ranked by that edge.

### Past picks tab
- **Live picks** — everything the auto-updater recorded before kickoff (all modeled
  props, tagged 25 Guaranteed / Value where they qualified), graded from the
  box score: hit, miss, push, or DNP.
- **Backtest** — what the model would have said before every past game using
  only earlier games, at the site's auto-seeded line, graded. This is what makes
  the calibration chart meaningful from day one.
- **Filters** — source, list, season, week, team, opponent, position, prop, side,
  result, player search. Summary tiles, a calibration chart ("when it said 80%,
  how often did it hit?"), hit rate by week, a breakdown by recommendation list
  and by prop type, and a sortable table. The live record of each list also shows
  next to its heading on the Research tab.

## Your Polymarket referral link
Near the top of the `<script>` in `template.html` (and `index.html`):
```js
const REFERRAL = { url: "", text: "..." };
```
Put your referral link in `url`. Leave it `""` to hide the banner.

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
| `.github/workflows/update.yml` | The scheduled job: tests, build, commit. |
| `tests/` | Unit tests for the model, market parsing, grading, and a check that the JavaScript model matches the Python one. |
| `tools/tune_context.py` | Re-fits the game-context adjustment strengths on the backtest. Run it when a season of new data has accumulated. |

## How the pipeline works

1. `build.py` downloads the last three seasons of weekly stats, the schedule, the
   current season's injury reports and roster.
2. It builds `data.json`: per-player game logs (regular season + playoffs), current
   team from the roster, injury status, this week's games with kickoff and Vegas
   lines, and blended defense-vs-position ranks.
3. It grades any pending live picks whose game is final **and** whose box score is
   in the stats file.
4. It fetches this week's Polymarket board, models every prop, assigns the
   25 Guaranteed / Value tags, and upserts them into `picks.json` (a pick is
   refreshed on every run until kickoff, then frozen and graded).
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

## One-time GitHub setup
1. Create a **public** repository and upload everything in this folder, including
   the `.github/workflows/update.yml` file (create it via *Add file → Create new
   file* if the folder doesn't drag in).
2. **Settings → Pages**: deploy from branch `main`, folder `/ (root)`.
3. **Settings → Actions → General → Workflow permissions**: *Read and write*.
4. **Actions** tab → enable workflows → run "Update NFL data" once.

## Honest limits
- Backward-looking. The model knows the game log, the Vegas line, the opponent's
  defense and the injury report, but not weather, a coaching change, or who else
  is out on the team. The backtest lines are self-seeded from history, so the
  edge the adjustments show there is larger than against a real market, which
  already prices the line and the matchup.
- Rookies and returning players appear in search right away but have no chance
  until their first box score.
- Polymarket's global book can differ from Polymarket US. Always check your price.
- Calibration is measured, not promised. Look at the Past picks tab before trusting
  a number.
- Research aid, **not betting advice**.

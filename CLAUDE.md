# Prop Streak Lab

Player-prop research site (NFL, NBA, NHL, MLB, plus tennis match markets) on GitHub Pages. A GitHub Action
rebuilds the data and pages every ~10 minutes and pushes straight to `main`.
README.md has the full feature tour; this file is the working rules.

## Layout

- `build.py` (NFL, the only fatal step), `build_nba.py`, `build_nhl.py`, `build_mlb.py`:
  download data, grade picks, price props off Polymarket/Kalshi, write the sport's
  JSON files and bake them into its page. Standard library only — don't add packages.
- `build_tennis.py` (since Nov 2, 2026): tennis, ATP and WTA singles. Neither exchange lists tennis player props, so it prices match
  markets: match winner (Polymarket US + Kalshi), set winner, exact score, game spread, total games (Kalshi). Elo per player
  (overall + per surface) over ESPN results cached in `tennis_results.json`, played out game by game for every scoreline
  (`HOLD`/`TAU`/`OVER_SHIFT` fit on 2026: `python build_tennis.py backtest`). Its `MODEL` block is Python only: the page shows the
  recorded chances and never recomputes them. Value = ATP match winners only, both players 30+ matches (WTA lost in a Kalshi price backtest, Nov 2, 2026), 30-80c, model 8-20 points over; Top 25 = up to 25 at 90%+ with a $25+ price (the NHL/MLB rule),
  any market. A retirement grades the match winner and voids the rest. `build_today.NOT_FEATURED` keeps tennis off every featured
  feed (home picks, Pick of the Day, 3 Picks, posts, parlays, pooled calibration) and `build_players.py`/`build_games.py` skip it,
  until it has a track record.
- `build_today.py` → `today.json` (home feed), runs `botd.py` → `botd.json` (Pick of the Day; called Bet of the Day before Oct 12, 2026).
- `build_players.py` → `players/`, `build_games.py` → `games/` (one page per upcoming game), `best/` (today's best props
  per sport) and `p/` (link-preview pages for shared picks, kept 14 days after the game), `health.py` → `health.json`,
  `post_daily.py` (Discord/Telegram, and the daily picks email via Buttondown: `BUTTONDOWN_API_KEY`, sign-up form on the
  home page shown once `NEWSLETTER` is set in index.html), `watchdog.py` (own workflow, started by every update run, so about every 20 min, with a 30-min schedule as backup: checks the live site and keeps one
  "Site watchdog" GitHub issue open while something is broken, and restarts the update chain when no update run has started in 30+ minutes (`restart_chain`, via `start_run.py`); the team dashboard reads it). `build_today.py` also writes `search.json` (home page player search).
- `edge_report.py` → `team/edges.enc` (every pass: which strategies make money, encrypted like the stats);
  `site_checks.py` (own daily workflow: search basics, keeps a "Site checks" GitHub issue).
  Polymarket and Kalshi links are plain links (no referral codes) since Oct 13, 2026.
  `dashboard_check.py` (in watchdog.yml, with each watchdog check: the team dashboard's page, encrypted numbers, edge tracker; "Team dashboard" issue).
  Private edge-tracker strategies live encrypted in `rules.enc` on `team-data` (the dashboard's Secret methods tab, `team/rules.js`; `team/methodtoday.js` lists today's picks that fit each one, followed live through `parlaylive.js`; the rules and each one's record from the edge tracker on every past pick that fits, with its record since the day it was added shown apart; read by `edge_report.py` load_private and rule_test, which also filter on list, model edge, positions, a price drop since the first price, and a start day); never put them back in the public code.
  `parlay.py` → `team/parlays.enc` (team only, never public): three parlays a day from 11 AM ET (no shared players; legs only from `TEST_PARLAY_SPORTS`, NHL only for now; Polymarket prices only; only prop types Polymarket US lets you parlay, read live by `combos.py`: no NHL assists), each 35-55% by the model, one per payout band (3-3.5x, 3.5-4x, 4-4.5x),
  plus separate NBA and NFL tracks with the same rules, each with its own three a day and record (`team/parlays_nba.enc`, `team/parlays_nfl.enc`) (all three in the dashboard's Parlays tab, with a summary of every set and each payout band; each set also has its own edge-tracker row),
  plus Parlay of the Day (`team/parlay_potd.enc`, the dashboard's Parlay of the Day tab and its own edge-tracker row): one a day from any sport, same legs, timing and grading, paying 3x+ and over 50% by the model, never an NHL assists under (`POTD_RULES`; NBA unders allowed again since Oct 28, 2026, with a tradable Polymarket price and $25+ like every leg), posted on Instagram as the series Parlay Payday (day 1 Oct 28, 2026, earlier days dropped; the tab shows `payday_script`'s script and caption), never a player from that day's 3 Picks of the Day (they come first: `tpod_players`; `tpod.py` skips the parlay's players too), with a Lock button like 3 Picks of the Day's (`potd_locks.enc` on team-data, read by `parlay.load_locks`: a locked day is never remade, filled or closed, and a changed parlay is put back before its games start),
  frozen once made, graded from the legs' picks; the edge tracker's "parlays" row and the dashboard's Model parlays panel read it; `team/parlaylive.js` tracks today's legs live in that panel from ESPN box scores (browser-side, display only).
  `spreads.py` → `team/spreads.enc` (team only, encrypted): a private test of full-game spreads on Polymarket US in every sport. A
  team-strength model per sport (margin ratings for NBA/NFL, scoring rates for NHL/MLB, calibrated on the previous season:
  `python spreads.py backtest`) fit on ESPN final scores cached in `spread_scores.json`; a pick when the model is 5-15 points above
  a 35-65c price with $25+ offered, one a game, frozen, graded from the final; the dashboard's Spreads tab and the edge tracker's spreads rows; `team/spreadlive.js`
  shows today's picks' live ESPN scores and whether each is covering in that tab (browser-side, display only).
  `arbs.py` → `team/arbs.enc` (team only, encrypted): Polymarket US / Kalshi arbitrage on player props. The NFL/NBA/NHL/MLB builders
  pass the prices they already read to `arbs.note` (both sides, paired on player, stat, exact line and game date; saved to `.arbs/`, gitignored),
  then `arbs.py` reads both live books of each pair quoted under $1.00 and keeps those returning 1%+ after taker fees (`FEE`: Polymarket US 0.05,
  Kalshi 0.07 × p × (1 − p)) with $25+ a side at those prices; the dashboard's Arbitrage tab. Not a list of picks, so not in the edge tracker.
  `tpod.py` → `team/tpod.enc` (team only, encrypted; build_today.py runs it after Pick of the Day): 3 Picks of the Day for TikTok from the
  private methods (rules.enc), each judged by its record in the pick's sport (30+ picks there, in profit): 35-75c on Polymarket with $25+ offered on that side (NBA unders were not tradable there Oct 22-28, 2026), model 60%+ and 5+ points over the price, no news flag or price drop, three games, at most two of a kind unless a third proven pick would otherwise lose its slot to a fill-in;
  no parlay (the fun parlay was dropped Oct 23, 2026; older days keep theirs in the file, unread). Frozen once made, graded like Pick of the Day; a script and caption that never name a method. After filming, the tab's Lock button saves the day's picks to `tpod_locks.enc` on `team-data` (needs a GitHub token, as in Expenses); `tpod.load_locks` reads it through the API each run, and a locked day is never remade or filled (picks changed after filming are put back). Dashboard tab 3 Picks of the Day (each pick shows how to say the player's name: `team/pronounce.js`, from Wikipedia in the browser, with a Hear it voice; today's picks followed live through `parlaylive.js`).
  A pending pick whose Polymarket US market is no longer listed loses its Polymarket price (`depth.drop_vanished`; the builders record every listed prop per game).
  A Polymarket US side marked not tradable (every NBA player prop's under, Oct 22-28, 2026) gets no Polymarket price (`depth.tradable_sides`/`side_ok`).
  `depth.guard` holds a 30c+ price jump until a second run confirms it (the `pj` pick column).
- `team_stats.py` → `team/stats.enc`: GoatCounter visitor totals (and traffic spikes), encrypted with the
  `TEAM_DASH_PASSWORD` secret, for the password-protected team dashboard `team/index.html`
  (hand-written, noindex, not in the sitemap). Totals only — no IPs or per-visitor data.
  The dashboard is split into tabs (Overview, Audience, Sign-ups, Picks & edges, Parlays, Parlay of the Day, Spreads, Arbitrage, Secret methods, 3 Picks of the Day, Social, Sponsors, Affiliates, Expenses: each panel has
  `data-view`). `app.js` feeds it anonymous GoatCounter events, `time/<range>`, `click/<what>/<page>`, `view/<n>`, `visitor/new|returning`
  (the visitor's n-th page today: page views and unique visitors) and `ref/<code>/visit|new`; their labels are mirrored in `team_stats.py`
  (TIME_RANGES, CLICK_RE, VIEW_RE, REF_RE) and `team/index.html`. `view/<n>` and `ref/` are disclosed in privacy.html and cookies.html.
- Affiliate program (private: no public page; the team recruits affiliates and they sign an agreement): links are `/?ref=<code>`. `app.js` sends `ref/<code>/visit` on
  arrival and `ref/<code>/new` once a never-seen browser has had the site on screen 20 seconds; every affiliate arrival also sends `ref/<code>/stay/<mark>` as the visit passes each time mark (STAY_MARKS in `team_stats.py`; the tab's
  tracking table shows average time on site); affiliates are paid $0.20 per
  `new`, every 2 weeks, $10 minimum (rolls over), $50 cap, 15 a week to avoid a warning. The dashboard's Affiliates tab
  (`AFF_*` constants) does the math, keeps the team's affiliate list (code, name, email, phone, warnings sent) in
  `affiliates.enc` on the `team-data` branch via `expenses.js`'s `window.psaTeamData`, and flags last week's under-15s
  with the warning email. Keep the dashboard constants, the warning email text and the signed agreement in sync.
- `team/ads.js`: the dashboard's Meta ads panel. Draws feed and story ads on a canvas from the public `today.json`
  (`calib`, `record`, `picks`, `streaks`) and writes the Ads Manager text; `team/ads/` holds the example PNGs.
  Its Video size hands off to `team/ads_video.js`: each ad kind's `script()` is what the owner films, and the 15s Reel
  (their clip, the story image, an optional screen recording, captions, end card) is recorded in the browser. Clips are never uploaded.
  Ad copy avoids "bet", "lock" and exchange names and carries an 18+ line (Meta restricts gambling ads).
- `tiktok_post.py` (own workflow, `tiktok.yml`, daily after 11 ET): three short videos and one photo carousel, uploaded to the
  TikTok inbox as drafts (the owner adds a sound and posts). `plan_day()` picks the videos from the sports playing today,
  rotating sport × angle (value gap, hit streak, season record); `team/render.html` draws them in headless Chrome with
  ads.js's cards (same copy rules), ffmpeg makes the slideshows. Carousel JPEGs are committed to `tiktok/<day>/` because
  TikTok pulls photos from our verified URL prefix; `tiktok/posted.json` feeds the dashboard's Social tab.
  `tiktok_auth.py` + `tiktok/callback.html`: the one-time sign-in that gives the `TIKTOK_REFRESH_TOKEN` secret.
- Shared helpers: `news.py`, `holds.py`, `kalshi.py`, `depth.py`.
- `update_pass.sh` is one full pass; `.github/workflows/update.yml` runs it twice per run, and each run starts
  the next one when it ends (the 20-minute schedule is only a backup: GitHub's scheduler stalls). `start_run.py` starts the
  next run and the watchdog check and confirms each one really started (a request GitHub accepts can still end in "startup_failure"), asking again if not.
- `app.js` / `app.css`: shared look and behavior for every page. Sport pages have a Simple (default) and a Pro view:
  `<html data-view>`, chosen after the 18+ check or with the header toggle. Anything new that only a regular needs
  (extra numbers, sort/filter controls, long notes) goes in Pro: class `pro-only`, or a rule in the Simple/Pro block of `app.css`.

## Generated files — never edit by hand

The bot overwrites these on every pass, so hand edits are lost and cause merge conflicts:

- `nfl.html` ← `template.html`; `nba.html` ← `nba_template.html`; `nhl.html` ← `nhl_template.html`;
  `mlb.html` ← `mlb_template.html`; `tennis.html` ← `tennis_template.html`. Edit the template (and the builder), never the output page.
- `data.json`, `slate.json`, `picks.json`, `weekly.json`, `*_picks.json`, `*_stats.json`,
  `nba.json`, `nhl.json`, `mlb.json`, `tennis.json`, `tennis_results.json`, `today.json`, `botd.json`, `health.json`, `top_cache.json`,
  `sitemap.xml`, `robots.txt`, `players/`, `games/`, `best/`, `p/`, `team/stats.enc`, `team/edges.enc`, `team/parlays.enc`, `team/parlays_nba.enc`, `team/parlays_nfl.enc`, `team/parlay_potd.enc`, `team/spreads.enc`, `team/arbs.enc`, `team/tpod.enc`, `spread_scores.json`, `fast_hist.json`, `*_picks_recent.json`, `search.json`,
  `tiktok/<day>/` and `tiktok/posted.json` (the TikTok workflow; `tiktok/callback.html` is hand-written).

`index.html` (home page), `methodology.html`, `guides/`, and the legal pages are hand-written and safe to edit.

## Rules that bite

- **The model is mirrored.** The block marked `MODEL` in each builder is copied line-for-line
  into its template's `// ==== MODEL` block. Change both together. `model_sync.mjs` checks the NFL pair.
- **Cache-busting.** When you change `app.js` or `app.css`, bump the `?v=YYYYMMDDx` query on every
  page and template that loads them (`index.html`, all `*_template.html`/`template.html`, the
  hand-written pages), or browsers keep the old file.
- **Keep the public explanation in sync.** A change to a rule users see (list cutoffs, lock
  times, Bet of the Day windows, grading) also updates `methodology.html` and any on-page note
  in `app.js`/the templates, and the README if it describes it.
- **The edge tracker follows every list change.** Adding, removing or changing a list, a list rule or what gets
  recommended (Value, Top 25, Pick of the Day, a new sport) also updates `edge_report.py` STRATEGIES in
  the same PR, so the team dashboard's edge tracker shows it. The owner treats it as the most important number.
- **Never rewrite recorded picks** (past entries in the picks files or `botd.json`) except
  through a builder's grading/void logic. The track record is the product.
- **Non-NFL steps must not break the deploy.** Only `build.py` may exit non-zero in `update_pass.sh`.

## Tests

```
python -m unittest discover -p "test_*.py"   # also writes model_cases.json
node model_sync.mjs                          # JS model in template.html == Python model
python -m http.server 8000                   # preview; pages fetch JSON, so don't open as files
```

Add or update a `test_*.py` case for any change to model, grading, locking, or list rules.

## Workflow

- Work on a branch and open a PR into `main`. `main` is protected: every PR needs
  Brandon's approval (`.github/CODEOWNERS`), and direct pushes are refused except for the
  update bot, which pushes with the `DEPLOY_KEY` deploy key.
- Before pushing, `git pull --rebase origin main` — `main` gets an "Auto-update data" commit
  every ~10 minutes. Don't commit regenerated data files in a PR.
- PR titles describe the user-visible change in plain words, with specifics
  (e.g. "Lock picks 30 minutes before the start (was 20)"). The body says what changed
  where and how it was tested.

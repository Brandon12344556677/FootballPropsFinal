# Prop Streak Lab

Player-prop research site (NFL, NBA, NHL, MLB) on GitHub Pages. A GitHub Action
rebuilds the data and pages every ~10 minutes and pushes straight to `main`.
README.md has the full feature tour; this file is the working rules.

## Layout

- `build.py` (NFL, the only fatal step), `build_nba.py`, `build_nhl.py`, `build_mlb.py`:
  download data, grade picks, price props off Polymarket/Kalshi, write the sport's
  JSON files and bake them into its page. Standard library only — don't add packages.
- `build_today.py` → `today.json` (home feed), runs `botd.py` → `botd.json` (Pick of the Day; called Bet of the Day before Oct 12, 2026).
- `build_players.py` → `players/`, `build_games.py` → `games/` (one page per upcoming game), `best/` (today's best props
  per sport) and `p/` (link-preview pages for shared picks, kept 14 days after the game), `health.py` → `health.json`,
  `post_daily.py` (Discord/Telegram, and the daily picks email via Buttondown: `BUTTONDOWN_API_KEY`, sign-up form on the
  home page shown once `NEWSLETTER` is set in index.html), `watchdog.py` (own workflow, every 30 min: checks the live site and keeps one
  "Site watchdog" GitHub issue open while something is broken; the team dashboard reads it). `build_today.py` also writes `search.json` (home page player search).
- `edge_report.py` → `team/edges.enc` (every pass: which strategies make money, encrypted like the stats);
  `site_checks.py` (own daily workflow: search basics, keeps a "Site checks" GitHub issue).
  Polymarket and Kalshi links are plain links (no referral codes) since Oct 13, 2026.
  `dashboard_check.py` (in watchdog.yml, every 30 min: the team dashboard's page, encrypted numbers, edge tracker; "Team dashboard" issue).
  Private edge-tracker strategies live encrypted in `rules.enc` on `team-data` (dashboard panel `team/rules.js`, read by `edge_report.py` load_private); never put them back in the public code.
  `parlay.py` → `team/parlays.enc` (team only, never public): three parlays a day from 11 AM ET (no shared players; legs only from `TEST_PARLAY_SPORTS`, NHL only for now; Polymarket prices only), each 35-55% by the model, one per payout band (3-3.5x, 3.5-4x, 4-4.5x),
  frozen once made, graded from the legs' picks; the edge tracker's "parlays" row and the dashboard's Model parlays panel read it; `team/parlaylive.js` tracks today's legs live in that panel from ESPN box scores (browser-side, display only).
  `depth.guard` holds a 30c+ price jump until a second run confirms it (the `pj` pick column).
- `team_stats.py` → `team/stats.enc`: GoatCounter visitor totals (and traffic spikes), encrypted with the
  `TEAM_DASH_PASSWORD` secret, for the password-protected team dashboard `team/index.html`
  (hand-written, noindex, not in the sitemap). Totals only — no IPs or per-visitor data.
  The dashboard is split into tabs (Overview, Audience, Sign-ups, Picks & edges, Social, Sponsors, Affiliates: each panel has
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
  Ad copy avoids "bet", "lock" and exchange names and carries an 18+ line (Meta restricts gambling ads).
- Shared helpers: `news.py`, `holds.py`, `kalshi.py`, `depth.py`.
- `update_pass.sh` is one full pass; `.github/workflows/update.yml` runs it twice per run, and each run starts
  the next one when it ends (the 20-minute schedule is only a backup: GitHub's scheduler stalls).
- `app.js` / `app.css`: shared look and behavior for every page. Sport pages have a Simple (default) and a Pro view:
  `<html data-view>`, chosen after the 18+ check or with the header toggle. Anything new that only a regular needs
  (extra numbers, sort/filter controls, long notes) goes in Pro: class `pro-only`, or a rule in the Simple/Pro block of `app.css`.

## Generated files — never edit by hand

The bot overwrites these on every pass, so hand edits are lost and cause merge conflicts:

- `nfl.html` ← `template.html`; `nba.html` ← `nba_template.html`; `nhl.html` ← `nhl_template.html`;
  `mlb.html` ← `mlb_template.html`. Edit the template (and the builder), never the output page.
- `data.json`, `slate.json`, `picks.json`, `weekly.json`, `*_picks.json`, `*_stats.json`,
  `nba.json`, `nhl.json`, `mlb.json`, `today.json`, `botd.json`, `health.json`, `top_cache.json`,
  `sitemap.xml`, `robots.txt`, `players/`, `games/`, `best/`, `p/`, `team/stats.enc`, `team/edges.enc`, `team/parlays.enc`, `fast_hist.json`, `*_picks_recent.json`, `search.json`.

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

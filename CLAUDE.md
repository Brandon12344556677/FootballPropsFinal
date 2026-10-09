# Prop Streak Lab

Player-prop research site (NFL, NBA, NHL, MLB) on GitHub Pages. A GitHub Action
rebuilds the data and pages every ~10 minutes and pushes straight to `main`.
README.md has the full feature tour; this file is the working rules.

## Layout

- `build.py` (NFL, the only fatal step), `build_nba.py`, `build_nhl.py`, `build_mlb.py`:
  download data, grade picks, price props off Polymarket/Kalshi, write the sport's
  JSON files and bake them into its page. Standard library only — don't add packages.
- `build_today.py` → `today.json` (home feed), runs `botd.py` → `botd.json` (Bet of the Day).
- `build_players.py` → `players/`, `health.py` → `health.json`, `post_daily.py` (Discord/Telegram).
- Shared helpers: `news.py`, `holds.py`, `kalshi.py`, `depth.py`.
- `update_pass.sh` is one full pass; `.github/workflows/update.yml` runs it twice per scheduled run.
- `app.js` / `app.css`: shared look and behavior for every page.

## Generated files — never edit by hand

The bot overwrites these on every pass, so hand edits are lost and cause merge conflicts:

- `nfl.html` ← `template.html`; `nba.html` ← `nba_template.html`; `nhl.html` ← `nhl_template.html`;
  `mlb.html` ← `mlb_template.html`. Edit the template (and the builder), never the output page.
- `data.json`, `slate.json`, `picks.json`, `weekly.json`, `*_picks.json`, `*_stats.json`,
  `nba.json`, `nhl.json`, `mlb.json`, `today.json`, `botd.json`, `health.json`, `top_cache.json`,
  `sitemap.xml`, `robots.txt`, `players/`.

`index.html` (home page), `methodology.html`, and the legal pages are hand-written and safe to edit.

## Rules that bite

- **The model is mirrored.** The block marked `MODEL` in each builder is copied line-for-line
  into its template's `// ==== MODEL` block. Change both together. `model_sync.mjs` checks the NFL pair.
- **Cache-busting.** When you change `app.js` or `app.css`, bump the `?v=YYYYMMDDx` query on every
  page and template that loads them (`index.html`, all `*_template.html`/`template.html`, the
  hand-written pages), or browsers keep the old file.
- **Keep the public explanation in sync.** A change to a rule users see (list cutoffs, lock
  times, Bet of the Day windows, grading) also updates `methodology.html` and any on-page note
  in `app.js`/the templates, and the README if it describes it.
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

- Work on a branch and open a PR into `main`; teammates review before merging.
- Before pushing, `git pull --rebase origin main` — `main` gets an "Auto-update data" commit
  every ~10 minutes. Don't commit regenerated data files in a PR.
- PR titles describe the user-visible change in plain words, with specifics
  (e.g. "Lock picks 30 minutes before the start (was 20)"). The body says what changed
  where and how it was tested.

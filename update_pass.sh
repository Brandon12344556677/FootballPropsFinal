#!/usr/bin/env bash
# One full update pass: every builder, the health check, then commit + push.
# .github/workflows/update.yml runs this twice per scheduled run, 10 minutes apart.
#
# Each script's output is also saved to $RUNNER_TEMP/<script>.log for the health check;
# pipefail keeps each script's own exit code. Only the NFL build is fatal: a failure in
# any other step never blocks the deploy.
set -uo pipefail
LOGDIR="${RUNNER_TEMP:-/tmp}"

python build.py 2>&1 | tee "$LOGDIR/build.log" || exit 1

timeout 6m python build_nba.py 2>&1 | tee "$LOGDIR/build_nba.log" || echo "NBA build failed — skipping NBA files this run"
timeout 6m python build_nhl.py 2>&1 | tee "$LOGDIR/build_nhl.log" || echo "NHL build failed — skipping NHL files this run"
timeout 7m python build_mlb.py 2>&1 | tee "$LOGDIR/build_mlb.log" || echo "MLB build failed — skipping MLB files this run"

# The home page's Today feed and Bet of the Day.
python build_today.py 2>&1 | tee "$LOGDIR/build_today.log" || echo "today.json not rebuilt this run"

# One page per most-bet player, for search engines: rebuilt once a day, sitemap every run.
python build_players.py 2>&1 | tee "$LOGDIR/build_players.log" || echo "player pages not rebuilt this run"

# Once a day (first run after 11 AM ET): yesterday's Value results + today's best value,
# to whichever Discord/Telegram secrets are set. With none set, it does nothing.
python post_daily.py 2>&1 | tee "$LOGDIR/post_daily.log" || echo "daily post skipped this run"

# Reads those logs: any data source that failed, a builder that crashed, a data file gone
# stale, picks stuck ungraded. Records it in health.json (committed below, so it remembers
# across passes) and flags every open problem on the run's page.
python health.py "$LOGDIR" || true

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add nfl.html data.json slate.json picks.json weekly.json sitemap.xml robots.txt
git add -A players 2>/dev/null || true
for f in nba.html nba.json nba_stats.json nba_picks.json \
         nhl.html nhl.json nhl_stats.json nhl_picks.json \
         mlb.html mlb.json mlb_stats.json mlb_picks.json today.json botd.json posted.json top_cache.json health.json; do
  git add "$f" 2>/dev/null || true
done
if git diff --cached --quiet; then
  echo "No changes."
else
  git commit -m "Auto-update data ($(date -u +'%Y-%m-%d %H:%M UTC'))"
  # Push with rebase-retry so two runs finishing close together can't fail on a
  # non-fast-forward.
  for i in 1 2 3 4 5; do
    if git push; then
      echo "pushed"; break
    fi
    echo "push rejected, rebasing (attempt $i)…"
    git pull --rebase --autostash origin main || true
    sleep 3
  done
fi

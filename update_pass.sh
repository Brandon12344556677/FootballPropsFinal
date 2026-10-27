#!/usr/bin/env bash
# One full update pass: every builder, the health check, then commit + push.
# .github/workflows/update.yml runs this twice per scheduled run, 10 minutes apart.
#
# Each script's output is also saved to $RUNNER_TEMP/<script>.log for the health check;
# pipefail keeps each script's own exit code. Only the NFL build is fatal: a failure in
# any other step never blocks the deploy. Every step has a time limit: one stuck network
# call once froze a run for over 30 minutes (Oct 14, 2026), and a timeout costs one step, not hours.
set -uo pipefail
LOGDIR="${RUNNER_TEMP:-/tmp}"

timeout 8m python build.py 2>&1 | tee "$LOGDIR/build.log" || exit 1

timeout 6m python build_nba.py 2>&1 | tee "$LOGDIR/build_nba.log" || echo "NBA build failed — skipping NBA files this run"
timeout 6m python build_nhl.py 2>&1 | tee "$LOGDIR/build_nhl.log" || echo "NHL build failed — skipping NHL files this run"
timeout 7m python build_mlb.py 2>&1 | tee "$LOGDIR/build_mlb.log" || echo "MLB build failed — skipping MLB files this run"

# The home page's Today feed and Bet of the Day.
timeout 3m python build_today.py 2>&1 | tee "$LOGDIR/build_today.log" || echo "today.json not rebuilt this run"

# One page per most-bet player, for search engines: rebuilt once a day, sitemap every run.
timeout 3m python build_players.py 2>&1 | tee "$LOGDIR/build_players.log" || echo "player pages not rebuilt this run"

# One page per upcoming game (games/), every run; adds them to the sitemap.
timeout 2m python build_games.py 2>&1 | tee "$LOGDIR/build_games.log" || echo "game pages not rebuilt this run"

# Once a day (first run after 11 AM ET): yesterday's Value results + today's best value,
# to whichever Discord/Telegram secrets are set. With none set, it does nothing.
timeout 3m python post_daily.py 2>&1 | tee "$LOGDIR/post_daily.log" || echo "daily post skipped this run"

# Visitor totals for the password-protected team dashboard at /team/ (encrypted; needs the
# GOATCOUNTER_TOKEN and TEAM_DASH_PASSWORD secrets, does nothing without them).
timeout 2m python team_stats.py 2>&1 | tee "$LOGDIR/team_stats.log" || echo "team stats not refreshed this run"

# Team only: the daily model parlays, NHL (team/parlays.enc), NBA (team/parlays_nba.enc) and NFL (team/parlays_nfl.enc), and Parlay of the Day (team/parlay_potd.enc), encrypted; rewritten only on a change.
timeout 2m python parlay.py 2>&1 | tee "$LOGDIR/parlay.log" || echo "model parlay not refreshed this run"

# Team only: the private game-spread test (team/spreads.enc, encrypted; spread_scores.json holds the public final scores it fits on).
timeout 3m python spreads.py 2>&1 | tee "$LOGDIR/spreads.log" || echo "spread test not refreshed this run"

# Every pass: which strategies are making money (team/edges.enc, encrypted like the stats; rewritten only on a change).
timeout 2m python edge_report.py 2>&1 | tee "$LOGDIR/edge_report.log" || echo "edge report not refreshed this run"

# Reads those logs: any data source that failed, a builder that crashed, a data file gone
# stale, picks stuck ungraded. Records it in health.json (committed below, so it remembers
# across passes) and flags every open problem on the run's page.
timeout 2m python health.py "$LOGDIR" || true

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add nfl.html data.json slate.json picks.json weekly.json sitemap.xml robots.txt
git add -A players 2>/dev/null || true
git add -A games best p 2>/dev/null || true
for f in nba.html nba.json nba_stats.json nba_picks.json \
         nhl.html nhl.json nhl_stats.json nhl_picks.json \
         mlb.html mlb.json mlb_stats.json mlb_picks.json today.json botd.json posted.json top_cache.json health.json fast_hist.json \
         team/stats.enc team/edges.enc team/parlays.enc team/parlays_nba.enc team/parlays_nfl.enc team/parlay_potd.enc team/spreads.enc spread_scores.json team/tpod.enc nba_picks_recent.json nhl_picks_recent.json mlb_picks_recent.json search.json; do
  git add "$f" 2>/dev/null || true
done
if git diff --cached --quiet; then
  echo "No changes."
else
  git commit -m "Auto-update data ($(date -u +'%Y-%m-%d %H:%M UTC'))"
  # Push with rebase-retry so two runs finishing close together can't fail on a
  # non-fast-forward.
  for i in 1 2 3 4 5; do
    if timeout 2m git push; then
      echo "pushed"; break
    fi
    echo "push rejected, rebasing (attempt $i)…"
    timeout 2m git pull --rebase --autostash origin main || true
    sleep 3
  done
fi

#!/bin/bash
# run_and_push.sh - hourly data pipeline
# 1. scrape politician roster + parse to latest.json
# 2. discover + fetch + parse all active elections
# 3. aggregate elections into single feed for dashboard
# 4. commit data files, pull remote front-end edits, push

set -e
cd /home/matthew/bfth-dashboard
source .venv/bin/activate

echo "[cron] $(date -u +%Y-%m-%d-%H%M) starting pipeline"

# ─── Politician pipeline ───
echo "[cron] politician fetch..."
python3 scraper/fetch.py

echo "[cron] politician parse..."
python3 scraper/parse.py

# ─── Election pipeline ───
echo "[cron] elections discover + fetch + parse..."
python3 scraper/elections.py

echo "[cron] aggregate elections..."
python3 scraper/aggregate_elections.py

# ─── Sanity check ───
PLAYER_COUNT=$(python3 -c "import json; print(json.load(open('data/players/latest.json')).get('count', 0))" 2>/dev/null || echo 0)
if [ "$PLAYER_COUNT" -lt 50 ]; then
    echo "[cron] ABORT: only $PLAYER_COUNT players parsed (expected 60+)"
    git checkout data/players/latest.json 2>/dev/null || true
    exit 1
fi
echo "[cron] $PLAYER_COUNT players parsed"

ELECTION_COUNT=$(python3 -c "import json; print(json.load(open('data/elections.json')).get('total', 0))" 2>/dev/null || echo 0)
if [ "$ELECTION_COUNT" -lt 100 ]; then
    echo "[cron] WARN: only $ELECTION_COUNT elections in aggregate (expected 120+)"
fi
echo "[cron] $ELECTION_COUNT elections aggregated"

# ─── Stage data ───
git add data/players/latest.json
git add data/players/history.jsonl 2>/dev/null || true
git add data/elections/
git add data/elections.json
git add data/elections_history.jsonl 2>/dev/null || true

if git diff --cached --quiet; then
    echo "[cron] no data changes to commit"
    exit 0
fi

# ─── Commit ───
TURN=$(date -u +"%Y-%m-%d-%H%M")
git commit -m "turn: $TURN roster + elections [skip ci]"
echo "[cron] committed: turn $TURN"

# ─── Pull front-end edits from GitHub before pushing ───
# (in case any HTML was edited via GitHub web UI since last cron)
if git pull --rebase origin main; then
    echo "[cron] pulled remote changes"
else
    echo "[cron] pull failed, aborting push"
    exit 1
fi

# ─── Push ───
git push origin main
echo "[cron] pushed to origin/main"
echo "[cron] $(date -u +%Y-%m-%d-%H%M) done"
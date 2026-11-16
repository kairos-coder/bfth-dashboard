#!/bin/bash
# run_and_push.sh - hourly data pipeline
# Full sequence:
#   1. refresh GOP roster URL list (warn-only — stale roster beats dead pipeline)
#   2. fetch + parse politicians       → data/players/latest.json
#   3. build sparklines                → data/players/sparklines.json
#   4. fetch + parse corporations      → data/corporations/latest.json
#   5. fetch + parse congress          → data/congress.json
#   6. fetch + parse nations           → data/nations.json + data/nations/*.json
#   7. discover + fetch + parse elections → data/elections.json
#   8. commit + pull --rebase + push
#
# Exit codes:
#   0 = clean run (with or without data changes)
#   1 = critical pipeline step failed (fetch/parse politicians), nothing pushed

set -euo pipefail

REPO="/home/matthew/bfth-dashboard"
cd "$REPO"
source .venv/bin/activate

TURN=$(date -u +"%Y-%m-%d-%H%M")
START_TS=$(date -u +%s)

echo "[cron] $TURN starting pipeline"

# ─────────────────────────────────────────────────────────────
# 0. Preflight
# ─────────────────────────────────────────────────────────────
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "[cron] FATAL: $REPO is not a git repository" >&2
    exit 1
fi

if ! git diff --quiet HEAD --; then
    echo "[cron] WARN: working tree has uncommitted changes; cron will commit them with the turn"
fi

# ─────────────────────────────────────────────────────────────
# Helper: run a step, time it, return non-zero on failure
# ─────────────────────────────────────────────────────────────
run_step() {
    local label="$1"; shift
    echo "[cron] $label..."
    local t0
    t0=$(date -u +%s)
    if ! "$@"; then
        local dt=$(( $(date -u +%s) - t0 ))
        echo "[cron] FAILED: $label (${dt}s)" >&2
        return 1
    fi
    local dt=$(( $(date -u +%s) - t0 ))
    echo "[cron] ok: $label (${dt}s)"
}

# ─────────────────────────────────────────────────────────────
# 1. Roster refresh — WARN-ONLY, do not abort the whole pipeline
# ─────────────────────────────────────────────────────────────
# A stale gop.txt is much better than a dead pipeline. Transient timeouts
# on BFTH should not cost us the entire turn's data.
if ! run_step "refresh GOP roster" python3 scraper/fetch_gop_roster.py; then
    echo "[cron] WARN: gop.txt not refreshed; using previous roster" >&2
    if [ ! -s scraper/urls/gop.txt ]; then
        echo "[cron] FATAL: gop.txt is missing or empty, and refresh failed" >&2
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────
# 2. Politician pipeline — CRITICAL
# ─────────────────────────────────────────────────────────────
# Snapshot latest.json so we can restore on bad parse
cp data/players/latest.json /tmp/bfth-latest-backup.json 2>/dev/null || true

if ! run_step "fetch politicians" python3 scraper/fetch.py; then
    echo "[cron] ABORT: fetch.py failed" >&2
    exit 1
fi

if ! run_step "parse politicians" python3 scraper/parse.py; then
    echo "[cron] ABORT: parse.py failed" >&2
    exit 1
fi

# Sanity check: did we actually get enough players?
PLAYER_COUNT=$(python3 -c "import json; print(json.load(open('data/players/latest.json')).get('count', 0))" 2>/dev/null || echo 0)
if [ "$PLAYER_COUNT" -lt 50 ]; then
    echo "[cron] ABORT: only $PLAYER_COUNT players parsed (expected 60+)"
    if [ -f /tmp/bfth-latest-backup.json ]; then
        cp /tmp/bfth-latest-backup.json data/players/latest.json
        echo "[cron] restored previous latest.json"
    fi
    exit 1
fi
echo "[cron] $PLAYER_COUNT players parsed"

# ─────────────────────────────────────────────────────────────
# 3. Sparklines — WARN-ONLY
# ─────────────────────────────────────────────────────────────
# Depends on archives written by parse.py above. If it fails, roster page
# falls back to no sparklines (graceful).
if ! run_step "build sparklines" python3 scraper/build_sparklines.py; then
    echo "[cron] WARN: sparklines failed; roster falls back to no charts" >&2
fi
SPARK_COUNT=$(python3 -c "import json; d=json.load(open('data/players/sparklines.json')); print(len(d.get('players',{})))" 2>/dev/null || echo 0)
echo "[cron] $SPARK_COUNT players in sparklines.json"

# ─────────────────────────────────────────────────────────────
# 4. Corporations — WARN-ONLY
# ─────────────────────────────────────────────────────────────
if ! run_step "fetch+parse corporations" python3 scraper/corporations.py; then
    echo "[cron] WARN: corporations failed; skipping Market Desk refresh this turn" >&2
fi

# ─────────────────────────────────────────────────────────────
# 5. Congress — WARN-ONLY
# ─────────────────────────────────────────────────────────────
if ! run_step "fetch+parse congress" python3 scraper/congress.py; then
    echo "[cron] WARN: congress failed; skipping Congress refresh this turn" >&2
fi

# ─────────────────────────────────────────────────────────────
# 6. Nations — WARN-ONLY
# ─────────────────────────────────────────────────────────────
if ! run_step "fetch+parse nations" python3 scraper/nations.py; then
    echo "[cron] WARN: nations failed; skipping Nations refresh this turn" >&2
fi

# ─────────────────────────────────────────────────────────────
# 7. Elections — WARN-ONLY
# ─────────────────────────────────────────────────────────────
if ! run_step "fetch+parse elections" python3 scraper/elections.py; then
    echo "[cron] WARN: elections fetch/parse failed" >&2
fi

if ! run_step "aggregate elections" python3 scraper/aggregate_elections.py; then
    echo "[cron] WARN: elections aggregate failed" >&2
fi

ELECTION_COUNT=$(python3 -c "import json; print(json.load(open('data/elections.json')).get('total', 0))" 2>/dev/null || echo 0)
if [ "$ELECTION_COUNT" -lt 100 ]; then
    echo "[cron] WARN: only $ELECTION_COUNT elections in aggregate (expected 120+ when active)"
fi
echo "[cron] $ELECTION_COUNT elections aggregated"

# ─────────────────────────────────────────────────────────────
# 8. Stage everything that could possibly be written
# ─────────────────────────────────────────────────────────────
# Every file below has caused at least one abort in the last 48h by
# being left unstaged at the pull --rebase step. Stage them all.
git add data/players/latest.json 2>/dev/null || true
git add data/players/history.jsonl 2>/dev/null || true
git add data/players/sparklines.json 2>/dev/null || true
git add data/players/2026-*.json 2>/dev/null || true            # timestamped archives
git add data/latest.json 2>/dev/null || true                    # fetch.py intermediary
git add data/corporations/ 2>/dev/null || true
git add data/congress.json 2>/dev/null || true
git add data/nations.json 2>/dev/null || true
git add data/nations/ 2>/dev/null || true
git add data/elections/ 2>/dev/null || true
git add data/elections.json 2>/dev/null || true
git add data/elections_history.jsonl 2>/dev/null || true
git add scraper/urls/gop.txt 2>/dev/null || true                # roster changes tracked in git
git add scraper/fetch-report.txt 2>/dev/null || true            # fetch.py log
git add '*.html' 2>/dev/null || true                            # page edits between runs

if git diff --cached --quiet; then
    echo "[cron] no data changes to commit"
    TOTAL_DT=$(( $(date -u +%s) - START_TS ))
    echo "[cron] $TURN done (no-op, ${TOTAL_DT}s)"
    exit 0
fi

# ─────────────────────────────────────────────────────────────
# 9. Commit
# ─────────────────────────────────────────────────────────────
git commit -m "turn: $TURN roster + corps + congress + nations + elections [skip ci]"
echo "[cron] committed: turn $TURN"

# ─────────────────────────────────────────────────────────────
# 10. Pull + push
# ─────────────────────────────────────────────────────────────
if ! git pull --rebase origin main; then
    echo "[cron] ABORT: pull --rebase failed; local commit exists but not pushed" >&2
    echo "[cron] run 'git status' and 'git rebase --abort' or resolve manually" >&2
    exit 1
fi
echo "[cron] pulled remote changes"

if ! git push origin main; then
    echo "[cron] ABORT: push failed; local commit exists but not pushed" >&2
    exit 1
fi
echo "[cron] pushed to origin/main"

TOTAL_DT=$(( $(date -u +%s) - START_TS ))
echo "[cron] $TURN done (${TOTAL_DT}s)"
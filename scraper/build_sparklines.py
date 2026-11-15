#!/usr/bin/env python3
"""
Read the last N archive files in data/players/ and emit per-player time series
into data/players/sparklines.json for the roster page to render.
"""
import json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
ARCHIVE_DIR = ROOT / "data" / "players"
OUT_FILE = ARCHIVE_DIR / "sparklines.json"

WINDOW_DAYS = 7
METRICS = {
    "np": "national_prestige",
    "cf": "campaign_funds",
    "nw": "total_net_worth",
    "lc": "lc_income_hr",
}

def list_archives():
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}\.json$")
    files = [f.name for f in ARCHIVE_DIR.iterdir() if pat.match(f.name)]
    files.sort()
    return files

def pick_window(archives, days):
    """Return archive filenames within the last N days (or fewer if not available)."""
    if not archives:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H")
    return [f for f in archives if f[:13] >= cutoff_str]

def load_archive(name):
    with open(ARCHIVE_DIR / name) as f:
        return json.load(f).get("players", [])

def main():
    archives = list_archives()
    window = pick_window(archives, WINDOW_DAYS)

    # If no archives exist, emit empty shell
    if not window:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": WINDOW_DAYS,
            "archives_used": [],
            "players": {},
        }
        OUT_FILE.write_text(json.dumps(out, indent=2))
        print(f"[sparklines] no archives in window; wrote empty shell")
        return

    # Snapshot latest (may not be an archive itself)
    try:
        with open(ARCHIVE_DIR / "latest.json") as f:
            latest_players = json.load(f).get("players", [])
    except FileNotFoundError:
        latest_players = []

    # Build per-player time series from archive list
    series = {}  # id -> {name, state, np: [], cf: [], ...}
    per_archive_players = []
    for name in window:
        per_archive_players.append((name, load_archive(name)))

    # Union of all player IDs seen in any archive
    seen_ids = set()
    for _, players in per_archive_players:
        for p in players:
            if p.get("id"):
                seen_ids.add(str(p["id"]))

    for pid in seen_ids:
        entry = {"name": None, "state": None}
        for key in METRICS:
            entry[key] = []

        for name, players in per_archive_players:
            match = next((p for p in players if str(p.get("id")) == pid), None)
            if not match:
                continue
            entry["name"] = entry["name"] or match.get("name")
            entry["state"] = entry["state"] or match.get("state")
            for short, full in METRICS.items():
                v = match.get(full)
                entry[short].append(v if v is not None else None)

        # Attach the current value from latest.json if present (so the last
        # point is today, not yesterday's archive)
        current = next((p for p in latest_players if str(p.get("id")) == pid), None)
        if current:
            entry["name"] = current.get("name") or entry["name"]
            entry["state"] = current.get("state") or entry["state"]
            for short, full in METRICS.items():
                v = current.get(full)
                entry[short].append(v if v is not None else None)

        series[pid] = entry

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": WINDOW_DAYS,
        "archives_used": window,
        "players": series,
    }
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"[sparklines] wrote {len(series)} player series "
          f"from {len(window)} archives (last {WINDOW_DAYS} days)")

if __name__ == "__main__":
    main()
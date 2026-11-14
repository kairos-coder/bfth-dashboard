#!/usr/bin/env python3
"""
deltas.py - compute overnight movers against the most recent prior-day snapshot.

Baseline = newest archive in data/players/ whose date is strictly before today's
date. Multiple same-day runs don't stack — one snapshot per day is enough.

Writes data/players/deltas.json for the front-end ticker.

Usage:
    python3 scraper/deltas.py
    python3 scraper/deltas.py --date 2026-11-13    # override "today"
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PLAYERS_DIR = REPO_ROOT / "data" / "players"
LATEST = PLAYERS_DIR / "latest.json"
OUT_FILE = PLAYERS_DIR / "deltas.json"

# archive filenames look like 2026-11-14T00.json
ARCHIVE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T\d{2}\.json$")


def load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"  WARN: could not load {path.name}: {e}")
        return None


def find_prior_day_archive(today_str):
    """
    Return the newest archive from a date strictly before `today_str`
    (format: YYYY-MM-DD). If multiple archives exist on the chosen day,
    picks the latest hour of that day.
    """
    candidates = []
    for f in PLAYERS_DIR.glob("*.json"):
        m = ARCHIVE_RE.match(f.name)
        if not m:
            continue
        date_part = m.group(1)
        if date_part < today_str:  # strictly before today
            candidates.append((date_part, f.name, f))
    if not candidates:
        return None
    # sort by (date, filename) — filename includes the hour, so lexicographic works
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[-1][2]


def pick_mover(prev, cur):
    """Return the biggest-magnitude stat change as {stat, delta}."""
    d_np = (cur.get("national_prestige") or 0) - (prev.get("national_prestige") or 0)
    d_cs = (cur.get("campaign_strength") or 0) - (prev.get("campaign_strength") or 0)
    d_cf = (cur.get("campaign_funds") or 0) - (prev.get("campaign_funds") or 0)
    d_nw = (cur.get("total_net_worth") or 0) - (prev.get("total_net_worth") or 0)

    # scale so different stat ranges are comparable
    candidates = [
        {"stat": "NP", "delta": d_np, "mag": abs(d_np)},
        {"stat": "CS", "delta": d_cs, "mag": abs(d_cs) * 8},
        {"stat": "CF", "delta": d_cf, "mag": abs(d_cf) / 250_000},
        {"stat": "NW", "delta": d_nw, "mag": abs(d_nw) / 5_000_000},
    ]
    candidates = [c for c in candidates if c["mag"] > 0.001]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["mag"], reverse=True)
    return candidates[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default=None,
                    help="override today's date (YYYY-MM-DD); default = current UTC date")
    args = ap.parse_args()

    if args.date:
        today_str = args.date
    else:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not LATEST.exists():
        print(f"[deltas] no {LATEST.name} — nothing to compare")
        return

    cur_data = load_json(LATEST)
    if not cur_data:
        return

    prev_path = find_prior_day_archive(today_str)
    if not prev_path:
        print(f"[deltas] no archive from a day before {today_str} — writing empty")
        OUT_FILE.write_text(json.dumps({
            "generated_at": cur_data.get("generated_at"),
            "baseline_at": None,
            "baseline_file": None,
            "today": today_str,
            "movers": [],
            "note": f"no snapshot found prior to {today_str}",
        }, indent=2))
        return

    prev_data = load_json(prev_path)
    if not prev_data:
        return

    print(f"[deltas] today: {today_str}")
    print(f"[deltas] baseline: {prev_path.name}  (from {prev_data.get('generated_at')})")
    print(f"[deltas] current:  latest.json  (from {cur_data.get('generated_at')})")

    prev_by_id = {str(p.get("id")): p for p in prev_data.get("players", []) if p.get("id")}

    movers = []
    for p in cur_data.get("players", []):
        pid = str(p.get("id"))
        prev_p = prev_by_id.get(pid)
        if not prev_p:
            continue
        top = pick_mover(prev_p, p)
        if not top:
            continue
        movers.append({
            "id": pid,
            "name": p.get("name"),
            "stat": top["stat"],
            "delta": top["delta"],
        })

    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
    movers = movers[:40]

    OUT_FILE.write_text(json.dumps({
        "generated_at": cur_data.get("generated_at"),
        "baseline_at": prev_data.get("generated_at"),
        "baseline_file": prev_path.name,
        "today": today_str,
        "movers": movers,
    }, indent=2))

    print(f"[deltas] wrote {OUT_FILE.relative_to(REPO_ROOT)} ({len(movers)} movers)")
    for m in movers[:5]:
        sign = "+" if m["delta"] > 0 else ""
        print(f"  {m['name']:30} {m['stat']}  {sign}{m['delta']:.2f}")


if __name__ == "__main__":
    main()
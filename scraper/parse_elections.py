#!/usr/bin/env python3
"""
parse_elections.py - parse election HTML into structured JSON.

Reads scraper/raw/elections/*.html, writes
data/elections/<eid>/election.json with:
  - metadata (state, type, stance, end date)
  - candidates (name, party, final_pct, spent, ads, rallies, stance, np, cs, sr)
  - polls (per-poll percentages)

Merges with existing data so live scrapes accumulate.

Usage:
    python3 scraper/parse_elections.py
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
RAW_DIR = HERE / "raw" / "elections"
DATA_DIR = REPO_ROOT / "data" / "elections"


def parse_election(html, eid):
    soup = BeautifulSoup(html, "html.parser")

    # --- election meta ---
    state_name = None
    state_el = soup.find("p", string=re.compile(r"Elections$"))
    if state_el:
        state_name = state_el.get_text(strip=True).replace(" Elections", "")

    # stance from meta tags (bfth-stance or data attributes)
    # The wiki says state stance is used; need to find where it's rendered
    # TODO: inspect one page to confirm selector

    # --- candidates ---
    candidates = []
    # TODO: candidates appear in the "Candidates" card with
    # name, party, result %, seats, CS, SR, money spent, ads, rallies
    # Need real selectors

    # --- final result ---
    # TODO: extract winner % from the election page

    # --- polls (from pollingHistory JS) ---
    polls = []
    m = re.search(r'var pollingHistory = (\[.*?\]);', html, re.DOTALL)
    if m:
        try:
            history = json.loads(m.group(1))
            # Each entry: {"candidate_id": ..., "name": ..., "party_color": ..., "history": [{"date": ..., "polling": ...}, ...]}
            for cand in history:
                for i, h in enumerate(cand.get("history", [])):
                    if i >= len(polls):
                        polls.append({"index": i, "results": {}})
                    polls[i]["results"][cand["name"]] = h.get("polling")
        except Exception as e:
            print(f"  WARN: pollingHistory parse failed: {e}")

    return {
        "election_id": eid,
        "state": state_name,
        "candidates": candidates,
        "polls": polls,
        "polls_count": len(polls),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_election(eid, new_data):
    """Merge new parse into existing election.json (append new polls only)."""
    e_dir = DATA_DIR / eid
    e_dir.mkdir(parents=True, exist_ok=True)
    f = e_dir / "election.json"

    if f.exists():
        old = json.loads(f.read_text())
        old_poll_count = len(old.get("polls", []))
        new_poll_count = len(new_data.get("polls", []))
        print(f"  election {eid}: {old_poll_count} → {new_poll_count} polls")
        if new_poll_count <= old_poll_count:
            # No new data; but update metadata if it changed
            pass
        # Keep the larger poll set
        if old_poll_count > new_poll_count:
            new_data["polls"] = old["polls"]
        # Preserve any candidate data we had that the new parse lacks
        if not new_data.get("candidates") and old.get("candidates"):
            new_data["candidates"] = old["candidates"]

    f.write_text(json.dumps(new_data, indent=2))
    print(f"  wrote {f.relative_to(REPO_ROOT)}")


def main():
    if not RAW_DIR.exists():
        sys.exit(f"no {RAW_DIR} - run fetch_elections.py first")

    files = sorted(RAW_DIR.glob("*.html"))
    if not files:
        sys.exit("no election HTML files found")

    print(f"[parse] {len(files)} election HTML files")
    for path in files:
        eid = path.stem
        try:
            data = parse_election(path.read_text(encoding="utf-8"), eid)
            merge_election(eid, data)
        except Exception as e:
            print(f"  ERROR {eid}: {e}")


if __name__ == "__main__":
    main()
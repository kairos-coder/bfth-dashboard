#!/usr/bin/env python3
"""
aggregate_elections.py - consolidate per-election JSON into one feed for the dashboard.

Reads every data/elections/<eid>/election.json and writes:
  data/elections.json          ← one object with all elections, indexed by eid
  data/elections_history.jsonl ← append-only, one summary line per election per run

Usage:
    python3 scraper/aggregate_elections.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = REPO_ROOT / "data" / "elections"
OUT_JSON = REPO_ROOT / "data" / "elections.json"
OUT_HIST = REPO_ROOT / "data" / "elections_history.jsonl"


def summarize_election(d):
    """Compact per-race summary for the aggregate feed."""
    candidates = d.get("candidates", []) or []
    polls = d.get("polls", []) or []
    polls_count = d.get("polls_count", len(polls))

    # sort candidates by predicted_final desc, then final_pct desc
    def key(c):
        pf = c.get("predicted_final")
        fp = c.get("final_pct")
        return (pf if pf is not None else -1, fp if fp is not None else -1)
    candidates = sorted(candidates, key=key, reverse=True)

    leader = candidates[0] if candidates else None
    runner_up = candidates[1] if len(candidates) > 1 else None

    def clean_candidate(c):
        if not c:
            return None
        return {
            "name": c.get("name"),
            "politician_id": c.get("politician_id"),
            "final_pct": c.get("final_pct"),
            "predicted_final": c.get("predicted_final"),
            "polls_used": c.get("polls_used", 0),
        }

    return {
        "election_id": d.get("election_id"),
        "state_id": d.get("state_id"),
        "type": d.get("type"),
        "label": d.get("label"),
        "url": d.get("url"),
        "overview_lean": d.get("overview_lean"),
        "polls_count": polls_count,
        "polls_source": d.get("polls_source"),
        "candidates": [clean_candidate(c) for c in candidates],
        "leader": clean_candidate(leader),
        "runner_up": clean_candidate(runner_up),
        "parsed_at": d.get("parsed_at"),
    }


def main():
    if not DATA_DIR.exists():
        sys.exit(f"no {DATA_DIR}")

    elections = []
    for p in sorted(DATA_DIR.iterdir()):
        if not p.is_dir():
            continue
        f = p / "election.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except Exception as e:
            print(f"  ERROR {p.name}: {e}")
            continue
        elections.append(summarize_election(d))

    # sort: active races with polls first, then by poll count desc, then by eid
    elections.sort(key=lambda e: (
        -e["polls_count"],
        int(e["election_id"]) if e["election_id"] and e["election_id"].isdigit() else 0,
    ))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(elections),
        "with_polls": sum(1 for e in elections if e["polls_count"] > 0),
        "by_type": {},
        "by_poll_count": {},
        "elections": elections,
    }

    # type distribution
    for e in elections:
        t = e["type"] or "unknown"
        out["by_type"][t] = out["by_type"].get(t, 0) + 1

    # poll count distribution (bucketed)
    for e in elections:
        n = e["polls_count"]
        bucket = f"{n}" if n < 10 else f"{n//10*10}-{n//10*10+9}"
        out["by_poll_count"][bucket] = out["by_poll_count"].get(bucket, 0) + 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"[aggregate] wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"  {out['total']} elections, {out['with_polls']} with polls")
    print(f"  by type: {out['by_type']}")

    # append history summary line
    with OUT_HIST.open("a") as f:
        f.write(json.dumps({
            "ts": out["generated_at"],
            "total": out["total"],
            "with_polls": out["with_polls"],
            "by_type": out["by_type"],
        }) + "\n")
    print(f"[aggregate] appended to {OUT_HIST.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
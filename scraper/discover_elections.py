#!/usr/bin/env python3
"""
discover_elections.py - crawl /elections/overview, extract active elections.

Parses the `mapRaceLeans` JS array from the overview page HTML. Each entry
contains election_id, state_id, type, lean, and URL. Writes one election
URL per line to scraper/urls/elections.txt.

Usage:
    python3 scraper/discover_elections.py
"""

import base64
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URLS_DIR = HERE / "urls"
OUT_FILE = URLS_DIR / "elections.txt"
BASE = "https://battleforthehill.com"


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def extract_race_leans(html):
    """
    Extract every race entry from the mapRaceLeans JS array.
    Returns list of dicts with election_id, state_id, type, lean, label, url, etc.
    """
    m = re.search(r'const mapRaceLeans = (\[.*?\]);', html, re.DOTALL)
    if not m:
        # fallback: some builds may use "let" or "var"
        m = re.search(r'(?:var|let|const)\s+mapRaceLeans\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m:
        return []

    import json
    try:
        raw = m.group(1)
        # unescape the \/ that JSON escaping puts in URLs
        raw = raw.replace('\\/', '/')
        return json.loads(raw)
    except Exception as e:
        print(f"  WARN: failed to parse mapRaceLeans: {e}")
        return []


def main():
    URLS_DIR.mkdir(parents=True, exist_ok=True)

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json - run save_auth.py first")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        print("[discover] fetching /elections/overview")
        page.goto(f"{BASE}/elections/overview", timeout=30000, wait_until="networkidle")
        html = page.content()
        browser.close()

    races = extract_race_leans(html)
    if not races:
        print("no races found in mapRaceLeans - writing empty file")
        OUT_FILE.write_text("# no active races\n")
        return

    # Deduplicate by election_id, keep the URL
    seen = {}
    for r in races:
        eid = r.get("election_id")
        url = r.get("url")
        if eid and url and eid not in seen:
            seen[eid] = {
                "election_id": str(eid),
                "url": url,
                "state_id": str(r.get("state_id", "")),
                "type": r.get("type", ""),
                "label": r.get("label", ""),
                "lean": r.get("lean", 0),
                "lean_label": r.get("lean_label"),
                "leading_side": r.get("leading_side"),
            }

    OUT_FILE.write_text("\n".join(
        f"{v['election_id']} {v['url']} {v['state_id']} {v['type']} \"{v['label']}\" {v['lean']}"
        for v in sorted(seen.values(), key=lambda x: int(x["election_id"]))
    ) + "\n")

    print(f"[discover] wrote {len(seen)} active elections to {OUT_FILE.relative_to(HERE.parent)}")
    for v in sorted(seen.values(), key=lambda x: int(x["election_id"]))[:5]:
        print(f"  {v['election_id']}  {v['type']:8}  {v['lean_label'] or 'uncontested'}  {v['url']}")
    if len(seen) > 5:
        print(f"  ... and {len(seen) - 5} more")


if __name__ == "__main__":
    main()
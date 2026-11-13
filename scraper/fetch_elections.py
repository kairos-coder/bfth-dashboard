#!/usr/bin/env python3
"""
fetch_elections.py - fetch election pages for every URL in elections.txt.

Saves raw HTML to scraper/raw/elections/<eid>.html.

Usage:
    python3 scraper/fetch_elections.py
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
ELECTIONS_FILE = HERE / "elections.txt"
RAW_DIR = HERE / "raw" / "elections"
BASE = "https://battleforthehill.com"


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        import base64
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def read_elections(path):
    """Return list of (eid, url) from elections.txt."""
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url = line.split()[0]
        if url.startswith("http"):
            m = re.search(r"/elections/(\d+)", url)
            if m:
                out.append((m.group(1), url.rstrip("/")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--election", type=str, default=None)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    if not ELECTIONS_FILE.exists():
        sys.exit(f"missing {ELECTIONS_FILE}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    elections = read_elections(ELECTIONS_FILE)
    if args.election:
        elections = [(eid, u) for eid, u in elections if eid == args.election]
    if not elections:
        sys.exit("no elections to fetch")

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for eid, url in elections:
            out = RAW_DIR / f"{eid}.html"
            if out.exists():
                print(f"[fetch] {eid} (cached)")
                continue
            print(f"[fetch] {eid}: {url}")
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                out.write_text(page.content(), encoding="utf-8")
            except Exception as e:
                print(f"  error: {e}")
            time.sleep(args.delay)

        browser.close()


if __name__ == "__main__":
    main()
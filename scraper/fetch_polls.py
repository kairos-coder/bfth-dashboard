#!/usr/bin/env python3
"""
fetch_polls.py - fetch every poll URL from scraper/polls/*.txt.

Saves raw HTML to scraper/raw/polls/<poll_id>.html.

Usage:
    python3 scraper/fetch_polls.py
    python3 scraper/fetch_polls.py --election 22081
"""

import argparse
import base64
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
POLLS_DIR = HERE / "polls"
RAW_DIR = HERE / "raw" / "polls"

BASE = "https://battleforthehill.com"


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def slug_from_url(url):
    m = re.search(r"/poll/(\d+)", url)
    return m.group(1) if m else "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--election", type=str, default=None)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.election:
        files = [POLLS_DIR / f"{args.election}.txt"]
    else:
        files = sorted(POLLS_DIR.glob("*.txt"))

    if not files:
        sys.exit("no poll URL lists found")

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json - run save_auth.py first")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for f in files:
            print(f"[fetch] {f.name}")
            urls = [u.strip() for u in f.read_text().splitlines()
                    if u.strip() and not u.strip().startswith("#")]

            for i, path in enumerate(urls, 1):
                url = BASE + path if path.startswith("/") else path
                poll_id = slug_from_url(url)
                out_file = RAW_DIR / f"{poll_id}.html"

                if out_file.exists():
                    print(f"  [{i}/{len(urls)}] {poll_id} (cached)")
                    continue

                print(f"  [{i}/{len(urls)}] {poll_id}")
                try:
                    page.goto(url, timeout=30000, wait_until="networkidle")
                    html = page.content()
                    out_file.write_text(html, encoding="utf-8")
                except Exception as e:
                    print(f"    error: {e}")
                time.sleep(args.delay)

        browser.close()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
discover.py - crawl BFTH party member list pages and extract politician URLs.

Reads the paginated /national/users?party=N list, follows next links,
writes scraper/urls/<party>.txt with one URL per line.

Usage:
    python3 scraper/discover.py --party gop --party-id 2
    python3 scraper/discover.py --party dem --party-id 1
"""

import argparse
import base64
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
URLS_DIR = HERE / "urls"

BASE = "https://battleforthehill.com/national/users"


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def extract_politician_urls(html):
    """Return set of unique /politician/<id> URLs."""
    ids = set(re.findall(r'/politician/(\d+)"', html))
    return {f"https://battleforthehill.com/politician/{i}" for i in ids}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--party", required=True, choices=["gop", "dem"])
    ap.add_argument("--party-id", required=True, type=int,
                    help="2 = Republican, 1 = Democratic")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    URLS_DIR.mkdir(exist_ok=True)
    out_file = URLS_DIR / f"{args.party}.txt"

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json - run save_auth.py first")

    collected = set()
    print(f"[discover] party {args.party} (id={args.party_id})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for page_num in range(1, args.max_pages + 1):
            url = f"{BASE}?party={args.party_id}"
            if page_num > 1:
                url += f"&page={page_num}"
            print(f"[discover] page {page_num}: {url}")

            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
            except PWTimeout:
                print(f"  timeout - stopping")
                break
            except Exception as e:
                print(f"  error: {e} - stopping")
                break

            html = page.content()
            found = extract_politician_urls(html)
            new = found - collected
            collected.update(found)
            print(f"  {len(found)} links on page ({len(new)} new, {len(collected)} total)")

            if not new:
                print("  no new links - stopping")
                break

            # Check for next page link in HTML
            if f"page={page_num + 1}" not in html and f"page%3D{page_num + 1}" not in html:
                print(f"  no link to page {page_num + 1} - stopping")
                break

            time.sleep(args.delay)

        browser.close()

    if not collected:
        sys.exit("no politician URLs found")

    header = f"# Auto-discovered {args.party.upper()} politicians ({len(collected)} URLs)\n"
    out_file.write_text(header + "\n".join(sorted(collected)) + "\n")
    print(f"[discover] wrote {len(collected)} URLs to {out_file.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
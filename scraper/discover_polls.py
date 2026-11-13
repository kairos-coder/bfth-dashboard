#!/usr/bin/env python3
"""
discover_polls.py - crawl election pages, extract every poll URL.

Reads scraper/elections.txt (one election URL per line), crawls each
election's paginated poll list, and writes scraper/polls/<eid>.txt with
one /poll/<pid> path per line.

Usage:
    python3 scraper/discover_polls.py
    python3 scraper/discover_polls.py --election 22081
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
ELECTIONS_FILE = HERE / "elections.txt"
POLLS_DIR = HERE / "polls"
BASE = "https://battleforthehill.com"


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def read_elections(path):
    """Return list of (election_id, full_url) tuples."""
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url = line.split()[0]
        if not url.startswith("http"):
            continue
        m = re.search(r"/elections/(\d+)", url)
        if m:
            out.append((m.group(1), url.rstrip("/")))
    return out


def extract_poll_urls(html):
    """Return set of /states/<sid>/elections/<eid>/poll/<pid> paths."""
    pattern = r'/states/\d+/elections/\d+/poll/\d+'
    return set(re.findall(pattern, html))


def crawl_election(page, election_id, base_url, max_pages=20, delay=1.0):
    """Walk pagination for one election, return set of poll paths."""
    collected = set()
    for n in range(1, max_pages + 1):
        url = base_url + (f"?page={n}" if n > 1 else "")
        print(f"    page {n}: {url}")
        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
        except Exception as e:
            print(f"      error: {e}")
            break
        found = extract_poll_urls(page.content())
        new = found - collected
        print(f"      {len(found)} links ({len(new)} new, {len(collected)} total)")
        if not new:
            break
        collected.update(found)
        if n < max_pages:
            time.sleep(delay)
    return collected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--election", type=str, default=None,
                    help="limit to one election ID (must still be in elections.txt)")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    if not ELECTIONS_FILE.exists():
        sys.exit(f"missing {ELECTIONS_FILE}")
    POLLS_DIR.mkdir(exist_ok=True)

    elections = read_elections(ELECTIONS_FILE)
    if args.election:
        elections = [(eid, url) for eid, url in elections if eid == args.election]
    if not elections:
        sys.exit(f"no elections to discover (check {ELECTIONS_FILE})")

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json - run save_auth.py first")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for eid, base_url in elections:
            print(f"[discover] election {eid}")
            polls = crawl_election(page, eid, base_url, args.max_pages, args.delay)
            out_file = POLLS_DIR / f"{eid}.txt"
            if polls:
                out_file.write_text(
                    f"# Polls for election {eid}\n" + "\n".join(sorted(polls)) + "\n"
                )
                print(f"  wrote {len(polls)} poll URLs to {out_file.relative_to(HERE)}")
            else:
                print(f"  no polls found for {eid}")

        browser.close()


if __name__ == "__main__":
    main()
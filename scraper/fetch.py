#!/usr/bin/env python3
"""
fetch.py — raw HTML fetcher for Battle for the Hill profiles.

Purpose: prove we can reach the profiles and get the stats we care about.
No parsing. No JSON. No dashboard. Just: did we get the HTML, and does it
contain the fields we need?

Usage:
    python3 fetch.py                    # fetch all URLs in urls.txt
    python3 fetch.py --limit 3          # fetch only the first 3 (for testing)
    python3 fetch.py --url <one-url>    # fetch a single URL

Output:
    scraper/raw/<slug>.html             # raw HTML per profile
    scraper/fetch-report.txt            # summary of what worked/failed
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests

# --- config ---------------------------------------------------------------

HERE = Path(__file__).resolve().parent
URLS_FILE = HERE / "urls.txt"
RAW_DIR = HERE / "raw"
REPORT_FILE = HERE / "fetch-report.txt"

# Strings we look for in the HTML to confirm the stats are present.
# Adjust these to match BFTH's actual labels.
EXPECTED_MARKERS = [
    "National Prestige",
    "Campaign Strength",
    "State Reputation",
    "National Reputation",
    "Campaign Funds",
]

# Cookies: read from env var BFTH_COOKIES if set (JSON dict or "a=1; b=2" string).
# Leave unset for a public test.
def load_cookies():
    raw = os.environ.get("BFTH_COOKIES", "").strip()
    if not raw:
        return None
    # Accept either a JSON dict or a "k=v; k=v" cookie header string.
    if raw.startswith("{"):
        import json
        return json.loads(raw)
    jar = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar

# --- helpers --------------------------------------------------------------

def slugify(url: str) -> str:
    """Turn a URL into a safe filename."""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name)
    return name or "index"

def read_urls(path: Path) -> list[str]:
    if not path.exists():
        sys.exit(f"missing {path} — create it with one URL per line")
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls

def fetch_one(session: requests.Session, url: str, out_dir: Path) -> dict:
    """Fetch a URL, save raw HTML, return a summary dict."""
    result = {
        "url": url,
        "status": None,
        "bytes": 0,
        "markers_found": [],
        "markers_missing": [],
        "error": None,
        "saved_to": None,
    }
    try:
        r = session.get(url, timeout=20, allow_redirects=True)
        result["status"] = r.status_code
        result["bytes"] = len(r.content)
        html = r.text

        # Check which expected markers appear in the HTML.
        for marker in EXPECTED_MARKERS:
            if marker in html:
                result["markers_found"].append(marker)
            else:
                result["markers_missing"].append(marker)

        # Save raw HTML regardless of markers — we want to inspect failures.
        out_path = out_dir / f"{slugify(url)}.html"
        out_path.write_text(html, encoding="utf-8", errors="replace")
        result["saved_to"] = str(out_path)

    except requests.RequestException as e:
        result["error"] = str(e)
    return result

# --- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="only fetch the first N URLs")
    ap.add_argument("--url", type=str, default=None,
                    help="fetch a single URL instead of urls.txt")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds between requests (default 1.0)")
    args = ap.parse_args()

    RAW_DIR.mkdir(exist_ok=True)

    if args.url:
        urls = [args.url]
    else:
        urls = read_urls(URLS_FILE)

    if args.limit:
        urls = urls[: args.limit]

    if not urls:
        sys.exit("no URLs to fetch")

    cookies = load_cookies()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "bftf-warroom/0.1 (+private friend tool)",
        "Accept": "text/html,application/xhtml+xml",
    })
    if cookies:
        session.cookies.update(cookies)
        print(f"[auth] loaded {len(cookies)} cookies")
    else:
        print("[auth] no cookies — trying unauthenticated")

    print(f"[plan] fetching {len(urls)} URLs -> {RAW_DIR}/")
    results = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        result = fetch_one(session, url, RAW_DIR)
        results.append(result)
        if result["error"]:
            print(f"         ERROR: {result['error']}")
        else:
            found = len(result["markers_found"])
            total = len(EXPECTED_MARKERS)
            print(f"         {result['status']} · {result['bytes']:,} bytes · "
                  f"{found}/{total} markers found")
        time.sleep(args.delay)

    # Write a human-readable report.
    lines = []
    lines.append(f"# Fetch report — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# {len(results)} URLs\n")
    ok = sum(1 for r in results if r["status"] == 200 and not r["error"])
    lines.append(f"## Summary: {ok}/{len(results)} fetched successfully\n")
    for r in results:
        lines.append(f"### {r['url']}")
        lines.append(f"- status: {r['status']}")
        lines.append(f"- bytes: {r['bytes']}")
        lines.append(f"- saved: {r['saved_to']}")
        if r["error"]:
            lines.append(f"- error: {r['error']}")
        if r["markers_found"]:
            lines.append(f"- markers found: {', '.join(r['markers_found'])}")
        if r["markers_missing"]:
            lines.append(f"- markers missing: {', '.join(r['markers_missing'])}")
        lines.append("")
    REPORT_FILE.write_text("\n".join(lines))
    print(f"\n[report] wrote {REPORT_FILE}")

if __name__ == "__main__":
    main()

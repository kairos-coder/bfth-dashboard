#!/usr/bin/env python3
"""
fetch.py - raw HTML fetcher for Battle for the Hill profiles.

Purpose: prove we can reach the profiles and get the stats we care about.
No parsing beyond marker detection. No dashboard logic. Just: did we get
the HTML, does it contain the fields we need, and can we write a JSON
snapshot the static page can read?

Usage:
    python3 scraper/fetch.py                    # fetch all URLs in urls.txt
    python3 scraper/fetch.py --limit 3          # fetch only the first 3
    python3 scraper/fetch.py --url <one-url>    # fetch a single URL
    python3 scraper/fetch.py --delay 2.0        # slower between requests

Output:
    scraper/raw/<slug>.html             # raw HTML per profile
    scraper/fetch-report.txt            # human-readable summary
    data/latest.json                    # dashboard data (repo root)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- paths ----------------------------------------------------------------
# Repo layout:
#   <repo>/index.html
#   <repo>/data/latest.json
#   <repo>/scraper/fetch.py
#   <repo>/scraper/urls.txt
#   <repo>/scraper/raw/
#   <repo>/scraper/fetch-report.txt

HERE = Path(__file__).resolve().parent          # <repo>/scraper
REPO_ROOT = HERE.parent                         # <repo>
URLS_FILE = HERE / "urls.txt"
RAW_DIR = HERE / "raw"
REPORT_FILE = HERE / "fetch-report.txt"
DATA_DIR = REPO_ROOT / "data"
DATA_FILE = DATA_DIR / "latest.json"

# Strings we look for in the HTML to confirm the stats are present.
# Adjust these to match BFTH's actual labels once we see real HTML.
EXPECTED_MARKERS = [
    "National Prestige",
    "Campaign Strength",
    "State Reputation",
    "National Reputation",
    "Campaign Funds",
]

# --- auth -----------------------------------------------------------------

def load_cookies():
    """Read BFTH_COOKIES env var as either JSON dict or 'k=v; k=v' string."""
    raw = os.environ.get("BFTH_COOKIES", "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    jar = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar

# --- helpers --------------------------------------------------------------

def slugify(url):
    """Turn a URL into a safe filename."""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name)
    return name or "index"

def read_urls(path):
    if not path.exists():
        sys.exit(f"missing {path} - create it with one URL per line")
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls

def fetch_one(session, url, out_dir):
    """Fetch a URL, save raw HTML, return a result dict."""
    result = {
        "url": url,
        "status": None,
        "bytes": 0,
        "markers_found": [],
        "markers_missing": [],
        "final_url": None,
        "error": None,
        "saved_to": None,
    }
    try:
        r = session.get(url, timeout=20, allow_redirects=True)
        result["status"] = r.status_code
        result["bytes"] = len(r.content)
        result["final_url"] = r.url
        html = r.text

        for marker in EXPECTED_MARKERS:
            if marker in html:
                result["markers_found"].append(marker)
            else:
                result["markers_missing"].append(marker)

        out_path = out_dir / f"{slugify(url)}.html"
        out_path.write_text(html, encoding="utf-8", errors="replace")
        result["saved_to"] = str(out_path.relative_to(REPO_ROOT))

    except requests.RequestException as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result

def write_report(results, path):
    lines = []
    lines.append(f"# Fetch report - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# {len(results)} URLs\n")
    ok = sum(1 for r in results if r["status"] == 200 and not r["error"])
    lines.append(f"## Summary: {ok}/{len(results)} fetched successfully\n")
    for r in results:
        lines.append(f"### {r['url']}")
        lines.append(f"- status: {r['status']}")
        lines.append(f"- bytes: {r['bytes']}")
        if r["final_url"] and r["final_url"] != r["url"]:
            lines.append(f"- final_url: {r['final_url']}  (redirected)")
        lines.append(f"- saved: {r['saved_to']}")
        if r["error"]:
            lines.append(f"- error: {r['error']}")
        if r["markers_found"]:
            lines.append(f"- markers found: {', '.join(r['markers_found'])}")
        if r["markers_missing"]:
            lines.append(f"- markers missing: {', '.join(r['markers_missing'])}")
        lines.append("")
    path.write_text("\n".join(lines))

def write_data(results, path):
    """Write the JSON snapshot that index.html reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "fetch.py",
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2))
    # Confirm parseability so a bad write fails the workflow loudly.
    json.loads(path.read_text())

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
        sys.exit("no URLs to fetch - add at least one to scraper/urls.txt")

    cookies = load_cookies()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "bfth-warroom/0.1 (+private friend tool)",
        "Accept": "text/html,application/xhtml+xml",
    })
    if cookies:
        session.cookies.update(cookies)
        print(f"[auth] loaded {len(cookies)} cookies")
    else:
        print("[auth] no cookies - trying unauthenticated")

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
            print(f"         {result['status']} - {result['bytes']:,} bytes - "
                  f"{found}/{total} markers found")
            if result["final_url"] != result["url"]:
                print(f"         redirected -> {result['final_url']}")
        if i < len(urls):
            time.sleep(args.delay)

    write_report(results, REPORT_FILE)
    print(f"[report] wrote {REPORT_FILE.relative_to(REPO_ROOT)}")

    write_data(results, DATA_FILE)
    print(f"[data] wrote {DATA_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

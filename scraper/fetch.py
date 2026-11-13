#!/usr/bin/env python3
"""
fetch.py - Playwright-based fetcher for BFTH profiles.
Reads BFTH_STORAGE_STATE_B64 from env (or uses local scraper/storage_state.json),
writes data/latest.json + scraper/fetch-report.txt + scraper/raw/*.html.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
URLS_FILE = HERE / "urls" / "gop.txt"
RAW_DIR = HERE / "raw"
REPORT_FILE = HERE / "fetch-report.txt"
DATA_DIR = REPO_ROOT / "data"
DATA_FILE = DATA_DIR / "latest.json"

EXPECTED_MARKERS = [
    "National Prestige",
    "Campaign Strength",
    "State Reputation",
    "National Reputation",
    "Campaign Funds",
]

def load_storage_state():
    """Prefer BFTH_STORAGE_STATE_B64 (CI) then local storage_state.json."""
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        state_path = HERE / "storage_state.ci.json"
        state_path.write_bytes(base64.b64decode(raw))
        return str(state_path)
    local = HERE / "storage_state.json"
    if local.exists():
        return str(local)
    return None

def slugify(url):
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

def fetch_one(page, url, out_dir):
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
        resp = page.goto(url, timeout=30000, wait_until="networkidle")
        result["status"] = resp.status if resp else None
        result["final_url"] = page.url
        html = page.content()
        result["bytes"] = len(html.encode("utf-8"))

        for marker in EXPECTED_MARKERS:
            if marker in html:
                result["markers_found"].append(marker)
            else:
                result["markers_missing"].append(marker)

        out_path = out_dir / f"{slugify(url)}.html"
        out_path.write_text(html, encoding="utf-8", errors="replace")
        result["saved_to"] = str(out_path.relative_to(REPO_ROOT))

    except PWTimeout:
        result["error"] = "Playwright timeout (30s)"
    except Exception as e:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "fetch.py (playwright)",
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2))
    json.loads(path.read_text())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--url", type=str, default=None)
    ap.add_argument("--delay", type=float, default=1.5)
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

    state_path = load_storage_state()
    if state_path:
        print(f"[auth] loaded storageState ({Path(state_path).stat().st_size} bytes)")
    else:
        print("[auth] no storageState - will likely hit login redirect")

    print(f"[plan] fetching {len(urls)} URLs -> {RAW_DIR}/")
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=state_path,
            user_agent="bfth-warroom/0.1 (+private friend tool)",
        )
        page = context.new_page()

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            result = fetch_one(page, url, RAW_DIR)
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

        browser.close()

    write_report(results, REPORT_FILE)
    print(f"[report] wrote {REPORT_FILE.relative_to(REPO_ROOT)}")
    write_data(results, DATA_FILE)
    print(f"[data] wrote {DATA_FILE.relative_to(REPO_ROOT)}")

if __name__ == "__main__":
    main()

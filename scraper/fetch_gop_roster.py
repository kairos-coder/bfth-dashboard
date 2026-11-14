#!/usr/bin/env python3
"""
fetch_gop_roster.py — write scraper/urls/gop.txt from the live GOP roster.

Uses Playwright + the same storage state that fetch.py uses.
Paginates ?party=2&page=N until no new IDs.
"""
import base64, os, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "urls" / "gop.txt"

PARTY_ID = 2
BASE_URL = "https://battleforthehill.com/national/users"
MAX_PAGES = 20


def load_storage_state():
    """Prefer BFTH_STORAGE_STATE_B64 (CI) then local storage_state.json — same as fetch.py."""
    raw = os.environ.get("BFTH_STORAGE_STATE_B64")
    if raw:
        state_path = HERE / "storage_state.ci.json"
        state_path.write_bytes(base64.b64decode(raw))
        return str(state_path)
    local = HERE / "storage_state.json"
    if local.exists():
        return str(local)
    return None


def extract_ids(html_text):
    hits = re.findall(r'/politician/(\d+)', html_text)
    seen, out = set(), []
    for pid in hits:
        pid = int(pid)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def main():
    state_path = load_storage_state()
    if not state_path:
        print("[gop-roster] no storage state (checked BFTH_STORAGE_STATE_B64 and scraper/storage_state.json)", file=sys.stderr)
        sys.exit(1)

    all_ids, seen = [], set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state_path)
        page = ctx.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            url = f"{BASE_URL}?party={PARTY_ID}&page={page_num}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[gop-roster] page {page_num} goto failed: {e}", file=sys.stderr)
                if page_num == 1:
                    browser.close()
                    sys.exit(1)
                break

            html = page.content()
            ids = extract_ids(html)
            new = [i for i in ids if i not in seen]
            print(f"[gop-roster] page {page_num}: {len(ids)} rows, {len(new)} new")

            # Sanity: if the first page has zero politician links, we're not authenticated
            if page_num == 1 and not ids:
                if 'Log In' in html:
                    print("[gop-roster] page returned login wall — storage state is stale or expired",
                          file=sys.stderr)
                else:
                    print("[gop-roster] page structure changed — no /politician/ links found",
                          file=sys.stderr)
                browser.close()
                sys.exit(2)

            for pid in ids:
                if pid not in seen:
                    seen.add(pid)
                    all_ids.append(pid)

            if not new:
                break  # no progress → past last page

            # check for a "next page" link before looping
            if not re.search(
                rf'/national/users\?party={PARTY_ID}&(?:amp;)?page={page_num + 1}',
                html
            ):
                break

        browser.close()

    if not all_ids:
        print("[gop-roster] parsed 0 IDs", file=sys.stderr)
        sys.exit(2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".txt.tmp")
    with open(tmp, "w") as f:
        for pid in sorted(all_ids):
            f.write(f"https://battleforthehill.com/politician/{pid}\n")
    tmp.replace(OUT)

    print(f"[gop-roster] wrote {len(all_ids)} URLs → {OUT}")


if __name__ == "__main__":
    main()
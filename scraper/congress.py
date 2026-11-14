#!/usr/bin/env python3
"""
congress.py — scrape Senate and House pages, extract party seat counts
and leadership, write data/congress.json.

Usage:
    python3 scraper/congress.py
"""
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = HERE / "raw" / "congress"
STORAGE_STATE = HERE / "storage_state.json"

CHAMBERS = {
    "senate": {
        "url": "https://battleforthehill.com/national/senate/1",
        "table_id": "senate-political-breakdown-table",
        "total_seats_selector": "div[style*='font-size: 50px']",  # the big seat count
    },
    "house": {
        "url": "https://battleforthehill.com/national/house/1",
        "table_id": "political-breakdown-table",
        "total_seats_selector": "div[style*='font-size: 50px']",
    },
}

PARTY_COLORS = {
    "1": "#3B82F6", "2": "#EF4444", "254": "#961D1D",
    "255": "#86489C", "396": "#020080", "410": "#F5D60F",
    "416": "#2F4F4F", "419": "#4E5FA2",
}


def parse_chamber(html_text, chamber):
    soup = BeautifulSoup(html_text, "html.parser")

    # Party seats
    table = soup.find("table", id=CHAMBERS[chamber]["table_id"])
    parties = []
    total_seats = 0
    if table:
        for tr in table.select("tbody tr"):
            tr_soup = tr
            seats = int(tr_soup.get("data-seats") or 0)
            link = tr_soup.find("a", href=re.compile(r"/parties/(\d+)"))
            party_id = None
            party_name = "—"
            if link:
                m = re.search(r"/parties/(\d+)", link.get("href", ""))
                if m:
                    party_id = m.group(1)
                name_span = link.find("span", style=re.compile("color"))
                party_name = (name_span or link).get_text(strip=True)
            parties.append({
                "party_id": party_id,
                "name": party_name,
                "seats": seats,
                "color": PARTY_COLORS.get(party_id, "#666"),
            })
            total_seats += seats

    # Leadership: look for <h3> with role text, find politician link nearby
    leadership = []
    for h3 in soup.find_all("h3"):
        role_text = h3.get_text(strip=True)
        if not re.search(r"Leader|Whip|Speaker|Pro-Tempore|President of the Senate", role_text, re.I):
            continue
        # walk forward through siblings to find a politician link
        name, pid = None, None
        parent = h3.find_parent("div")
        search_area = parent.find_next("div") if parent else None
        scope = search_area if search_area else h3.parent
        for link in (scope.find_all("a", href=re.compile(r"/politician/\d+"), limit=5) if scope else []):
            m = re.search(r"/politician/(\d+)", link.get("href", ""))
            if m:
                pid = m.group(1)
                name = link.get_text(strip=True)
                break
        leadership.append({
            "role": role_text,
            "name": name,
            "politician_id": pid,
        })

    # Fallback: total seats from the big number in the chart
    if not total_seats:
        big_num = soup.find("div", string=re.compile(r"^\d+$"))
        if big_num and big_num.get_text(strip=True).isdigit():
            total_seats = int(big_num.get_text(strip=True))

    # GOP = party_id 2
    gop = next((p for p in parties if p["party_id"] == "2"), None)

    return {
        "chamber": chamber,
        "total_seats": total_seats,
        "majority_needed": (total_seats // 2) + 1 if total_seats else None,
        "gop_seats": gop["seats"] if gop else 0,
        "parties": sorted(parties, key=lambda p: -p["seats"]),
        "leadership": [l for l in leadership if l["name"] or l["politician_id"]],
    }


def main():
    if not STORAGE_STATE.exists():
        print(f"[congress] missing {STORAGE_STATE}", file=sys.stderr)
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    result = {"generated_at": datetime.now(timezone.utc).isoformat()}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(STORAGE_STATE))
        page = ctx.new_page()

        for chamber, cfg in CHAMBERS.items():
            print(f"[congress] fetching {chamber}")
            try:
                page.goto(cfg["url"], wait_until="domcontentloaded", timeout=30000)
                html = page.content()
            except Exception as e:
                print(f"[congress] {chamber} failed: {e}", file=sys.stderr)
                continue

            (RAW_DIR / f"{chamber}.html").write_text(html)
            result[chamber] = parse_chamber(html, chamber)
            print(f"[congress] {chamber}: {result[chamber]['gop_seats']} GOP / {result[chamber]['total_seats']} seats")

        browser.close()

    out = DATA_DIR / "congress.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.replace(out)
    print(f"[congress] wrote {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
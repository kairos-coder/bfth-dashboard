#!/usr/bin/env python3
"""
nations.py - scrape all nation budgets.

1. discover: fetch /national/budget/1, parse the country-switcher <select>
             for all nation IDs + names
2. fetch:    for each nation, GET /national/budget/<id>, save raw HTML
3. parse:    extract GDP, revenue, expenditure, debt from budget page
             write data/nations/<id>.json
4. aggregate: consolidate to data/nations.json

Usage:
    python3 scraper/nations.py              # full pipeline
    python3 scraper/nations.py --discover   # only discovery
    python3 scraper/nations.py --fetch      # only fetch
    python3 scraper/nations.py --parse      # only parse
    python3 scraper/nations.py --aggregate  # only aggregate
    python3 scraper/nations.py --nation 29  # single nation
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

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
URLS_FILE = HERE / "urls" / "nations.txt"
RAW_DIR = HERE / "raw" / "nations"
DATA_DIR = REPO_ROOT / "data" / "nations"
AGGREGATE = REPO_ROOT / "data" / "nations.json"

BASE = "https://battleforthehill.com"
SEED_URL = f"{BASE}/national/budget/1"  # any nation page works for discovery


def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def goto_with_retry(page, url, timeout=30000, settle_ms=1500, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            return True
        except Exception as e:
            last = e
            if attempt < retries:
                print(f"    retry {attempt+1}/{retries}: {type(e).__name__}")
                time.sleep(2)
    raise last


# ─── discovery ───
def discover(state_path):
    URLS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()
        print(f"[discover] fetching {SEED_URL}")
        goto_with_retry(page, SEED_URL, settle_ms=1000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", {"id": "budget_country_id"})
    if not select:
        # fallback: any select whose options look like nation IDs
        for s in soup.find_all("select"):
            if len(s.find_all("option")) > 50:
                select = s
                break

    nations = []
    if select:
        for opt in select.find_all("option"):
            nid = opt.get("value")
            name = opt.get_text(strip=True)
            if nid and name:
                nations.append((nid, name))

    if not nations:
        print("[discover] FAILED: no country-switcher select found")
        return

    lines = ["# nation_id | name"]
    for nid, name in sorted(nations, key=lambda x: int(x[0])):
        lines.append(f"{nid} {name}")
    URLS_FILE.write_text("\n".join(lines) + "\n")
    print(f"[discover] wrote {len(nations)} nations to urls/nations.txt")


def read_nations():
    if not URLS_FILE.exists():
        return []
    out = []
    for line in URLS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            out.append({"id": parts[0], "name": parts[1]})
    return out


# ─── fetch ───
def fetch(state_path, only_id=None, delay=1.5):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    nations = read_nations()
    if only_id:
        nations = [n for n in nations if n["id"] == only_id]
    if not nations:
        print("[fetch] no nations to fetch")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for i, n in enumerate(nations, 1):
            nid = n["id"]
            out = RAW_DIR / f"{nid}.html"
            if out.exists():
                print(f"[fetch {i}/{len(nations)}] {nid} {n['name']} (cached)")
                continue
            url = f"{BASE}/national/budget/{nid}"
            print(f"[fetch {i}/{len(nations)}] {nid} {n['name']}")
            try:
                goto_with_retry(page, url, settle_ms=1000, retries=1)
                out.write_text(page.content(), encoding="utf-8")
            except Exception as e:
                print(f"  ERROR {nid}: {e}")
            time.sleep(delay)

        browser.close()


# ─── parse ───
def _num(text):
    if text is None:
        return None
    m = re.search(r"-?\$?\s*([\d,]+(?:\.\d+)?)", str(text).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _pct(text):
    if text is None:
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", str(text))
    return float(m.group(1)) if m else None


def _find_row(soup, label):
    """Find the <tr> whose first bold <td> is `label`. Returns the row or None."""
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        first = tds[0].get_text(strip=True)
        if first == label:
            return tr
    return None


def _row_values(tr):
    """Return (description_text, amount_text) for a row."""
    if not tr:
        return (None, None)
    tds = tr.find_all("td", recursive=False)
    if len(tds) >= 3:
        return (tds[1].get_text(" ", strip=True), tds[2].get_text(" ", strip=True))
    elif len(tds) >= 2:
        return (None, tds[1].get_text(" ", strip=True))
    return (None, None)


def _header_label(soup):
    """'<h1>United States Budget</h1>' -> 'United States'"""
    h1 = soup.find("h1")
    if not h1:
        return None, None
    text = h1.get_text(strip=True)
    if " Budget" in text:
        short = text.replace(" Budget", "").strip()
    else:
        short = text
    h2 = soup.find("h2")
    full = h2.get_text(strip=True) if h2 else short
    return (short, full)


def parse_one(html, nid, fallback_name):
    soup = BeautifulSoup(html, "html.parser")
    short_name, full_name = _header_label(soup)

    # GDP
    gdp_tr = _find_row(soup, "GDP")
    _, gdp_txt = _row_values(gdp_tr)
    gdp = _num(gdp_txt)

    gdppc_tr = _find_row(soup, "GDP per Capita")
    _, gdppc_txt = _row_values(gdppc_tr)
    gdppc = _num(gdppc_txt)

    growth_tr = _find_row(soup, "Growth")
    _, growth_txt = _row_values(growth_tr)
    growth = _pct(growth_txt)

    # Revenue rows
    def rev(label):
        tr = _find_row(soup, label)
        desc, amt = _row_values(tr)
        return {
            "description": desc,
            "pct": _pct(desc),
            "amount": _num(amt),
            "amount_pct": _pct(amt),
        }

    corporate = rev("Corporate Tax")
    income = rev("Income Tax")
    tariffs = rev("Tariffs")
    estate = rev("Estate Tax")
    excise = rev("Excise Tax")
    exit_tax = rev("Exit Tax")

    total_rev_tr = _find_row(soup, "Total")  # careful: both revenue and expenditure have "Total"
    # walk rows, first "Total" after "Revenue" section header
    total_rev = None
    total_exp = None
    in_revenue = False
    in_expenditure = False
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        first = tds[0].get_text(strip=True)
        if first == "Corporate Tax":
            in_revenue = True
            in_expenditure = False
        elif first == "Defense":
            in_revenue = False
            in_expenditure = True
        elif first == "Total":
            amt = tds[-1].get_text(" ", strip=True) if tds else None
            if in_revenue:
                total_rev = {"amount": _num(amt), "pct_gdp": _pct(amt)}
            elif in_expenditure:
                total_exp = {"amount": _num(amt), "pct_gdp": _pct(amt)}

    # Debt
    debt_gdp_tr = _find_row(soup, "Debt to GDP")
    _, debt_gdp_txt = _row_values(debt_gdp_tr)
    debt_gdp = _pct(debt_gdp_txt)

    debt_tr = _find_row(soup, "Debt")
    _, debt_txt = _row_values(debt_tr)
    debt = _num(debt_txt)

    interest_rate_tr = _find_row(soup, "Interest Rate")
    _, interest_rate_txt = _row_values(interest_rate_tr)
    interest_rate = _pct(interest_rate_txt)

    # Surplus
    surplus_tr = _find_row(soup, "Surplus")
    _, surplus_txt = _row_values(surplus_tr)
    surplus_amount = _num(surplus_txt)

    budget_surplus_tr = _find_row(soup, "Budget Surplus")
    _, budget_surplus_txt = _row_values(budget_surplus_tr)
    budget_surplus_pct = _pct(budget_surplus_txt)

    # Wealth fund
    wf_tr = _find_row(soup, "Wealth Fund")
    _, wf_txt = _row_values(wf_tr)
    wealth_fund = _num(wf_txt)

    return {
        "nation_id": nid,
        "name": short_name or fallback_name,
        "full_name": full_name or fallback_name,
        "gdp": gdp,
        "gdp_per_capita": gdppc,
        "gdp_growth_pct": growth,
        "corporate_tax_pct": corporate["pct"],
        "corporate_tax_revenue": corporate["amount"],
        "income_tax_pct": income["pct"],
        "income_tax_desc": income["description"],
        "tariffs_pct": tariffs["pct"],
        "tariffs_desc": tariffs["description"],
        "tariffs_revenue": tariffs["amount"],
        "estate_tax_desc": estate["description"],
        "excise_tax_desc": excise["description"],
        "exit_tax_desc": exit_tax["description"],
        "exit_tax_pct": exit_tax["pct"],
        "total_revenue": total_rev,
        "total_expenditure": total_exp,
        "debt_to_gdp_pct": debt_gdp,
        "debt": debt,
        "interest_rate_pct": interest_rate,
        "surplus": surplus_amount,
        "budget_surplus_pct": budget_surplus_pct,
        "wealth_fund": wealth_fund,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse(only_id=None):
    if not RAW_DIR.exists():
        print(f"[parse] no {RAW_DIR}")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    names = {n["id"]: n["name"] for n in read_nations()}
    files = sorted(RAW_DIR.glob("*.html"))
    if only_id:
        files = [f for f in files if f.stem == only_id]

    print(f"[parse] {len(files)} nation pages")
    for path in files:
        nid = path.stem
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            data = parse_one(html, nid, names.get(nid, "Unknown"))
            out = DATA_DIR / f"{nid}.json"
            out.write_text(json.dumps(data, indent=2))
            print(f"  {nid:>3} {data['name'][:30]:30} corp={data['corporate_tax_pct']}% tariff={data['tariffs_pct']}% GDP=${(data['gdp'] or 0)/1e9:.1f}B")
        except Exception as e:
            print(f"  ERROR {nid}: {e}")


def aggregate():
    if not DATA_DIR.exists():
        return
    nations = []
    for f in sorted(DATA_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        try:
            nations.append(json.loads(f.read_text()))
        except Exception:
            continue
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(nations),
        "nations": nations,
    }
    AGGREGATE.write_text(json.dumps(out, indent=2))
    print(f"[aggregate] wrote {AGGREGATE.relative_to(REPO_ROOT)} ({len(nations)} nations)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--nation", type=str, default=None)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json")

    modes = [m for m in ("discover", "fetch", "parse", "aggregate") if getattr(args, m)]
    run_all = not modes

    if run_all or args.discover:
        discover(state_path)
    if run_all or args.fetch:
        fetch(state_path, only_id=args.nation, delay=args.delay)
    if run_all or args.parse:
        parse(only_id=args.nation)
    if run_all or args.aggregate:
        aggregate()


if __name__ == "__main__":
    main()
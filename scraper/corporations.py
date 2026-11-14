#!/usr/bin/env python3
"""
corporations.py — scrape national corporations + stock market,
join by corp_id, write data/corporations/latest.json.

Fetches:
  /national/corporations/1?page=N     (CEO, HQ, marketing, margin)
  /national/stockmarket/1?page=N       (symbol, shares, dividends, growth)

Merges by corp_id. GOP aggregates strict to party_id == 2.

Usage:
    python3 scraper/corporations.py
"""
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = REPO_ROOT / "data" / "corporations"
RAW_DIR = HERE / "raw" / "corporations"

COUNTRY_ID = 1
CORP_BASE = f"https://battleforthehill.com/national/corporations/{COUNTRY_ID}"
STOCK_BASE = f"https://battleforthehill.com/national/stockmarket/{COUNTRY_ID}"
STORAGE_STATE = HERE / "storage_state.json"
MAX_PAGES = 20
GOP_PARTY_ID = 2


def load_storage_state():
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def extract_num(text):
    if not text:
        return None
    cleaned = re.sub(r'[^\d.\-]', '', text.replace(',', ''))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Corporations page parsing
# ---------------------------------------------------------------------------
def parse_corp_row(tr):
    """Parse a <tr> from /national/corporations/1 table."""
    cells = tr.find_all('td')
    if len(cells) < 7:
        return None

    # Name cell: link + valuation + marketing strength
    name_cell = cells[0]
    corp_link = name_cell.find('a', href=re.compile(r'/parties/\d+/corporations/\d+'))
    if not corp_link:
        return None
    m = re.search(r'/parties/(\d+)/corporations/(\d+)', corp_link['href'])
    if not m:
        return None
    party_id = int(m.group(1))
    corp_id = int(m.group(2))
    name = corp_link.get_text(strip=True)

    val_span = name_cell.find('span', class_=re.compile('bloomberg-positive|bloomberg-negative'))
    valuation = extract_num(val_span.get_text()) if val_span else None

    ms_span = name_cell.find('span', class_='marketing-strength-tooltip')
    marketing_strength = extract_num(ms_span.get_text()) if ms_span else None
    marketing_increase = None
    if ms_span and ms_span.get('data-increase'):
        try:
            marketing_increase = float(ms_span['data-increase'])
        except ValueError:
            pass

    sector = cells[1].get('data-sort-value', '').strip()

    # CEO cell
    ceo_cell = cells[2]
    ceo_link = ceo_cell.find('a', href=re.compile(r'/politician/\d+'))
    ceo = None
    if ceo_link:
        ceo_m = re.search(r'/politician/(\d+)', ceo_link['href'])
        if ceo_m:
            ceo = {
                'politician_id': int(ceo_m.group(1)),
                'name': ceo_link.get_text(strip=True),
            }

    # HQ cell
    hq_cell = cells[3]
    hq_link = hq_cell.find('a', href=re.compile(r'/states/\d+/sectors'))
    hq = None
    if hq_link:
        hq_m = re.search(r'/states/(\d+)/', hq_link['href'])
        hq_span = hq_link.find('span', class_=re.compile('text-xs'))
        if hq_m:
            hq = {
                'state_id': int(hq_m.group(1)),
                'state': hq_span.get_text(strip=True) if hq_span else None,
            }

    stock_price = extract_num(cells[4].get('data-sort-value'))
    change_span = cells[4].find('span', class_=re.compile('bloomberg-(positive|negative)'))
    stock_change_pct = extract_num(change_span.get_text()) if change_span else None

    post_margin = extract_num(cells[5].get('data-sort-value'))
    profit = extract_num(cells[6].get('data-sort-value'))
    growth_pct = extract_num(cells[7].get('data-sort-value')) if len(cells) > 7 else None

    return {
        'corp_id': corp_id,
        'name': name,
        'party_id': party_id,
        'sector': sector,
        'valuation': valuation,
        'stock_price': stock_price,
        'stock_change_pct': stock_change_pct,
        'post_margin': post_margin,
        'profit': profit,
        'growth_pct': growth_pct,
        'marketing_strength': marketing_strength,
        'marketing_increase': marketing_increase,
        'ceo': ceo,
        'hq': hq,
        'is_vacant_ceo': ceo is None,
    }


# ---------------------------------------------------------------------------
# Stock market page parsing
# ---------------------------------------------------------------------------
def parse_stock_row(tr):
    """Parse a <tr> from /national/stockmarket/1 table."""
    cells = tr.find_all('td')
    if len(cells) < 6:
        return None

    sym_cell = cells[0]
    corp_link = sym_cell.find('a', href=re.compile(r'/parties/\d+/corporations/\d+'))
    if not corp_link:
        return None
    m = re.search(r'/parties/(\d+)/corporations/(\d+)', corp_link['href'])
    if not m:
        return None
    party_id = int(m.group(1))
    corp_id = int(m.group(2))
    symbol = corp_link.get_text(strip=True)

    val_div = sym_cell.find('div', class_=re.compile('text-sm.*font-semibold'))
    valuation = extract_num(val_div.get_text()) if val_div else None

    total_shares = extract_num(cells[1].get('data-sort-value'))

    shares_for_sale = extract_num(cells[2].get('data-sort-value'))
    pct_match = re.search(r'\(([\d.]+)%\)', cells[2].get_text())
    shares_for_sale_pct = float(pct_match.group(1)) if pct_match else 0.0

    sector = cells[3].get('data-sort-value', '').strip()

    stock_price = extract_num(cells[4].get('data-sort-value'))
    change_span = cells[4].find('span', class_=re.compile('text-(green|red)-400'))
    stock_change_pct = extract_num(change_span.get_text()) if change_span else None

    dividends = extract_num(cells[5].get('data-sort-value'))
    div_pct_match = re.search(r'\((\d+)%\)', cells[5].get_text())
    dividend_payout_pct = float(div_pct_match.group(1)) if div_pct_match else 0.0

    growth_pct = extract_num(cells[6].get('data-sort-value')) if len(cells) > 6 else None

    return {
        'corp_id': corp_id,
        'symbol': symbol,
        'party_id': party_id,
        'sector': sector,
        'valuation': valuation,
        'stock_price': stock_price,
        'stock_change_pct': stock_change_pct,
        'total_shares': total_shares,
        'shares_for_sale': shares_for_sale,
        'shares_for_sale_pct': shares_for_sale_pct,
        'dividends': dividends,
        'dividend_payout_pct': dividend_payout_pct,
        'growth_pct': growth_pct,
    }


# ---------------------------------------------------------------------------
# Page-level metadata (only on page 1 of the corp listing)
# ---------------------------------------------------------------------------
def parse_total_market_cap(html):
    m = re.search(r'data-total-market-cap="([\d.]+)"', html)
    return float(m.group(1)) if m else None


def parse_total_corporations(html):
    m = re.search(r'Total Corporations</p>\s*<p[^>]*>\s*(\d+)', html)
    return int(m.group(1)) if m else None


def parse_market_composition(html):
    m = re.search(r'var marketComposition\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return []


def has_next_page(soup, path, page_num):
    return soup.find('a', href=re.compile(rf'{path}\?page={page_num + 1}'))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    state = load_storage_state()
    if not state:
        print("[corps] no storage_state.json", file=sys.stderr)
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    corps = {}
    stock = {}
    total_market_cap = None
    total_corporations = None
    market_composition = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state)
        page = ctx.new_page()

        # --- Corporations listing ---
        print(f"[corps] corporations listing")
        for page_num in range(1, MAX_PAGES + 1):
            url = f"{CORP_BASE}?page={page_num}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[corps] page {page_num} failed: {e}", file=sys.stderr)
                if page_num == 1:
                    browser.close()
                    sys.exit(1)
                break

            html = page.content()
            (RAW_DIR / f"corp_{page_num}.html").write_text(html)

            if page_num == 1:
                total_market_cap = parse_total_market_cap(html)
                total_corporations = parse_total_corporations(html)
                market_composition = parse_market_composition(html)

            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.select('table tbody tr')
            if not rows:
                print(f"[corps] no rows on page {page_num}, stopping", file=sys.stderr)
                break

            added = 0
            for tr in rows:
                row = parse_corp_row(tr)
                if row and row['corp_id'] not in corps:
                    corps[row['corp_id']] = row
                    added += 1

            print(f"[corps] corp page {page_num}: {len(rows)} rows, {added} new")

            if not has_next_page(soup, f'corporations/{COUNTRY_ID}', page_num):
                break
            time.sleep(1.0)

        # --- Stock market listing ---
        print(f"[corps] stock market listing")
        for page_num in range(1, MAX_PAGES + 1):
            url = f"{STOCK_BASE}?page={page_num}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[corps] stock page {page_num} failed: {e}", file=sys.stderr)
                break

            html = page.content()
            (RAW_DIR / f"stock_{page_num}.html").write_text(html)

            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.select('table tbody tr')
            if not rows:
                break

            added = 0
            for tr in rows:
                entry = parse_stock_row(tr)
                if entry and entry['corp_id'] not in stock:
                    stock[entry['corp_id']] = entry
                    added += 1

            print(f"[corps] stock page {page_num}: {len(rows)} rows, {added} new")

            if not has_next_page(soup, f'stockmarket/{COUNTRY_ID}', page_num):
                break
            time.sleep(1.0)

        browser.close()

    # --- Merge stock data into corp records ---
    for corp_id, corp in corps.items():
        s = stock.get(corp_id, {})
        for key in ('symbol', 'total_shares', 'shares_for_sale',
                    'shares_for_sale_pct', 'dividends', 'dividend_payout_pct'):
            corp[key] = s.get(key)

    # --- Aggregates (strict GOP = party_id 2) ---
    all_corps = list(corps.values())
    gop = [c for c in all_corps if c['party_id'] == GOP_PARTY_ID]
    gop_valuation = sum(c['valuation'] or 0 for c in gop)
    gop_dividends = sum(c['dividends'] or 0 for c in gop)
    gop_profit = sum(c['profit'] or 0 for c in gop)

    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'country_id': COUNTRY_ID,
        'country': 'United States',
        'total_corporations': total_corporations or len(all_corps),
        'total_market_cap': total_market_cap,
        'gop_corp_count': len(gop),
        'gop_total_valuation': gop_valuation,
        'gop_total_dividends': gop_dividends,
        'gop_total_profit': gop_profit,
        'gop_market_share_pct': round(
            gop_valuation / total_market_cap * 100, 2
        ) if total_market_cap else None,
        'corporations': sorted(all_corps, key=lambda c: -(c['valuation'] or 0)),
        'market_composition': market_composition,
    }

    out_file = DATA_DIR / "latest.json"
    tmp = out_file.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(output, indent=2))
    tmp.replace(out_file)

    print(f"[corps] wrote {out_file.relative_to(REPO_ROOT)}")
    print(f"  total: {len(all_corps)} corps, ${(total_market_cap or 0)/1e9:.2f}B market cap")
    print(f"  GOP:   {len(gop)} corps, ${gop_valuation/1e9:.2f}B valuation "
          f"({output['gop_market_share_pct'] or 0:.1f}% of market)")
    print(f"         ${gop_dividends/1e6:.1f}M dividends, ${gop_profit/1e6:.1f}M profit")


if __name__ == '__main__':
    main()
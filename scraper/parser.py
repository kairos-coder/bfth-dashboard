#!/usr/bin/env python3
"""
parse.py - parse BFTH politician profile HTML into structured JSON.

Reads scraper/raw/*.html (saved by fetch.py), extracts stats, writes
data/players/latest.json.

Usage:
    python3 scraper/parse.py
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
RAW_DIR = HERE / "raw"
DATA_DIR = REPO_ROOT / "data"
PLAYERS_DIR = DATA_DIR / "players"
OUT_FILE = PLAYERS_DIR / "latest.json"


def text_of(node):
    """Return stripped text of a node, or None."""
    if node is None:
        return None
    return node.get_text(strip=True) or None


def money(text):
    """'$188,837' -> 188837 (int). Returns None if unparseable."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def number(text):
    """'13,174.8' -> 13174.8. '84.3%' -> 84.3. Returns None if unparseable."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def by_id(soup, elem_id):
    el = soup.find(id=elem_id)
    return text_of(el)


def row_value(soup, label):
    """Find a 'label' row and return the sibling text value.

    The BFTH layout wraps each stat in a div with two spans:
      <span>Label</span><span>Value</span>
    We search for the label span, then walk up to its parent row,
    then grab the next span.
    """
    label_el = soup.find(string=lambda s: s and s.strip() == label)
    if not label_el:
        return None
    row = label_el.find_parent("div")
    if not row:
        return None
    spans = row.find_all("span", recursive=False)
    if len(spans) >= 2:
        # Last span with text is usually the value
        for sp in reversed(spans):
            t = sp.get_text(strip=True)
            if t and t != label:
                return t
    return None


def extract_politician_id(url_or_filename):
    """Pull the numeric ID from a URL or filename."""
    m = re.search(r"(\d+)", url_or_filename)
    return m.group(1) if m else None


def parse_profile(html, profile_id):
    soup = BeautifulSoup(html, "html.parser")

    # --- name ---
    name = None
    name_el = soup.find("p", class_=lambda c: c and "text-3xl" in c)
    if name_el:
        name = text_of(name_el)

    # --- state ---
    state = None
    state_el = soup.find("img", src=lambda s: s and "/images/flags/" in s and "usa" not in s.split("/")[-1])
    if state_el:
        state = state_el.get("alt")

    # --- discord ---
    discord = row_value(soup, "Discord Username")

    # --- alt link ---
    alt = None
    alt_link = soup.find("a", href=lambda h: h and "/politician/" in h and "alt" in h.lower())
    # fallback: find the row labeled "Alt"
    alt_label = soup.find(string=lambda s: s and s.strip() == "Alt:")
    if alt_label:
        row = alt_label.find_parent("div")
        if row:
            a = row.find("a")
            if a:
                alt = {"name": text_of(a), "url": a.get("href")}

    # --- marriage ---
    marriage = row_value(soup, "Marriage:")

    # --- stats ---
    data = {
        "id": profile_id,
        "name": name,
        "state": state,
        "discord": discord,
        "alt": alt,
        "marriage": marriage,

        # stats
        "campaign_strength": number(by_id(soup, "campaign-strength-display")),
        "state_reputation": number(by_id(soup, "state-reputation-display")),
        "political_capital": number(by_id(soup, "jurisdiction-tooltip")),
        "campaign_funds": money(by_id(soup, "campaign-funds-tooltip")),
        "net_contributions_hr": money(by_id(soup, "net-contributions-tooltip")),
        "national_reputation": number(by_id(soup, "national-reputation-display")),
        "national_prestige": number(by_id(soup, "national-prestige-tooltip")),
        "controversy": number(by_id(soup, "controversy-display")),

        # money
        "liquid_capital": money(by_id(soup, "liquid-capital-tooltip")),
        "lc_income_hr": money(by_id(soup, "net-personal-income-tooltip")),
        "annual_lc_income": money(by_id(soup, "annual-lc-income-tooltip")),
        "total_net_worth": money(by_id(soup, "total-net-worth-tooltip")),
        "gold_oz": number(row_value(soup, "Gold")),
        "stocks_value": money(row_value(soup, "Stocks Value")),

        # military
        "military_influence": number(by_id(soup, "military-influence-tooltip")),

        # raw text
        "raw_stance_social": row_value(soup, "Social Stance"),
        "raw_stance_econ": row_value(soup, "Economic Stance"),
    }

    return data


def main():
    if not RAW_DIR.exists():
        sys.exit("no scraper/raw/ directory - run fetch.py first")

    html_files = sorted(RAW_DIR.glob("*.html"))
    if not html_files:
        sys.exit("no HTML files in scraper/raw/ - run fetch.py first")

    print(f"[parse] {len(html_files)} HTML files")

    players = []
    for path in html_files:
        profile_id = extract_politician_id(path.stem)
        html = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = parse_profile(html, profile_id)
        except Exception as e:
            print(f"  ERROR {path.name}: {e}")
            continue
        players.append(data)
        found = sum(1 for k, v in data.items() if v not in (None, "") and k not in ("id", "raw_stance_social", "raw_stance_econ"))
        print(f"  {data.get('name', path.stem):30s}  {found} fields")

    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "parse.py",
        "count": len(players),
        "players": players,
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[parse] wrote {OUT_FILE.relative_to(REPO_ROOT)} ({len(players)} players)")


if __name__ == "__main__":
    main()
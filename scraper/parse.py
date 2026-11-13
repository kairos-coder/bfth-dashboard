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
    if node is None:
        return None
    return node.get_text(strip=True) or None


def money(text):
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def number(text):
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


def profile_scope(soup):
    """Return the div wrapping the static politician cards.

    All stat rows (State, Stocks Value, etc.) live inside this div.
    Nav elements live outside it, so scoping here avoids false matches.
    """
    scope = soup.find("div", class_="static-politician-cards")
    if scope:
        return scope
    return soup.body or soup


def find_label_row(scope, label, exact=False):
    """Find the row div containing a span whose text is the label."""
    if scope is None:
        return None
    for span in scope.find_all("span"):
        t = span.get_text(strip=True)
        if not t:
            continue
        if exact:
            if t == label:
                return span.find_parent("div")
        else:
            if t.startswith(label):
                return span.find_parent("div")
    return None


def row_value(scope, label, exact=False):
    """Extract the value text from a labeled row inside the scope.

    Walks the row and returns the first span/div/a text that looks like
    a value (has a digit, starts with $, or contains %). Falls back to
    the last non-label candidate.
    """
    row = find_label_row(scope, label, exact=exact)
    if not row:
        return None

    candidates = []
    for el in row.find_all(["span", "div", "a"]):
        t = el.get_text(strip=True)
        if not t:
            continue
        if t == label or t == label + ":":
            continue
        if t.startswith(label) and len(t) <= len(label) + 2:
            continue
        candidates.append(t)

    if not candidates:
        return None

    for c in candidates:
        if any(ch.isdigit() for ch in c) or c.startswith("$") or "%" in c:
            return c
    return candidates[-1]


def state_name(scope):
    """Find the State row inside the profile scope and return flag alt."""
    row = find_label_row(scope, "State", exact=True)
    if not row:
        return None
    img = row.find("img")
    if img and img.get("alt"):
        alt = img["alt"].strip()
        if alt and alt.lower() != "united states":
            return alt
    return None


def profile_image(soup):
    """Extract the profile owner's image URL.

    The nav bar has an <img> for the currently-logged-in user; the
    profile owner's image is in the masthead. We try the masthead first
    and fall back to the last /images/profile/ image on the page.
    """
    masthead = soup.find("div", class_=lambda c: c and "wn-masthead" in str(c))
    if masthead:
        img = masthead.find("img", src=lambda s: s and "/images/profile/" in s)
        if img and img.get("src"):
            return img["src"]

    imgs = soup.find_all("img", src=lambda s: s and "/images/profile/" in s)
    if imgs:
        return imgs[-1].get("src")
    return None


def extract_politician_id(name):
    m = re.search(r"(\d+)", name)
    return m.group(1) if m else None


def is_npc(data):
    """NPCs have names ending in 'NPC' and no discord handle."""
    name = data.get("name") or ""
    return name.endswith("NPC")


def parse_profile(html, profile_id):
    soup = BeautifulSoup(html, "html.parser")

    scope = profile_scope(soup)

    # --- name ---
    name = None
    name_el = soup.find("p", class_=lambda c: c and "text-3xl" in c)
    if name_el:
        name = text_of(name_el)

    # --- state ---
    state = state_name(scope)

    # --- discord ---
    discord = row_value(scope, "Discord Username", exact=False)

    # --- alt ---
    alt = None
    alt_row = find_label_row(scope, "Alt", exact=False)
    if alt_row:
        a = alt_row.find("a")
        if a:
            alt = {"name": text_of(a), "url": a.get("href")}

    # --- marriage ---
    marriage = row_value(scope, "Marriage", exact=False)

    # --- gold and stocks ---
    gold = row_value(scope, "Gold", exact=True)
    stocks = row_value(scope, "Stocks Value", exact=False)

    # --- profile image ---
    img_url = profile_image(soup)

    # --- stats by element id ---
    data = {
        "id": profile_id,
        "name": name,
        "profile_image": img_url,
        "state": state,
        "discord": discord,
        "alt": alt,
        "marriage": marriage,

        "campaign_strength": number(by_id(soup, "campaign-strength-display")),
        "state_reputation": number(by_id(soup, "state-reputation-display")),
        "political_capital": number(by_id(soup, "jurisdiction-tooltip")),
        "campaign_funds": money(by_id(soup, "campaign-funds-tooltip")),
        "net_contributions_hr": money(by_id(soup, "net-contributions-tooltip")),
        "national_reputation": number(by_id(soup, "national-reputation-display")),
        "national_prestige": number(by_id(soup, "national-prestige-tooltip")),
        "controversy": number(by_id(soup, "controversy-display")),

        "liquid_capital": money(by_id(soup, "liquid-capital-tooltip")),
        "lc_income_hr": money(by_id(soup, "net-personal-income-tooltip")),
        "annual_lc_income": money(by_id(soup, "annual-lc-income-tooltip")),
        "total_net_worth": money(by_id(soup, "total-net-worth-tooltip")),
        "gold_oz": number(gold),
        "stocks_value": money(stocks),

        "military_influence": number(by_id(soup, "military-influence-tooltip")),

        "raw_stance_social": row_value(scope, "Social Stance", exact=False),
        "raw_stance_econ": row_value(scope, "Economic Stance", exact=False),
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
    npc_count = 0
    for path in html_files:
        profile_id = extract_politician_id(path.stem)
        html = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = parse_profile(html, profile_id)
        except Exception as e:
            print(f"  ERROR {path.name}: {e}")
            continue

        if is_npc(data):
            npc_count += 1
            continue

        players.append(data)
        skip = {"id", "raw_stance_social", "raw_stance_econ"}
        found = sum(1 for k, v in data.items() if k not in skip and v not in (None, "", {}))
        print(f"  {str(data.get('name', path.stem)):30s}  {found} fields")

    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "parse.py",
        "count": len(players),
        "npc_filtered": npc_count,
        "players": players,
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[parse] wrote {OUT_FILE.relative_to(REPO_ROOT)} ({len(players)} players, {npc_count} NPCs filtered)")


if __name__ == "__main__":
    main()
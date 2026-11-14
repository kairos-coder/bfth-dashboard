#!/usr/bin/env python3
"""
parse.py - parse BFTH politician profile HTML into structured JSON.

Reads scraper/raw/*.html (saved by fetch.py), extracts stats, writes
data/players/latest.json.

v3.1:
  - caucus_id + caucus_name extracted from profile body (NOT nav dropdown)
  - party_id + party_name from profile body
  - state_party_id + state_party_name + state_id from profile body
  - stance_value_social + stance_value_econ (parsed from raw strings)

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
    """Extract the value text from a labeled row inside the scope."""
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
    """Extract the profile owner's image URL."""
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


# ============================================================
# v3.1: caucus + party extraction, scoped to profile body
# ============================================================
def _is_nav_link(a):
    """Return True if this <a> is part of the nav dropdown (logged-in user's)."""
    classes = a.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if "wn-nav-link" in classes:
        return True
    if a.find_parent(class_="wn-nav-link"):
        return True
    if a.find_parent(class_="wn-nav-kicker"):
        return True
    return False


def extract_caucus(soup):
    """Extract caucus from the profile body, NOT the nav dropdown.

    The nav dropdown shows the LOGGED-IN user's caucus on every page
    (always 172 for us, since we fetch with Taurineaux's session).

    The profile owner's caucus is a link with
    style="color: ...; text-decoration: none; display: flex; align-items: center;"
    inside the profile card — no wn-nav-link class.

    Returns (caucus_id, caucus_name) tuple.
    """
    for a in soup.find_all("a", href=re.compile(r"/parties/\d+/caucuses/\d+")):
        href = a.get("href", "")

        # Skip nav dropdown links
        if _is_nav_link(a):
            continue

        # Skip "caucus elections" sub-links
        if "/elections" in href:
            continue

        m = re.search(r"/parties/\d+/caucuses/(\d+)", href)
        if not m:
            continue

        caucus_id = int(m.group(1))
        caucus_name = a.get_text(strip=True) or None

        # Require a real name (not generic "Caucus", not empty)
        if caucus_name and len(caucus_name) > 3 and caucus_name.lower() != "caucus":
            return caucus_id, caucus_name

    return None, None


def extract_party(soup):
    """Extract national party from profile body, NOT the nav dropdown.

    Excludes:
      - nav dropdown links (wn-nav-link class)
      - /national/parties/N (Party List)
      - /parties/N/caucuses/M
      - /parties/N/corporations, /admin, /elections, etc.
    """
    EXCLUDED_SUFFIXES = (
        "caucuses", "corporations", "admin", "elections",
        "national-committee", "wealthLIST", "corporationsMARKET",
    )

    for a in soup.find_all("a", href=re.compile(r"/parties/\d+")):
        href = a.get("href", "")

        # Skip nav dropdown links
        if _is_nav_link(a):
            continue

        m = re.search(r"/parties/(\d+)(?:$|/)", href)
        if not m:
            continue

        # Skip excluded suffixes
        if any(f"/{suf}" in href for suf in EXCLUDED_SUFFIXES):
            continue

        # Skip /national/parties/N (party list, not our party)
        if "/national/parties/" in href:
            continue

        party_id = int(m.group(1))
        party_name = a.get_text(strip=True) or None

        if party_name and len(party_name) > 3:
            return party_id, party_name

    return None, None


def extract_state_party(soup):
    """Extract state party from profile body, NOT the nav dropdown.

    Returns (state_party_id, state_party_name, state_id) tuple.
    """
    for a in soup.find_all("a", href=re.compile(r"/states/\d+/parties/\d+(?:$|/)")):
        href = a.get("href", "")

        if _is_nav_link(a):
            continue
        if "/admin" in href or "/elections" in href:
            continue

        m = re.search(r"/states/(\d+)/parties/(\d+)", href)
        if not m:
            continue

        state_id = int(m.group(1))
        state_party_id = int(m.group(2))
        link_text = a.get_text(strip=True) or None

        return state_party_id, link_text, state_id

    return None, None, None


# ============================================================
# v3.1: stance value extraction
# ============================================================
def parse_stance_value(raw):
    """Parse 'Center-Right (1.68)' -> 1.68. Returns None if not parseable."""
    if not raw:
        return None
    m = re.search(r"\(([\d.]+)\)", raw)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


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

    # --- v3.1: caucus + party + state party from profile body ---
    caucus_id, caucus_name = extract_caucus(soup)
    party_id, party_name = extract_party(soup)
    state_party_id, state_party_name, state_id = extract_state_party(soup)

    # --- v3.1: stance values ---
    raw_stance_social = row_value(scope, "Social Stance", exact=False)
    raw_stance_econ = row_value(scope, "Economic Stance", exact=False)

    # --- stats by element id ---
    data = {
        "id": profile_id,
        "name": name,
        "profile_image": img_url,
        "state": state,
        "state_id": state_id,
        "discord": discord,
        "alt": alt,
        "marriage": marriage,

        # v3.1 identity fields
        "party_id": party_id,
        "party_name": party_name,
        "caucus_id": caucus_id,
        "caucus_name": caucus_name,
        "state_party_id": state_party_id,
        "state_party_name": state_party_name,

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

        # Raw strings kept for backwards compat + parsed values
        "raw_stance_social": raw_stance_social,
        "raw_stance_econ": raw_stance_econ,
        "stance_value_social": parse_stance_value(raw_stance_social),
        "stance_value_econ": parse_stance_value(raw_stance_econ),
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
    caucus_hits = 0
    party_hits = 0
    caucus_names = {}
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

        if data.get("caucus_id"):
            caucus_hits += 1
            cn = data.get("caucus_name") or f"#{data['caucus_id']}"
            caucus_names[cn] = caucus_names.get(cn, 0) + 1
        if data.get("party_id"):
            party_hits += 1

        players.append(data)
        skip = {"id", "raw_stance_social", "raw_stance_econ"}
        found = sum(1 for k, v in data.items() if k not in skip and v not in (None, "", {}))
        marker = ""
        if data.get("caucus_name"):
            marker = f" [{data['caucus_name']}]"
        print(f"  {str(data.get('name', path.stem)):30s}  {found} fields{marker}")

    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "parse.py",
        "count": len(players),
        "npc_filtered": npc_count,
        "caucus_hits": caucus_hits,
        "party_hits": party_hits,
        "caucus_distribution": dict(sorted(caucus_names.items(), key=lambda kv: -kv[1])),
        "players": players,
    }
    body = json.dumps(payload, indent=2)

    OUT_FILE.write_text(body)
    print(f"[parse] wrote {OUT_FILE.relative_to(REPO_ROOT)} "
          f"({len(players)} players, {npc_count} NPCs filtered, "
          f"{caucus_hits} with caucus, {party_hits} with party)")

    if caucus_names:
        print(f"[parse] caucus distribution:")
        for name, n in sorted(caucus_names.items(), key=lambda kv: -kv[1]):
            print(f"          {n:3d}  {name}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    archive = PLAYERS_DIR / f"{stamp}.json"
    archive.write_text(body)
    print(f"[parse] archived {archive.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
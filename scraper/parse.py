#!/usr/bin/env python3
"""
parse.py - parse politician HTML into latest.json, with day-over-day and
week-over-week deltas baked in.

Output structure (data/players/latest.json):
{
  "generated_at": "...",
  "count": 64,
  "npc_filtered": 61,
  "baselines": {
    "day":  {"ts": "...", "file": "2026-11-13T21.json"},
    "week": {"ts": "...", "file": "2026-11-06T00.json"}
  },
  "players": [
    {
      "id": "1239", "name": "Greg Abbott", "state": "West Virginia",
      "national_prestige": 16762.8, "campaign_strength": 100.0,
      "campaign_funds": 1800000, "total_net_worth": 105900000,
      "lc_income_hr": 16000, ...,
      "delta": {
        "day":  {"national_prestige": 127.5, "campaign_strength": 0.0,
                 "campaign_funds": -42000, "total_net_worth": 85000,
                 "lc_income_hr": 0, "state_reputation": 0.0,
                 "national_reputation": 0.0},
        "week": {"national_prestige": 890.2, ...}
      }
    }
  ]
}

Baselines:
  - day:  newest archive whose date is strictly before today's UTC date
  - week: newest archive that is >=7 days before today (falls back to oldest
          pre-today archive if no 7-day-old snapshot exists yet)

Deltas are null when no baseline is available for a given horizon.

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
PLAYERS_DIR = REPO_ROOT / "data" / "players"
LATEST = PLAYERS_DIR / "latest.json"

# archive filenames look like 2026-11-13T21.json
ARCHIVE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})\.json$")

# minimum markers we expect on a valid politician page
MARKERS = ["National Prestige", "Campaign Strength", "State Reputation"]


# ─────────────────────────────────────────────────────────────────────────────
# scalar extraction helpers (same logic as before, cleaned up)
# ─────────────────────────────────────────────────────────────────────────────

def _text(soup):
    return soup.get_text(" ", strip=True)


def _money(s):
    """'$1,234,567' or '$1.23M' or '1,234' -> float."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("-").replace("$", "").replace(",", "").strip()
    mult = 1
    if s.endswith("B") or s.endswith("b"):
        mult, s = 1e9, s[:-1]
    elif s.endswith("M") or s.endswith("m"):
        mult, s = 1e6, s[:-1]
    elif s.endswith("K") or s.endswith("k"):
        mult, s = 1e3, s[:-1]
    try:
        v = float(s) * mult
    except ValueError:
        return None
    return -v if neg else v


def _pct(s):
    """'54.3%' -> 54.3."""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def _num(s):
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def _find_value_after_label(soup, label, parser):
    """Search text nodes for a label, take the next sibling's text, parse it."""
    el = soup.find(string=re.compile(re.escape(label), re.IGNORECASE))
    if not el:
        return None
    parent = el.find_parent()
    if parent:
        sib = parent.find_next_sibling()
        if sib:
            return parser(_text(sib))
        # fallback: parse the parent text minus the label
        parent_text = _text(parent).replace(label, "").strip()
        return parser(parent_text)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# profile parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_profile(html):
    """Parse one politician HTML page -> dict of fields."""
    soup = BeautifulSoup(html, "html.parser")

    # ---- header block: name, state, politician ID, image ----
    name_el = soup.select_one("h1")
    name = _text(name_el) if name_el else None

    # politician ID from canonical link
    pid = None
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        m = re.search(r"/politician/(\d+)", canonical["href"])
        if m:
            pid = m.group(1)
    if not pid:
        # fallback: any /politician/<id> link on the page
        a = soup.find("a", href=re.compile(r"/politician/\d+"))
        if a:
            m = re.search(r"/politician/(\d+)", a["href"])
            if m:
                pid = m.group(1)

    # state — look for "State:" label
    state = _find_value_after_label(soup, "State", lambda s: s.strip() or None)

    # profile image
    profile_image = None
    img = soup.select_one("img[src*='/images/profile/']")
    if img:
        src = img.get("src", "")
        if src.startswith("/"):
            profile_image = "https://battleforthehill.com" + src
        else:
            profile_image = src

    # discord handle
    discord = _find_value_after_label(soup, "Discord", lambda s: s.strip() or None)

    # ---- alt account ----
    alt = None
    alt_link = soup.find("a", string=re.compile(r"Alt", re.IGNORECASE))
    if alt_link:
        alt_name = _text(alt_link).replace("Alt:", "").strip() or None
        alt_url = alt_link.get("href")
        if alt_name:
            alt = {"name": alt_name, "url": alt_url}

    # ---- marriage ----
    marriage = _find_value_after_label(soup, "Married", lambda s: s.strip() or None)
    if not marriage:
        marriage = _find_value_after_label(soup, "Spouse", lambda s: s.strip() or None)

    # ---- numeric stats ----
    np_val      = _find_value_after_label(soup, "National Prestige", _num)
    cs_val      = _find_value_after_label(soup, "Campaign Strength", _num)
    sr_val      = _find_value_after_label(soup, "State Reputation", _pct)
    nr_val      = _find_value_after_label(soup, "National Reputation", _pct)
    pc_val      = _find_value_after_label(soup, "Political Capital", _num)
    cf_val      = _find_value_after_label(soup, "Campaign Funds", _money)
    nw_val      = _find_value_after_label(soup, "Net Worth", _money)
    lc_val      = _find_value_after_label(soup, "Liquid Capital", _money)
    lc_hr_val   = _find_value_after_label(soup, "LC / hr", _money) \
                  or _find_value_after_label(soup, "LC/hr", _money) \
                  or _find_value_after_label(soup, "Income / hr", _money)
    lc_ann_val  = _find_value_after_label(soup, "Annual LC", _money)
    nc_hr_val   = _find_value_after_label(soup, "Net Contributions / hr", _money) \
                  or _find_value_after_label(soup, "Contributions / hr", _money)
    mil_val     = _find_value_after_label(soup, "Military Influence", _num)
    contro_val  = _find_value_after_label(soup, "Controversy", _num)
    gold_val    = _find_value_after_label(soup, "Gold", _num)
    stocks_val  = _find_value_after_label(soup, "Stocks", _money)

    # ---- stance strings (leave as raw text for later parsing) ----
    ss = _find_value_after_label(soup, "Social Stance", lambda s: s.strip() or None)
    es = _find_value_after_label(soup, "Economic Stance", lambda s: s.strip() or None)

    return {
        "id": pid,
        "name": name,
        "profile_image": profile_image,
        "state": state,
        "discord": discord,
        "alt": alt,
        "marriage": marriage,
        "national_prestige":      np_val,
        "campaign_strength":      cs_val,
        "state_reputation":       sr_val,
        "national_reputation":    nr_val,
        "political_capital":      pc_val,
        "campaign_funds":         cf_val,
        "net_contributions_hr":   nc_hr_val,
        "total_net_worth":        nw_val,
        "liquid_capital":         lc_val,
        "lc_income_hr":           lc_hr_val,
        "annual_lc_income":       lc_ann_val,
        "military_influence":     mil_val,
        "controversy":            contro_val,
        "gold_oz":                gold_val,
        "stocks_value":           stocks_val,
        "raw_stance_social":      ss,
        "raw_stance_econ":        es,
    }


def is_npc(profile):
    """NPC detection - same heuristic as before."""
    name = (profile.get("name") or "").lower()
    if "npc" in name:
        return True
    # missing discord is a strong signal, but some dormant players lack it too
    return False


# ─────────────────────────────────────────────────────────────────────────────
# delta computation
# ─────────────────────────────────────────────────────────────────────────────

def load_baseline(path):
    try:
        data = json.loads(path.read_text())
        return {
            "ts": data.get("generated_at"),
            "file": path.name,
            "by_id": {str(p.get("id")): p for p in data.get("players", []) if p.get("id")},
        }
    except Exception as e:
        print(f"  WARN: could not load baseline {path.name}: {e}")
        return None


def find_baseline_day(today_str):
    """Newest archive strictly before today."""
    candidates = []
    for f in PLAYERS_DIR.glob("*.json"):
        m = ARCHIVE_RE.match(f.name)
        if m and m.group(1) < today_str:
            candidates.append((m.group(1), m.group(2), f.name, f))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return load_baseline(candidates[-1][3])


def find_baseline_week(today_str):
    """Newest archive >=7 days before today. Falls back to oldest pre-today archive."""
    today_dt = datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    seven_ago = []
    all_prior = []
    for f in PLAYERS_DIR.glob("*.json"):
        m = ARCHIVE_RE.match(f.name)
        if not m:
            continue
        date_part = m.group(1)
        if date_part >= today_str:
            continue
        all_prior.append((date_part, m.group(2), f.name, f))
        try:
            archive_dt = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (today_dt - archive_dt).days >= 7:
            seven_ago.append((date_part, m.group(2), f.name, f))

    if seven_ago:
        seven_ago.sort(key=lambda x: (x[0], x[1], x[2]))
        return load_baseline(seven_ago[-1][3])
    if all_prior:
        all_prior.sort(key=lambda x: (x[0], x[1], x[2]))
        return load_baseline(all_prior[0][3])
    return None


def diff_fields(cur, prev):
    """Return delta dict or None if prev is missing."""
    if not prev:
        return None

    def d(field):
        cv = cur.get(field)
        pv = prev.get(field)
        if cv is None or pv is None:
            return None
        return round(cv - pv, 4)

    return {
        "national_prestige":    d("national_prestige"),
        "campaign_strength":    d("campaign_strength"),
        "campaign_funds":       d("campaign_funds"),
        "total_net_worth":      d("total_net_worth"),
        "lc_income_hr":         d("lc_income_hr"),
        "state_reputation":     d("state_reputation"),
        "national_reputation":  d("national_reputation"),
    }


def attach_deltas(players, baseline_day, baseline_week):
    """Attach delta.day / delta.week to each player."""
    day_by_id = baseline_day["by_id"] if baseline_day else {}
    week_by_id = baseline_week["by_id"] if baseline_week else {}

    for p in players:
        pid = str(p.get("id"))
        p["delta"] = {
            "day":  diff_fields(p, day_by_id.get(pid)),
            "week": diff_fields(p, week_by_id.get(pid)),
        }

    return {
        "day": {
            "ts": baseline_day["ts"] if baseline_day else None,
            "file": baseline_day["file"] if baseline_day else None,
        },
        "week": {
            "ts": baseline_week["ts"] if baseline_week else None,
            "file": baseline_week["file"] if baseline_week else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not RAW_DIR.exists():
        sys.exit(f"no {RAW_DIR} — run fetch.py first")

    html_files = sorted(RAW_DIR.glob("politician-*.html"))
    if not html_files:
        # fallback: fetch.py may save with different naming
        html_files = sorted(RAW_DIR.glob("*.html"))
    if not html_files:
        sys.exit(f"no HTML files in {RAW_DIR}")

    print(f"[parse] {len(html_files)} HTML files")

    players = []
    npc_count = 0
    for path in html_files:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            profile = parse_profile(html)
            if not profile.get("name"):
                continue
            if is_npc(profile):
                npc_count += 1
                print(f"  {profile['name']:30} (NPC — filtered)")
                continue
            # count non-empty fields for the summary line
            field_count = sum(1 for v in profile.values() if v not in (None, "", 0, []))
            print(f"  {profile['name']:30} {field_count} fields")
            players.append(profile)
        except Exception as e:
            print(f"  ERROR {path.name}: {e}")

    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- attach deltas ----
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    baseline_day = find_baseline_day(today_str)
    baseline_week = find_baseline_week(today_str)

    print(f"[parse] today: {today_str}")
    if baseline_day:
        print(f"[parse] day baseline:  {baseline_day['file']}  ({baseline_day['ts']})")
    else:
        print(f"[parse] day baseline:  none (no prior-day archive)")
    if baseline_week:
        print(f"[parse] week baseline: {baseline_week['file']}  ({baseline_week['ts']})")
    else:
        print(f"[parse] week baseline: none")

    baselines = attach_deltas(players, baseline_day, baseline_week)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(players),
        "npc_filtered": npc_count,
        "baselines": baselines,
        "players": players,
    }

    LATEST.write_text(json.dumps(output, indent=2))
    print(f"[parse] wrote {LATEST.relative_to(REPO_ROOT)} ({len(players)} players, {npc_count} NPCs filtered)")

    # ---- archive a copy ----
    hour_str = datetime.now(timezone.utc).strftime("%H")
    archive_path = PLAYERS_DIR / f"{today_str}T{hour_str}.json"
    archive_path.write_text(json.dumps(output, indent=2))
    print(f"[parse] archived {archive_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
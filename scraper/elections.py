#!/usr/bin/env python3
"""
elections.py - full elections pipeline in one shot.

1. discover: fetch /elections/overview, parse mapRaceLeans, write urls/elections.txt
2. fetch:    for each election, grab election page HTML + one sample poll
3. parse:    extract metadata + pollingHistory, write data/elections/<eid>/election.json,
             append to data/elections/history.jsonl

Usage:
    python3 scraper/elections.py                    # full pipeline
    python3 scraper/elections.py --discover         # only step 1
    python3 scraper/elections.py --fetch            # only step 2
    python3 scraper/elections.py --parse            # only step 3
    python3 scraper/elections.py --election 19474 --fetch --parse   # single election
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
URLS_DIR = HERE / "urls"
URLS_FILE = URLS_DIR / "elections.txt"
RAW_ELEC = HERE / "raw" / "elections"
RAW_POLLS = HERE / "raw" / "polls"
DATA_DIR = REPO_ROOT / "data" / "elections"

BASE = "https://battleforthehill.com"
OVERVIEW_URL = f"{BASE}/elections/overview"


# ─────────────────────────────────────────────────────────────────────────
# shared helpers
# ─────────────────────────────────────────────────────────────────────────

def load_storage_state():
    raw = os.environ.get("BFTH_STORAGE_STATE_B64", "").strip()
    if raw:
        p = HERE / "storage_state.ci.json"
        p.write_bytes(base64.b64decode(raw))
        return str(p)
    local = HERE / "storage_state.json"
    return str(local) if local.exists() else None


def goto_with_retry(page, url, timeout=30000, settle_ms=1500, retries=2):
    """goto with domcontentloaded + fixed settle time + retry on timeout."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            return True
        except Exception as e:
            last_err = e
            if attempt < retries:
                print(f"    retry {attempt+1}/{retries} after: {type(e).__name__}")
                time.sleep(2)
    raise last_err


def read_urls():
    if not URLS_FILE.exists():
        return []
    out = []
    for line in URLS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: <eid> <url> <sid> <type> "<label>" <lean>
        # Label is quoted and may contain spaces. Use regex.
        m = re.match(
            r'^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"([^"]*)"\s+(\S+)\s*$',
            line
        )
        if not m:
            # fallback: old space-split (in case an unquoted line snuck in)
            parts = line.split(None, 5)
            if len(parts) < 2:
                continue
            out.append({
                "eid": parts[0],
                "url": parts[1],
                "sid": parts[2] if len(parts) > 2 else "",
                "type": parts[3] if len(parts) > 3 else "",
                "label": parts[4].strip('"') if len(parts) > 4 else "",
                "overview_lean": 0.0,
            })
            continue

        eid, url, sid, typ, label, lean_str = m.groups()
        try:
            lean = float(lean_str)
        except ValueError:
            lean = 0.0

        out.append({
            "eid": eid,
            "url": url,
            "sid": sid,
            "type": typ,
            "label": label,
            "overview_lean": lean,
        })
    return out


def extract_polling_history(html):
    m = re.search(r'(?:var|let|const)\s+pollingHistory\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# step 1: discover
# ─────────────────────────────────────────────────────────────────────────

def extract_race_leans(html):
    m = re.search(r'(?:var|let|const)\s+mapRaceLeans\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(1).replace('\\/', '/'))
    except Exception as e:
        print(f"  WARN: failed to parse mapRaceLeans: {e}")
        return []


def discover(state_path):
    URLS_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()
        print("[discover] fetching /elections/overview")
        try:
            goto_with_retry(page, OVERVIEW_URL, settle_ms=1000)
        except Exception as e:
            print(f"  ERROR loading overview: {e}")
            browser.close()
            return 0
        html = page.content()
        browser.close()

    races = extract_race_leans(html)
    if not races:
        print("  no races found in mapRaceLeans")
        URLS_FILE.write_text("# no active races\n")
        return 0

    seen = {}
    for r in races:
        eid = r.get("election_id")
        url = r.get("url")
        if eid and url and str(eid) not in seen:
            seen[str(eid)] = {
                "eid": str(eid),
                "url": url,
                "sid": str(r.get("state_id", "")),
                "type": r.get("type", ""),
                "label": r.get("label", ""),
                "lean": r.get("lean", 0),
                "lean_label": r.get("lean_label"),
            }

    lines = []
    for v in sorted(seen.values(), key=lambda x: int(x["eid"])):
        lines.append(
            f"{v['eid']} {v['url']} {v['sid']} {v['type']} "
            f"\"{v['label']}\" {v['lean']}"
        )
    URLS_FILE.write_text("\n".join(lines) + "\n")
    print(f"[discover] wrote {len(seen)} active elections to urls/elections.txt")
    return len(seen)


# ─────────────────────────────────────────────────────────────────────────
# step 2: fetch
# ─────────────────────────────────────────────────────────────────────────

def extract_poll_urls(html):
    return set(re.findall(r'/states/\d+/elections/\d+/poll/\d+', html))


def fetch(state_path, only_eid=None, delay=1.5):
    RAW_ELEC.mkdir(parents=True, exist_ok=True)
    RAW_POLLS.mkdir(parents=True, exist_ok=True)

    elections = read_urls()
    if only_eid:
        elections = [e for e in elections if e["eid"] == only_eid]
    if not elections:
        print("[fetch] no elections to fetch")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        for i, e in enumerate(elections, 1):
            eid = e["eid"]
            out = RAW_ELEC / f"{eid}.html"
            if out.exists():
                print(f"[fetch {i}/{len(elections)}] {eid} (cached)")
                continue

            print(f"[fetch {i}/{len(elections)}] {eid} ({e['type']})")
            try:
                goto_with_retry(page, e["url"], settle_ms=1500)
                html = page.content()
                out.write_text(html, encoding="utf-8")

                ph = extract_polling_history(html)
                if ph:
                    print(f"  pollingHistory embedded ({len(ph)} chars)")
                else:
                    polls = extract_poll_urls(html)
                    print(f"  pollingHistory missing; {len(polls)} poll URLs found")
                    if polls:
                        newest = max(polls, key=lambda u: int(re.search(r'/poll/(\d+)', u).group(1)))
                        pid = re.search(r'/poll/(\d+)', newest).group(1)
                        poll_out = RAW_POLLS / f"{pid}.html"
                        if not poll_out.exists():
                            try:
                                goto_with_retry(page, f"{BASE}{newest}", settle_ms=1000, retries=1)
                                poll_out.write_text(page.content(), encoding="utf-8")
                                print(f"  fetched sample poll {pid}")
                            except Exception as pe:
                                print(f"  poll fetch failed: {pe}")
            except Exception as ex:
                print(f"  ERROR: {ex}")

            time.sleep(delay)

        browser.close()


# ─────────────────────────────────────────────────────────────────────────
# step 3: parse
# ─────────────────────────────────────────────────────────────────────────

def parse_candidates(soup):
    candidates = []
    seen_names = set()
    for p in soup.find_all("p", class_=re.compile(r"text-lg.*font-semibold")):
        name = p.get_text(strip=True)
        if not name or len(name) > 80 or name in seen_names:
            continue
        seen_names.add(name)

        pid = None
        a = p.find_parent("a")
        if a and a.get("href"):
            m = re.search(r"/politician/(\d+)", a["href"])
            if m:
                pid = m.group(1)

        pct = None
        row = p.find_parent("tr") or p.find_parent("div", class_=re.compile(r"flex|grid"))
        if row:
            m = re.search(r"(\d+\.\d+)%", row.get_text())
            if m:
                pct = float(m.group(1))

        candidates.append({"name": name, "politician_id": pid, "final_pct": pct})
    return candidates


def parse_one(html, eid, url_meta):
    soup = BeautifulSoup(html, "html.parser")
    meta = url_meta.get(eid, {})

    ph = extract_polling_history(html)
    polls = []
    polls_source = "unavailable"
    if ph:
        n = max((len(c.get("history", [])) for c in ph), default=0)
        for i in range(n):
            entry = {"index": i + 1, "results": {}}
            for c in ph:
                h = c.get("history", [])
                if i < len(h):
                    entry["results"][c.get("name", "?")] = h[i].get("polling")
                    entry["date"] = h[i].get("date")
            polls.append(entry)
        polls_source = "pollingHistory"

    return {
        "election_id": eid,
        "state_id": meta.get("sid", ""),
        "type": meta.get("type", ""),
        "label": meta.get("label", ""),
        "overview_lean": meta.get("overview_lean", 0),
        "url": meta.get("url", ""),
        "candidates": parse_candidates(soup),
        "polls": polls,
        "polls_count": len(polls),
        "polls_source": polls_source,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_and_write(eid, new_data):
    e_dir = DATA_DIR / eid
    e_dir.mkdir(parents=True, exist_ok=True)
    f = e_dir / "election.json"

    if f.exists():
        try:
            old = json.loads(f.read_text())
            if len(old.get("polls", [])) > len(new_data.get("polls", [])):
                new_data["polls"] = old["polls"]
                new_data["polls_count"] = len(old["polls"])
                new_data["polls_source"] = old.get("polls_source")
            if not new_data.get("candidates") and old.get("candidates"):
                new_data["candidates"] = old["candidates"]
        except Exception:
            pass

    f.write_text(json.dumps(new_data, indent=2))
    return new_data


def append_history(new_data):
    hist = DATA_DIR / "history.jsonl"
    line = {
        "ts": new_data["parsed_at"],
        "election_id": new_data["election_id"],
        "type": new_data["type"],
        "state_id": new_data["state_id"],
        "label": new_data["label"],
        "polls_count": new_data["polls_count"],
        "lean": new_data["overview_lean"],
        "leader_pct": max(
            (c.get("final_pct") for c in new_data.get("candidates", [])
             if c.get("final_pct") is not None),
            default=None,
        ),
    }
    with hist.open("a") as f:
        f.write(json.dumps(line) + "\n")


def parse(only_eid=None):
    if not RAW_ELEC.exists():
        print("[parse] no raw/elections/ - run fetch first")
        return

    files = sorted(RAW_ELEC.glob("*.html"))
    if only_eid:
        files = [f for f in files if f.stem == only_eid]
    if not files:
        print("[parse] no election HTML files")
        return

    url_meta = {e["eid"]: e for e in read_urls()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[parse] {len(files)} election HTML files")
    ok, fail = 0, 0
    for path in files:
        eid = path.stem
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            data = parse_one(html, eid, url_meta)
            data = merge_and_write(eid, data)
            append_history(data)
            print(f"  {eid}: {data['polls_count']} polls ({data['polls_source']})")
            ok += 1
        except Exception as ex:
            print(f"  ERROR {eid}: {ex}")
            fail += 1

    print(f"[parse] done: {ok} ok, {fail} failed")


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="only run discovery")
    ap.add_argument("--fetch", action="store_true", help="only run fetch")
    ap.add_argument("--parse", action="store_true", help="only run parse")
    ap.add_argument("--election", type=str, default=None, help="limit fetch/parse to one eid")
    ap.add_argument("--delay", type=float, default=1.5, help="delay between fetches (s)")
    args = ap.parse_args()

    state_path = load_storage_state()
    if not state_path:
        sys.exit("no storage_state.json - run save_auth.py first")

    only = args.election
    modes = [m for m in ("discover", "fetch", "parse") if getattr(args, m)]
    run_all = not modes

    if run_all or args.discover:
        if not discover(state_path):
            if run_all:
                print("nothing to fetch or parse")
                return
    if run_all or args.fetch:
        fetch(state_path, only_eid=only, delay=args.delay)
    if run_all or args.parse:
        parse(only_eid=only)


if __name__ == "__main__":
    main()
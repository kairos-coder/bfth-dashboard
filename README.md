# BFTH War Room

A self-hosted dashboard for [Battle for the Hill](https://battleforthehill.com) — roster, caucus breakdowns, congressional composition, live elections, and GOP market desk. Built for a private Discord, not for public redistribution.

**Status:** live at `kairos-coder.github.io/bfth-dashboard` · updates driven by a local hourly cron · last refreshed `Nov 14, 2026`

---

## What's in it

| Page | What it shows |
|---|---|
| `index.html` | Home — quick stats, tile grid, congress snapshot, nations table, live elections |
| `roster.html` | Every GOP politician with NP/CF/NW/stance, filterable and sortable |
| `caucus.html` | Caucus composition charts (Highcharts drilldown), ticker, presidential primary snapshot, endorsement tracker |
| `congress.html` | Senate + House breakdowns, party stacked bars, leadership, member table |
| `elections.html` | Active / Upcoming / Ended tabs, per-race cards with polling, state filter |
| `corporations.html` | GOP-owned corporations, market valuation, dividend/profit totals |
| `history.html` | Archive browser for `data/players/history.jsonl` |

Everything is static — plain HTML/CSS/JS, no framework, no build step. Data comes from JSON files committed by the scraper.

---

## Run it on your own PC

### 1. Prerequisites

- **Python 3.9+** — the scraper uses only stdlib + a couple of common packages
- **Git** — to clone and pull
- **A BFTH account** — the scraper needs a logged-in session cookie

That's it. No Node, no npm, no Docker.

### 2. Clone and set up

```bash
git clone https://github.com/kairos-coder/bfth-dashboard.git
cd bfth-dashboard

# Create a virtualenv so you don't pollute system Python
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Install the scraper dependencies
pip install -r scraper/requirements.txt
```

### 3. Get your BFTH session cookies

The scraper hits authenticated pages, so it needs to look like your browser.

1. Log in to `https://battleforthehill.com` in Chrome or Firefox
2. Open DevTools → **Network** tab → reload the page
3. Click any request to `battleforthehill.com` → **Headers** → scroll to **Request Headers** → copy the entire `Cookie:` header value
4. Save it to `scraper/storage_state.json` in this format:

```json
{
  "cookies": "your-full-cookie-string-here"
}
```

If your `fetch.py` uses Playwright's `storage_state` format instead, export it from a Playwright session — check `scraper/fetch.py` for what it's expecting.

### 4. Test the pipeline once

Before you commit to running it hourly, do a single manual pass to confirm it works:

```bash
# Politicians — this should fetch ~67 profiles and write data/players/latest.json
python3 scraper/parse.py

# Corporations
python3 scraper/corporations.py

# Congress
python3 scraper/congress.py

# Nations (60 countries, takes ~2 min)
python3 scraper/nations.py

# Elections
python3 scraper/elections.py
python3 scraper/aggregate_elections.py
```

If any of those throw an auth error, your cookie is stale — re-export it and try again.

### 5. Serve the dashboard locally

Because the pages `fetch()` JSON files relatively, you can't just double-click `index.html` — the browser will block the fetches under `file://`. Spin up a local server:

```bash
# From the repo root
python3 -m http.server 8000
```

Then open **http://localhost:8000** in your browser. You should see the home dashboard with data loaded.

If you see "Failed to load players" in the debug panel, the JSON files aren't there yet — run step 4 first.

### 6. Automate it (optional)

The script `scraper/run_and_push.sh` runs the full pipeline and commits + pushes any data changes. To run it hourly on macOS/Linux:

```bash
# Edit the paths at the top of scraper/run_and_push.sh first
crontab -e

# Add this line — runs at :00 every hour
0 * * * * /path/to/bfth-dashboard/scraper/run_and_push.sh >> /tmp/bfth-cron.log 2>&1
```

If you're on Windows, use Task Scheduler instead. If you just want it updating without pushing to git, delete the `git pull` / `git push` lines at the bottom of `run_and_push.sh` — the JSON files will refresh locally and the dashboard will pick them up on next page load.

---

## What's in the repo

```
bfth-dashboard/
├── index.html                 # home dashboard
├── roster.html                # politician roster
├── caucus.html                # caucus breakdowns + presidential primary
├── congress.html              # Senate + House composition
├── elections.html             # active/upcoming/ended elections
├── corporations.html          # GOP market desk
├── history.html               # player history archive
├── images/                    # banners, textures, emblem
├── data/
│   ├── players/
│   │   ├── latest.json        # current roster snapshot
│   │   └── <timestamp>.json   # archived snapshots (2/day)
│   ├── corporations/
│   │   └── latest.json
│   ├── nations.json           # aggregated from data/nations/*.json
│   ├── nations/<id>.json      # per-country
│   ├── congress.json
│   └── elections.json
└── scraper/
    ├── fetch.py               # politician HTML fetcher
    ├── parse.py               # politician HTML → JSON
    ├── corporations.py        # corp fetch + parse
    ├── congress.py            # senate + house
    ├── nations.py             # all 60 nations
    ├── elections.py           # elections pipeline
    ├── aggregate_elections.py
    ├── run_and_push.sh        # hourly cron entrypoint
    ├── fetch_gop_roster.py    # writes scraper/urls/gop.txt
    ├── storage_state.json     # your cookies (DO NOT COMMIT)
    └── raw/                   # cached HTML (gitignored)
```

---

## Data flow

```
fetch_gop_roster.py  →  scraper/urls/gop.txt
                              ↓
fetch.py             →  scraper/raw/<id>.html (128 files)
                              ↓
parse.py             →  data/players/latest.json + timestamped archive
                              ↓
                     [corporations.py, congress.py, nations.py, elections.py]
                              ↓
                     data/*.json consumed by all pages
```

Every page does its own `fetch()` against `data/*.json`. That means **you can update the data without touching the HTML**, and you can update any page's HTML without breaking the others.

---

## How the URLs work

A few BFTH quirks the scraper already handles, documented here so you don't re-solve them:

- **Politician profiles:** `battleforthehill.com/politician/<id>`
- **Nations:** `battleforthehill.com/<nation_id>/overview` — but five have named slugs: USA → `/national/overview`, Canada → `/canada/overview`, Cuba → `/cuba/overview`, Russia → `/russia/overview`
- **Elections:** `battleforthehill.com/states/<state_id>/elections/<election_id>`
- **Congress:** Senate `/national/senate/1`, House `/national/house/1`
- **Party list:** `/national/parties/1`
- **Election overview:** `/elections/overview` (returns empty JSON when no elections are active — this is why `scraper/elections.py` prints "no races found in mapRaceLeans" and exits without error)

---

## Known risks

- **Cookie expiry breaks the scraper silently.** Re-export from your browser when `parse.py` starts failing auth. Long-term fix: the session cookie is stored in `storage_state.json`, so a short refresh script would be nice.
- **HTML structure changes on BFTH break selectors.** All selectors live in `scraper/parse.py` (and one-off in `corporations.py`, `congress.py`, `nations.py`, `elections.py`) so a single-file fix usually restores the pipeline.
- **Terms of Service.** This is a private tool for the Discord. Don't redistribute the scraped data or the dashboard publicly. If you're not in the Discord, you're in the wrong place.
- **Parser gaps.** `data/elections.json` currently lacks a `status` field (`active` / `upcoming` / `ended`) and per-election dates — `elections.html` compensates with a heuristic, but the exact data would come from extending `parse_elections.py` to scrape `date_text` and `status` from each state election page. Same for `congress.json` — it doesn't include member-level rosters yet, so `congress.html` shows party breakdowns and leadership only.

---

## Contributing

This is a friends-and-family project. If you're in the Discord, you're welcome to:

- **Fix a selector** — if the scraper breaks, the fix usually goes in `scraper/parse.py`
- **Improve a page** — everything is plain HTML + JS, no build step. Open the file, edit, reload.
- **Add a new view** — pick one of the JSON files under `data/`, build a page against it, link it from the nav on all seven pages (find-and-replace `History (soon)` → `Your Page`)
- **Correct data** — if a politician's name is wrong or a corporation is missing, fix it in the corresponding `scraper/*.py` and re-run

No CI ceremony, no issue templates. Just don't break `main`.

---

## License

Private. Not for redistribution. Built with C-shaped paranoia, Python-shaped pragmatism, and a deep suspicion of institutions that don't show their work.

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

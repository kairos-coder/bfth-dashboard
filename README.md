bfth-dashboard/
├── .github/workflows/scrape.yml      # cron: hourly + workflow_dispatch
├── scraper/
│   ├── fetch.py                      # requests.Session + cookies from secret
│   ├── parse.py                      # BeautifulSoup selectors for stats
│   └── store.py                      # write data/latest.json + data/history/
├── data/
│   ├── latest.json                   # current snapshot (all players)
│   ├── players.json                  # static: handles, URLs, corps
│   └── history/2026-11-12-14.json    # timestamped snapshots
├── dashboard/
│   ├── index.html                    # reads data/latest.json
│   └── app.js                        # war-room UI, filters, player cards
└── README.md                         # = your Roster #1 markdown, updated

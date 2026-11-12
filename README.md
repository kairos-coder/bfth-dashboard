
---

## 🚀 Roadmap

### Phase 0 — Foundation *(this README, the repo skeleton)*
- [x] Write the README with goals and architecture
- [ ] Create repo structure
- [ ] Port Roster #1 markdown into `docs/ROSTER-1.md`
- [ ] Hand-build `data/players.json` for Players #1–#12

### Phase 1 — Static Dashboard *(no scraping yet)*
- [ ] `dashboard/index.html` renders player cards from `players.json`
- [ ] Filters: state, caucus, KOFI status, VET status
- [ ] Sort: NP, CF, NW, CS, SR, NR
- [ ] Player detail view: offices, marriages, alt links
- [ ] Deploy to GitHub Pages
- **Milestone:** you can share the link in Discord and friends can browse the roster

### Phase 2 — Scraper *(the real work)*
- [ ] Inspect one BFTH profile page in incognito → determine auth model
- [ ] `fetch.py` with session cookies from GitHub Secrets
- [ ] `parse.py` with selectors for CF, NP, CS, SR, NR, NW, LC/hr, offices
- [ ] `store.py` writes `latest.json` + history snapshot
- [ ] `scrape.yml` runs hourly, commits results, notifies Discord on failure
- **Milestone:** stats update automatically; dashboard shows "last updated"

### Phase 3 — War Room *(the fun part)*
- [ ] Sparklines: last 24h / 7d of NP, CF, NW per player
- [ ] Change detection: "NP +47 since yesterday" badges
- [ ] Alliance web visualization: marriage links, KOFI clusters
- [ ] State map: GOP politicians by state, colored by total NP
- [ ] Activity feed: "Greg Abbott gained 47 NP at 14:32"
- [ ] Search: find any politician, player, state, or caucus

### Phase 4 — Stretch *(only if it's still fun)*
- [ ] LC-per-turn tracker (if BFTH exposes it reliably)
- [ ] Alert webhooks: "P4's CF crossed $500M"
- [ ] Discord bot that answers `/whois greg-abbott`
- [ ] Export to CSV for spreadsheet people

---

## 🔐 Secrets & Configuration

The scraper needs an authenticated BFTH session. Store it as a repository secret:

| Secret name | What it is |
|-------------|------------|
| `BFTH_COOKIES` | JSON-encoded cookie jar exported from your browser after login |
| `DISCORD_WEBHOOK` | Webhook URL for failure notifications (optional) |

**Cookie refresh:** when the Action fails with an auth error, re-export cookies from
your browser, update the secret, and re-run. The failure notification tells you when.

---

## ⚠️ Known Risks

- **Cookie expiry** will silently break the scraper. Mitigated by failure notifications.
- **HTML structure changes** on BFTH will break selectors. Mitigated by logging raw HTML
  on parse failure and keeping selectors in one place.
- **Terms of Service.** This is a private tool for friends, not a public redistribution
  of BFTH data. Keep the repo private if you're concerned.
- **GitHub Actions minutes.** Hourly scrapes of ~20 profiles fit comfortably in the
  2,000 free minutes/month. If the roster grows past ~100 profiles, reduce frequency.

---

## 👥 The Roster

The current roster lives in [`docs/ROSTER-1.md`](docs/ROSTER-1.md) — players #1–#12
profiled, 23 politicians logged, 16 states covered. This markdown is the **seed data**
for `players.json` and the **human-readable reference** for the dashboard.

**Currently tracked:**

- 🔑 **2 KOFI accounts** — `vikitor889_80029#0` (3 profiles), `venus.444#0` (5 profiles)
- 🏛️ **4 executive offices** — President, VP, Senate Maj. Leader, Speaker
- 🟢 **$963.6M** combined campaign funds
- 🟡 **$8.1B** combined net worth
- 🕸️ **10 marriage/alliance links** across 6 players

---

## 🤝 Contributing

This is a friends-and-family project. If you're in the Discord, you're welcome to:

- **Add a player profile** — open a PR against `data/players.json`
- **Fix a selector** — if the scraper breaks, the fix goes in `scraper/parse.py`
- **Improve the dashboard** — `dashboard/app.js` is plain JS, no build step
- **Correct the roster** — `docs/ROSTER-1.md` is editable markdown

No CI ceremony, no issue templates, no code of conduct. Just don't break `main`.

---

## 📜 License

Private. Not for redistribution. If you're reading this and you're not in the Discord,
you're in the wrong place.

---

*Built with C-shaped paranoia, Python-shaped pragmatism, and a deep suspicion of
institutions that don't show their work.*

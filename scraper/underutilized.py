#!/usr/bin/env python3
"""
underutilized.py - find alts that are under-developed AND actively played.

Groups profiles by discord handle. In each group, the highest-NP profile
is the "main"; the rest are "alts". Flags any alt where:
  - campaign_strength < CS_THRESHOLD (under-developed)
  - last_active_hours <= ACTIVITY_HOURS (logged in recently)
  - main campaign_strength >= MAIN_CS_FLOOR (main is actually built)

Skips dormant mains and inactive alts by default. Use --all to include them.

Usage:
    python3 scraper/underutilized.py
    python3 scraper/underutilized.py --threshold 70
    python3 scraper/underutilized.py --all
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA = REPO_ROOT / "data" / "players" / "latest.json"

CS_THRESHOLD = 50
MAIN_CS_FLOOR = 20
ACTIVITY_HOURS = 168  # 7 days


def np_of(p):
    return p.get("national_prestige") or 0


def cs_of(p):
    return p.get("campaign_strength") or 0


def activity_of(p):
    """Return hours since last active, or None if unknown."""
    return p.get("last_active_hours")


def format_money(n):
    if n is None:
        return "-"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.1f}M"
    if n >= 1e3:
        return f"${n/1e3:.0f}K"
    return f"${n:.0f}"


def format_np(n):
    if n is None:
        return "-"
    if n >= 1000:
        return f"{n:,.0f}"
    return f"{n:.1f}"


def format_activity(p):
    raw = p.get("last_active_raw")
    if not raw:
        return "-"
    # Shorten "Active Now" -> "now", "2 weeks ago" -> "2w"
    r = raw.lower().replace(" ago", "")
    r = r.replace("active now", "now").replace("just now", "now")
    r = r.replace(" minute", "m").replace("minute", "m")
    r = r.replace(" hour", "h").replace("hour", "h")
    r = r.replace(" day", "d").replace("day", "d")
    r = r.replace(" week", "w").replace("week", "w")
    r = r.replace(" month", "mo").replace("month", "mo")
    r = r.replace(" year", "y").replace("year", "y")
    r = r.replace("s ", " ").replace("s", "")
    return r[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=CS_THRESHOLD,
                    help=f"CS threshold for flagging (default {CS_THRESHOLD})")
    ap.add_argument("--activity-hours", type=float, default=ACTIVITY_HOURS,
                    help=f"max hours since last active to count as 'playing' "
                         f"(default {ACTIVITY_HOURS})")
    ap.add_argument("--all", action="store_true",
                    help="include dormant mains and inactive alts")
    args = ap.parse_args()

    if not DATA.exists():
        sys.exit(f"missing {DATA} - run parse.py first")

    data = json.loads(DATA.read_text())
    players = data.get("players") or []
    if not players:
        sys.exit("no players in latest.json")

    by_discord = {}
    for p in players:
        d = p.get("discord")
        if d:
            by_discord.setdefault(d, []).append(p)

    multi = {d: ps for d, ps in by_discord.items() if len(ps) >= 2}

    if not multi:
        print("No multi-profile accounts found.")
        return

    print(f"Analyzing {len(multi)} multi-profile accounts")
    print(f"Flagging alts with CS < {args.threshold}", end="")
    if not args.all:
        print(f", last active < {args.activity_hours:.0f}h", end="")
        print(f", where main CS >= {MAIN_CS_FLOOR}")
    else:
        print(" (including dormant / inactive)")
    print()

    flagged = []
    skipped = []

    for discord, profiles in multi.items():
        profiles.sort(key=np_of, reverse=True)
        main = profiles[0]
        alts = profiles[1:]
        main_cs = cs_of(main)

        for alt in alts:
            alt_cs = cs_of(alt)
            if alt_cs >= args.threshold:
                continue

            if not args.all:
                if main_cs < MAIN_CS_FLOOR:
                    skipped.append({
                        "discord": discord,
                        "main": main,
                        "alt": alt,
                        "reason": f"main CS {main_cs:.0f} < {MAIN_CS_FLOOR}",
                    })
                    continue

                alt_hrs = activity_of(alt)
                if alt_hrs is not None and alt_hrs > args.activity_hours:
                    skipped.append({
                        "discord": discord,
                        "main": main,
                        "alt": alt,
                        "reason": f"alt inactive {alt_hrs:.0f}h",
                    })
                    continue

            flagged.append({
                "discord": discord,
                "main": main,
                "alt": alt,
                "alt_cs": alt_cs,
                "main_cs": main_cs,
            })

    flagged.sort(key=lambda x: x["alt_cs"])

    if not flagged:
        print("No under-utilized alts found.")
    else:
        print(
            f"{'Player':<24} "
            f"{'Main':<20} {'CS':>5}  "
            f"{'Alt':<20} {'CS':>5}  "
            f"{'Alt NP':>9}  {'Alt CF':>9}  {'Active':<10}"
        )
        print("-" * 118)

        for f in flagged:
            main = f["main"]
            alt = f["alt"]
            print(
                f"{f['discord'][:23]:<24} "
                f"{main['name'][:18]:<20} {f['main_cs']:>5.1f}  "
                f"{alt['name'][:18]:<20} {f['alt_cs']:>5.1f}  "
                f"{format_np(np_of(alt)):>9}  "
                f"{format_money(alt.get('campaign_funds')):>9}  "
                f"{format_activity(alt):<10}"
            )

        print(f"\n{len(flagged)} under-utilized alts "
              f"across {len({f['discord'] for f in flagged})} players")

    if skipped:
        print(f"\n({len(skipped)} alt(s) skipped as dormant or inactive)")
        for s in skipped:
            print(
                f"  {s['discord'][:22]:<24} "
                f"main={s['main']['name'][:16]:<18} "
                f"alt={s['alt']['name'][:16]:<18} "
                f"({s['reason']})"
            )


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
predict_final.py - weighted poll forecast for completed and live elections.

The model: final result = weighted sum of per-poll percentages, with the last
N_LATE polls weighted W_LATE each and everything before weighted W_EARLY each.

Weights are pre-registered priors (see W_EARLY / W_LATE below). They will be
refit empirically once we have 3+ completed races to fit against. Until then,
they are the best guess derived from the wiki's "~0.7% early / ~7.5% late" note,
adjusted slightly to sum closer to 1.0.

Usage:
    # Forecast one election
    python3 scraper/predict_final.py --election 19489

    # Forecast all parsed elections
    python3 scraper/predict_final.py --all

    # Show actual vs predicted for a completed race (fit check)
    python3 scraper/predict_final.py --election <eid> --check

    # Refit weights against all completed races (needs 3+)
    python3 scraper/predict_final.py --fit
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = REPO_ROOT / "data" / "elections"


# ─── model parameters (pre-registered priors, refit when completed races accumulate) ───
W_EARLY = 0.00734    # per early poll (polls 1..92 in a 96-poll cycle)
W_LATE  = 0.0767     # per late poll (polls 93..96)
N_LATE  = 4
N_CYCLE = 96


def predict_final(pct_list, w_e=W_EARLY, w_l=W_LATE, n_late=N_LATE):
    """
    Weighted sum of per-poll percentages -> predicted final result.

    pct_list: chronological list of per-poll percentages for ONE candidate,
              oldest first. Length <= N_CYCLE.
    Returns: predicted final percentage (float), or None if empty.
    """
    n = len(pct_list)
    if n == 0:
        return None
    n_late_actual = min(n_late, n)
    n_early_actual = n - n_late_actual
    total = sum(pct_list[:n_early_actual]) * w_e
    total += sum(pct_list[n_early_actual:]) * w_l
    return round(total, 3)


def extract_candidate_series(candidate_name, polls):
    """Return chronological list of a candidate's pct in each poll, skipping None."""
    return [
        p["results"][candidate_name]
        for p in polls
        if candidate_name in p.get("results", {})
        and p["results"][candidate_name] is not None
    ]


def forecast_election(election_data, w_e=W_EARLY, w_l=W_LATE, n_late=N_LATE):
    """
    Given a parsed election.json dict, return per-candidate forecasts.
    Returns: list of dicts with name, predicted_final, polls_used, final_pct.
    """
    polls = election_data.get("polls", [])
    candidates = election_data.get("candidates", [])
    out = []
    for cand in candidates:
        name = cand.get("name")
        if not name:
            continue
        series = extract_candidate_series(name, polls)
        pred = predict_final(series, w_e=w_e, w_l=w_l, n_late=n_late) if series else None
        out.append({
            "name": name,
            "politician_id": cand.get("politician_id"),
            "final_pct": cand.get("final_pct"),
            "predicted_final": pred,
            "polls_used": len(series),
            "gap": round(pred - cand["final_pct"], 3)
                   if pred is not None and cand.get("final_pct") is not None else None,
        })
    # sort by predicted_final desc so winner is first
    out.sort(key=lambda c: c["predicted_final"] or -1, reverse=True)
    return out


def load_election(eid):
    f = DATA_DIR / eid / "election.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception as e:
        print(f"  ERROR loading {eid}: {e}")
        return None


def list_elections():
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if (p / "election.json").exists())


def cmd_one(eid, check=False):
    data = load_election(eid)
    if not data:
        print(f"no data for election {eid}")
        return 1

    label = data.get("label", "")
    typ = data.get("type", "")
    state_id = data.get("state_id", "")
    polls_count = data.get("polls_count", 0)
    source = data.get("polls_source", "?")

    print(f"\n{'='*70}")
    print(f"  {eid}  {typ}  state={state_id}  {label}")
    print(f"  polls: {polls_count}  source: {source}")
    print(f"{'='*70}\n")

    if polls_count == 0:
        print("  no polls captured — cannot forecast")
        return 0

    forecasts = forecast_election(data)
    if not forecasts:
        print("  no candidates parsed")
        return 0

    # headline
    winner = forecasts[0]
    print(f"  PREDICTED WINNER: {winner['name']}")
    print(f"    predicted_final: {winner['predicted_final']:.2f}%")
    print(f"    polls used: {winner['polls_used']}")
    if check and winner["final_pct"] is not None:
        print(f"    actual final:    {winner['final_pct']:.2f}%")
        print(f"    residual:        {winner['gap']:+.2f} points")
    print()

    # full table
    print(f"  {'candidate':<28} {'predicted':>10} {'polls':>7} {'actual':>10} {'gap':>8}")
    print(f"  {'-'*28} {'-'*10} {'-'*7} {'-'*10} {'-'*8}")
    for c in forecasts:
        pred = f"{c['predicted_final']:.2f}%" if c['predicted_final'] is not None else "—"
        actual = f"{c['final_pct']:.2f}%" if c['final_pct'] is not None else "—"
        gap = f"{c['gap']:+.2f}" if c['gap'] is not None else "—"
        print(f"  {c['name'][:28]:<28} {pred:>10} {c['polls_used']:>7} {actual:>10} {gap:>8}")

    # weight sanity note
    n = winner["polls_used"]
    if n < N_CYCLE:
        missing = N_CYCLE - n
        print()
        print(f"  NOTE: {n}/{N_CYCLE} polls so far; {missing} poll(s) still to come.")
        print(f"        Projection will firm up when late polls arrive.")

    return 0


def cmd_all():
    elections = list_elections()
    if not elections:
        print("no parsed elections found in data/elections/")
        return 1

    print(f"forecasting {len(elections)} elections...\n")
    print(f"  {'eid':<8} {'type':<10} {'polls':>6} {'leader':<24} {'predicted':>10} {'source':<14}")
    print(f"  {'-'*8} {'-'*10} {'-'*6} {'-'*24} {'-'*10} {'-'*14}")

    for eid in elections:
        data = load_election(eid)
        if not data:
            continue
        polls_count = data.get("polls_count", 0)
        source = data.get("polls_source", "?")
        if polls_count == 0:
            print(f"  {eid:<8} {data.get('type', '?'):<10} {polls_count:>6} {'(no polls)':<24} {'—':>10} {source:<14}")
            continue
        forecasts = forecast_election(data)
        if not forecasts:
            print(f"  {eid:<8} {data.get('type', '?'):<10} {polls_count:>6} {'(no candidates)':<24} {'—':>10} {source:<14}")
            continue
        w = forecasts[0]
        pred_str = f"{w['predicted_final']:.1f}%" if w['predicted_final'] is not None else "—"
        print(f"  {eid:<8} {data.get('type', '?'):<10} {polls_count:>6} {w['name'][:24]:<24} {pred_str:>10} {source:<14}")

    return 0


def cmd_fit():
    """
    Fit W_EARLY and W_LATE against all completed races.
    Requires 3+ completed races with full poll history and known final_pct.
    Uses least squares to find (w_e, w_l) minimizing sum of squared residuals.
    """
    elections = list_elections()
    if not elections:
        print("no parsed elections")
        return 1

    # collect completed races: has polls, has final_pct, has >= 60 polls (near-complete)
    completed = []
    for eid in elections:
        data = load_election(eid)
        if not data:
            continue
        if data.get("polls_count", 0) < 60:
            continue
        candidates = data.get("candidates", [])
        # require at least 2 candidates with final_pct populated
        with_final = [c for c in candidates if c.get("final_pct") is not None]
        if len(with_final) < 2:
            continue
        # find the top two candidates by final_pct
        with_final.sort(key=lambda c: c["final_pct"], reverse=True)
        winner, runner_up = with_final[0], with_final[1]
        # both must have a poll series
        w_series = extract_candidate_series(winner["name"], data["polls"])
        r_series = extract_candidate_series(runner_up["name"], data["polls"])
        if not w_series or not r_series:
            continue
        completed.append({
            "eid": eid,
            "winner_series": w_series,
            "winner_final": winner["final_pct"],
            "runner_series": r_series,
            "runner_final": runner_up["final_pct"],
        })

    print(f"completed races with full data: {len(completed)}")
    if len(completed) < 3:
        print(f"  need 3+ to fit; have {len(completed)}")
        print("  current priors still in effect: W_EARLY={}, W_LATE={}".format(W_EARLY, W_LATE))
        return 1

    # simple grid search for now (least squares via minimize_scalar would be better)
    # parameterize by RATIO = w_l/w_e; solve w_e so weights sum to 1 for a 96-cycle
    print("\ngrid search over ratio (w_l / w_e)...")
    best_ratio, best_rmse = None, float("inf")
    for ratio in [r * 0.25 for r in range(20, 80)]:  # 5.0 to 20.0 in 0.25 steps
        n_early = N_CYCLE - N_LATE
        w_e = 1.0 / (n_early + N_LATE * ratio)
        w_l = ratio * w_e
        sq_err = 0.0
        count = 0
        for r in completed:
            w_pred = predict_final(r["winner_series"], w_e=w_e, w_l=w_l)
            r_pred = predict_final(r["runner_series"], w_e=w_e, w_l=w_l)
            if w_pred is None or r_pred is None:
                continue
            sq_err += (w_pred - r["winner_final"]) ** 2
            sq_err += (r_pred - r["runner_final"]) ** 2
            count += 2
        if count == 0:
            continue
        rmse = (sq_err / count) ** 0.5
        if rmse < best_rmse:
            best_rmse = rmse
            best_ratio = ratio

    if best_ratio is None:
        print("fit failed")
        return 1

    n_early = N_CYCLE - N_LATE
    w_e = 1.0 / (n_early + N_LATE * best_ratio)
    w_l = best_ratio * w_e

    print(f"\n  best ratio:   {best_ratio:.3f}")
    print(f"  fitted W_EARLY = {w_e:.5f}  (current: {W_EARLY})")
    print(f"  fitted W_LATE  = {w_l:.5f}  (current: {W_LATE})")
    print(f"  RMSE:         {best_rmse:.3f} points")
    print()
    print(f"  to use these, update predict_final.py:")
    print(f"    W_EARLY = {w_e:.5f}")
    print(f"    W_LATE  = {w_l:.5f}")

    # per-race residuals at best fit
    print(f"\n  per-race residuals at best fit:")
    for r in completed:
        w_pred = predict_final(r["winner_series"], w_e=w_e, w_l=w_l)
        resid = w_pred - r["winner_final"] if w_pred is not None else None
        resid_str = f"{resid:+.2f}" if resid is not None else "—"
        print(f"    {r['eid']}: winner {r['winner_final']:.2f}% vs predicted {w_pred:.2f}%  (residual {resid_str})")

    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--election", type=str, help="forecast one election")
    ap.add_argument("--all", action="store_true", help="forecast all parsed elections")
    ap.add_argument("--check", action="store_true", help="show actual vs predicted (add to --election)")
    ap.add_argument("--fit", action="store_true", help="refit weights against completed races")
    args = ap.parse_args()

    if args.fit:
        return cmd_fit()
    if args.all:
        return cmd_all()
    if args.election:
        return cmd_one(args.election, check=args.check)

    # no args: show help
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
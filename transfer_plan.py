#!/usr/bin/env python3
"""Propose transfers for an existing FPL squad.

Reads the live squad from the public API and ranks every legal single swap by
expected-points gain over the coming gameweeks. Selling prices and bank come
from a state file, because they need an authenticated session this script
deliberately does not have.

Usage:  python3 transfer_plan.py --state team_state.json [--horizon 5] [--top 12]
"""

import argparse
import json

from gw1_squad import (CLUB_LIMIT, POS, difficulty_by_team, effective_ownership,
                       get, load_baseline, score_players)

HIT_COST = 4
# A -4 is only worth taking if the gain clearly beats it over the horizon.
HIT_THRESHOLD = 6.0


def load_state(path):
    with open(path) as f:
        s = json.load(f)
    return s["entry"], s["bank"], s.get("free_transfers", 1), {int(k): v for k, v in s["selling"].items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="JSON with entry, bank, selling prices")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--eo-weight", type=float, default=0.35)
    ap.add_argument("--exclude-club", nargs="*", default=[],
                    help="club short names to never transfer in, e.g. MCI")
    ap.add_argument("--only-out", nargs="*", default=[],
                    help="only consider selling these web_names")
    ap.add_argument("--min-evidence", type=int, default=900,
                    help="baseline minutes an incoming player must have; without this "
                         "the ranking fills with unknowns who merely beat an injured man")
    args = ap.parse_args()

    entry, bank, free_transfers, selling = load_state(args.state)

    boot = get("bootstrap-static/")
    team_name = {t["id"]: t["short_name"] for t in boot["teams"]}
    gw = next(e["id"] for e in boot["events"] if e["is_current"] or e["is_next"])
    # Transfers land in the NEXT gameweek, so plan from there.
    nxt = gw + 1 if any(e["id"] == gw and e["is_current"] for e in boot["events"]) else gw
    gameweeks = list(range(nxt, nxt + args.horizon))

    picks = get(f"entry/{entry}/event/{gw}/picks/")["picks"]
    owned = [p["element"] for p in picks]

    fdr = difficulty_by_team(gameweeks)
    eo = effective_ownership(nxt)
    # gw1_weight 0 -> score the whole horizon evenly; a transfer is a multi-week bet.
    baseline = load_baseline()
    scored = {p["id"]: p for p in
              score_players(boot["elements"], fdr, gameweeks, eo, 0.0, baseline=baseline)}

    by_id = {e["id"]: e for e in boot["elements"]}
    clubs = {}
    for i in owned:
        clubs[by_id[i]["team"]] = clubs.get(by_id[i]["team"], 0) + 1

    def value(pid):
        p = scored.get(pid)
        if not p:
            return 0.0
        return p["score"] + args.eo_weight * p["eo"] * p["score"]

    moves = []
    for out in owned:
        o = by_id[out]
        if args.only_out and o["web_name"] not in args.only_out:
            continue
        budget = bank + selling.get(out, o["now_cost"])
        for cand in boot["elements"]:
            if cand["id"] in owned or cand["element_type"] != o["element_type"]:
                continue
            if cand["now_cost"] > budget or cand["status"] in ("u", "n", "i"):
                continue
            if team_name[cand["team"]] in args.exclude_club:
                continue
            if baseline.get(cand["id"], {}).get("minutes", 0) < args.min_evidence:
                continue
            # club limit, remembering the outgoing player frees a slot
            used = clubs.get(cand["team"], 0) - (1 if cand["team"] == o["team"] else 0)
            if used >= CLUB_LIMIT:
                continue
            gain = value(cand["id"]) - value(out)
            if gain > 0:
                moves.append((gain, out, cand["id"], budget - cand["now_cost"]))

    moves.sort(reverse=True)
    print(f"squad {entry} | bank £{bank/10:.1f}m | {free_transfers} free transfer(s) | "
          f"planning GW{nxt}-{nxt + args.horizon - 1}\n")
    print(f"{'gain':>6}  {'OUT':<26} {'IN':<26} {'left':>6}")
    seen = set()
    for gain, out, inn, left in moves:
        if out in seen and not args.only_out:
            continue          # show only each player's best upgrade
        seen.add(out)
        o, c = by_id[out], by_id[inn]
        print(f"{gain:>+6.2f}  {POS[o['element_type']]} {o['web_name']:<12} "
              f"{team_name[o['team']]:<4} £{selling.get(out, o['now_cost'])/10:<4.1f} "
              f"→ {POS[c['element_type']]} {c['web_name']:<12} {team_name[c['team']]:<4} "
              f"£{c['now_cost']/10:<4.1f} {left/10:>5.1f}")
        if len(seen) >= args.top and not args.only_out:
            break

    if moves:
        best = moves[0][0]
        second = next((g for g, o, i, _ in moves[1:] if o != moves[0][1]), 0)
        print(f"\nbest single transfer: {best:+.2f} over {args.horizon} GWs")
        print(f"second transfer would add {second:+.2f} for a -{HIT_COST} hit — "
              f"{'WORTH IT' if second >= HIT_THRESHOLD else 'not worth it'} "
              f"(threshold {HIT_THRESHOLD})")


if __name__ == "__main__":
    main()

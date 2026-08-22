#!/usr/bin/env python3
"""GW1 squad picker. Throwaway: gets a legal team in before the deadline.

ponytail: heuristic EP, not a trained model. The real model lands post-GW1
(see plans/fpl-ai-manager-spec.md). Wildcard in GW2+ makes any error here free.

Usage:  python3 gw1_squad.py [--horizon 5] [--bench-weight 0.15]
"""

import argparse
import json
import os
import statistics
import pulp

from fpl_api import POS, current_and_next_event, fetch, get

# livefpl publishes predicted effective ownership per gameweek as open JSON.
LIVEFPL_EO = "https://livefpl.us/predictedEOs/{gw}.json"
SQUAD = {1: 2, 2: 5, 3: 5, 4: 3}          # 15-man squad by position
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}         # valid formation bounds
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
BUDGET = 1000                             # £100.0m in FPL's tenths
CLUB_LIMIT = 3

# Fixture difficulty 1 (easiest) .. 5 (hardest) -> points multiplier.
DIFFICULTY_STEP = 0.12
# Below this many minutes last season we don't trust points-per-90.
MIN_MINUTES = 450
# The live bootstrap resets to current-season totals at GW1 kickoff, so scoring
# rates come from an archived pre-season snapshot instead. See data/README.
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "baseline-2025-26.json")


def effective_ownership(gw):
    """{player_id: EO} — ownership plus captaincy, so it can exceed 1.0.

    Not owning a 1.2-EO player costs you ~1.2x whatever he scores, relative to
    the field. That risk is what the eo_weight term prices in.
    """
    try:
        return {int(k): v for k, v in fetch(LIVEFPL_EO.format(gw=gw)).items()}
    except Exception as e:
        print(f"warning: no EO data ({e}); solving on raw expected points")
        return {}


def difficulty_by_team(gameweeks):
    """{team_id: {gw: [difficulty per fixture]}}.

    A list, not a scalar: in a double gameweek a team plays twice and keying by
    gameweek alone silently discards one of them, valuing a DGW asset at half
    its worth. A blank gameweek is naturally the empty list.
    """
    out = {}
    for gw in gameweeks:
        for f in get(f"fixtures/?event={gw}"):
            out.setdefault(f["team_h"], {}).setdefault(gw, []).append(f["team_h_difficulty"])
            out.setdefault(f["team_a"], {}).setdefault(gw, []).append(f["team_a_difficulty"])
    return out


def load_baseline():
    """{player_id: last full season's scoring stats}. Empty if the archive is absent."""
    try:
        with open(BASELINE) as f:
            return {e["id"]: e for e in json.load(f)["elements"]}
    except FileNotFoundError:
        print(f"warning: no baseline at {BASELINE}; scoring on live season only")
        return {}


def base_points_per_game(hist, live):
    """Expected points for a full appearance.

    Scoring rate comes from the archived season (`hist`); `ep_next` is FPL's
    forward projection and must come from the LIVE element (`live`), or every
    thin-history player stays frozen at his pre-season estimate all year.
    """
    minutes = hist["minutes"]
    if minutes < MIN_MINUTES:
        # New signing / fringe: FPL's own estimate is all we have.
        return float(live["ep_next"] or 0)
    # Preseason, ep_next is a near-flat prior (4.0 for Haaland AND for a midtable
    # midfielder), so blending it in just flattens the premiums. Real minutes beat it.
    return hist["total_points"] / (minutes / 90)


def availability(p):
    """0..1. Suspended/injured/left the club are excluded outright by the caller."""
    chance = p["chance_of_playing_next_round"]
    if chance is not None:
        return chance / 100
    return 1.0


def start_probability(p):
    """Rough minutes model: last season's start rate, floored so nobody is written off."""
    if p["minutes"] < MIN_MINUTES:
        return 0.55  # unknown quantity, assume a rotation risk
    return min(1.0, max(0.3, p["starts"] / 38))


def score_players(elements, fdr, gameweeks, eo, gw1_weight=0.55, exclude=(),
                  exclude_clubs=(), team_name=None, baseline=None):
    players = []
    for p in elements:
        if p["status"] in ("u", "n"):  # unavailable / not in squad
            continue
        if p["web_name"] in exclude or str(p["id"]) in exclude:
            continue
        if team_name and team_name.get(p["team"]) in exclude_clubs:
            continue
        # Rates from the baseline, availability and price from the live feed.
        hist = (baseline or {}).get(p["id"], p)
        base = base_points_per_game(hist, p) * start_probability(hist)
        if base <= 0:
            continue
        per_gw = []
        for i, gw in enumerate(gameweeks):
            # Sum over fixtures: two in a double, none in a blank.
            played = fdr.get(p["team"], {}).get(gw, [])
            pts = sum(base * (1 + (3 - d) * DIFFICULTY_STEP) for d in played)
            # chance_of_playing is a NEXT-ROUND flag. Applying it across the whole
            # horizon writes a one-week knock off for five weeks, which makes the
            # transfer planner recommend selling a player who is back in GW+1.
            per_gw.append(pts * availability(p) if i == 0 else pts)
        players.append(
            {
                "id": p["id"],
                "name": p["web_name"],
                "pos": p["element_type"],
                "team": p["team"],
                "cost": p["now_cost"],
                "owned": float(p["selected_by_percent"]),
                "eo": eo.get(p["id"], 0.0),
                "ep_gw1": per_gw[0],
                # Weight GW1 heavily (it is the one we're solving) but keep the
                # squad viable for the run of fixtures behind it.
                "score": gw1_weight * per_gw[0]
                + (1 - gw1_weight) * statistics.mean(per_gw),
            }
        )
    return players


def solve(players, bench_weight, must_have=(), eo_weight=0.0):
    prob = pulp.LpProblem("fpl_gw1", pulp.LpMaximize)
    pick = {p["id"]: pulp.LpVariable(f"p{p['id']}", cat="Binary") for p in players}
    start = {p["id"]: pulp.LpVariable(f"s{p['id']}", cat="Binary") for p in players}
    cap = {p["id"]: pulp.LpVariable(f"c{p['id']}", cat="Binary") for p in players}

    by_id = {p["id"]: p for p in players}
    prob += pulp.lpSum(
        by_id[i]["score"] * (start[i] + bench_weight * (pick[i] - start[i]))
        # Owning a heavily-captained asset is risk reduction, not just points —
        # but only if he STARTS. Credited on pick[i], the solver would happily
        # buy an expensive high-EO backup keeper who can never play.
        + eo_weight * by_id[i]["eo"] * by_id[i]["ep_gw1"]
        * (start[i] + bench_weight * (pick[i] - start[i]))
        + by_id[i]["ep_gw1"] * cap[i]
        for i in pick
    )

    for name in must_have:
        matches = [p for p in players
                   if p["name"] == name or str(p["id"]) == str(name)]
        if not matches:
            raise SystemExit(f"no available player named {name!r}")
        if len(matches) > 1:
            # 15 surnames are shared in the game; left ambiguous, the solver is free
            # to satisfy "Wilson" with a £4.5m reserve keeper. Make the caller choose.
            opts = ", ".join(f"{p['name']} ({POS[p['pos']]}, £{p['cost']/10}m, id={p['id']})"
                             for p in matches)
            raise SystemExit(f"{name!r} is ambiguous: {opts} — use the id instead")
        prob += pick[matches[0]["id"]] == 1

    prob += pulp.lpSum(by_id[i]["cost"] * pick[i] for i in pick) <= BUDGET
    prob += pulp.lpSum(pick.values()) == 15
    prob += pulp.lpSum(start.values()) == 11
    prob += pulp.lpSum(cap.values()) == 1
    for i in pick:
        prob += start[i] <= pick[i]
        prob += cap[i] <= start[i]
    for pos, n in SQUAD.items():
        prob += pulp.lpSum(pick[p["id"]] for p in players if p["pos"] == pos) == n
        in_xi = pulp.lpSum(start[p["id"]] for p in players if p["pos"] == pos)
        prob += in_xi >= XI_MIN[pos]
        prob += in_xi <= XI_MAX[pos]
    for team in {p["team"] for p in players}:
        prob += pulp.lpSum(pick[p["id"]] for p in players if p["team"] == team) <= CLUB_LIMIT

    if prob.solve(pulp.PULP_CBC_CMD(msg=0)) != pulp.LpStatusOptimal:
        raise SystemExit("no optimal squad found")
    return (
        [by_id[i] for i in pick if pick[i].value() > 0.5],
        {i for i in start if start[i].value() > 0.5},
        next(i for i in cap if cap[i].value() > 0.5),
    )


def check(squad, xi, teams):
    """Every FPL rule that would get the entry rejected."""
    assert len(squad) == 15, len(squad)
    assert sum(p["cost"] for p in squad) <= BUDGET
    assert len(xi) == 11
    for pos, n in SQUAD.items():
        assert sum(1 for p in squad if p["pos"] == pos) == n, POS[pos]
        n_xi = sum(1 for p in squad if p["pos"] == pos and p["id"] in xi)
        assert XI_MIN[pos] <= n_xi <= XI_MAX[pos], f"{POS[pos]} {n_xi}"
    for t in teams:
        assert sum(1 for p in squad if p["team"] == t) <= CLUB_LIMIT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=lambda v: max(1, int(v)), default=5,
                    help="gameweeks of fixtures to weigh")
    ap.add_argument("--bench-weight", type=float, default=0.15)
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="web_names or ids to ban from the squad")
    ap.add_argument("--exclude-club", nargs="*", default=[],
                    help="club short names to ban, e.g. MCI (keep some with --must-have)")
    ap.add_argument("--must-have", nargs="*", default=[],
                    help="web_names to force into the squad, e.g. Haaland")
    ap.add_argument("--eo-weight", type=float, default=0.35,
                    help="0 = pure expected points, higher = hug the crowd")
    ap.add_argument("--gw1-weight", type=float, default=0.55,
                    help="1.0 = solve GW1 only, 0.0 = solve the whole horizon evenly")
    args = ap.parse_args()

    boot = get("bootstrap-static/")
    team_name = {t["id"]: t["short_name"] for t in boot["teams"]}
    cur, nxt = current_and_next_event(boot)
    if nxt is None and cur is None:
        raise SystemExit("no current or next gameweek; nothing to solve")
    gw1 = (nxt or cur)["id"]
    gameweeks = list(range(gw1, gw1 + args.horizon))

    fdr = difficulty_by_team(gameweeks)
    eo = effective_ownership(gw1)
    baseline = load_baseline()
    players = score_players(boot["elements"], fdr, gameweeks, eo, args.gw1_weight,
                            args.exclude, args.exclude_club, team_name, baseline)
    # A club ban must not remove a player the caller explicitly demanded.
    have = {p["name"] for p in players}
    rescued = [e for e in boot["elements"]
               if (e["web_name"] in args.must_have or str(e["id"]) in args.must_have)
               and e["web_name"] not in have]
    players += score_players(rescued, fdr, gameweeks, eo, args.gw1_weight,
                             baseline=baseline)
    squad, xi, captain = solve(players, args.bench_weight, args.must_have, args.eo_weight)
    check(squad, xi, team_name)

    starters = sorted((p for p in squad if p["id"] in xi), key=lambda p: (p["pos"], -p["score"]))
    bench = sorted((p for p in squad if p["id"] not in xi), key=lambda p: (p["pos"] != 1, -p["score"]))
    vice = max((p for p in starters if p["id"] != captain), key=lambda p: p["ep_gw1"])
    formation = "-".join(str(sum(1 for p in starters if p["pos"] == x)) for x in (2, 3, 4))

    print(f"\nStarting XI  ({formation})")
    for p in starters:
        mark = " (C)" if p["id"] == captain else " (V)" if p["id"] == vice["id"] else ""
        print(f"  {POS[p['pos']]:3} {p['name']:<18} {team_name[p['team']]:<4} "
              f"£{p['cost']/10:>4.1f}m  ep={p['ep_gw1']:.2f}  EO={p['eo']*100:>3.0f}%{mark}")
    print("\nBench (auto-sub order; GK first, cannot be reordered)")
    for n, p in enumerate(bench, 1):
        print(f"  {n}. {POS[p['pos']]:3} {p['name']:<18} {team_name[p['team']]:<4} "
              f"£{p['cost']/10:>4.1f}m  ep={p['ep_gw1']:.2f}")

    spend = sum(p["cost"] for p in squad)
    print(f"\nSpend £{spend/10:.1f}m   in the bank £{(BUDGET - spend)/10:.1f}m")
    print(f"XI expected points £GW{gw1}: {sum(p['ep_gw1'] for p in starters):.1f} "
          f"(+{next(p['ep_gw1'] for p in starters if p['id'] == captain):.1f} captain)")


if __name__ == "__main__":
    main()

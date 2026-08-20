#!/usr/bin/env python3
"""GW1 squad picker. Throwaway: gets a legal team in before the deadline.

ponytail: heuristic EP, not a trained model. The real model lands post-GW1
(see plans/fpl-ai-manager-spec.md). Wildcard in GW2+ makes any error here free.

Usage:  python3 gw1_squad.py [--horizon 5] [--bench-weight 0.15]
"""

import argparse
import json
import statistics
import urllib.request

import pulp

API = "https://fantasy.premierleague.com/api"
# livefpl publishes predicted effective ownership per gameweek as open JSON.
LIVEFPL_EO = "https://livefpl.us/predictedEOs/{gw}.json"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD = {1: 2, 2: 5, 3: 5, 4: 3}          # 15-man squad by position
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}         # valid formation bounds
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
BUDGET = 1000                             # £100.0m in FPL's tenths
CLUB_LIMIT = 3

# Fixture difficulty 1 (easiest) .. 5 (hardest) -> points multiplier.
DIFFICULTY_STEP = 0.12
# Below this many minutes last season we don't trust points-per-90.
MIN_MINUTES = 450


def get(path):
    return _fetch(f"{API}/{path}")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def effective_ownership(gw):
    """{player_id: EO} — ownership plus captaincy, so it can exceed 1.0.

    Not owning a 1.2-EO player costs you ~1.2x whatever he scores, relative to
    the field. That risk is what the eo_weight term prices in.
    """
    try:
        return {int(k): v for k, v in _fetch(LIVEFPL_EO.format(gw=gw)).items()}
    except Exception as e:
        print(f"warning: no EO data ({e}); solving on raw expected points")
        return {}


def difficulty_by_team(gameweeks):
    """{team_id: [difficulty per gameweek]}. Missing GW (blank) -> 5, i.e. no points."""
    out = {}
    for gw in gameweeks:
        seen = set()
        for f in get(f"fixtures/?event={gw}"):
            out.setdefault(f["team_h"], {})[gw] = f["team_h_difficulty"]
            out.setdefault(f["team_a"], {})[gw] = f["team_a_difficulty"]
            seen |= {f["team_h"], f["team_a"]}
    return out


def base_points_per_game(p):
    """Expected points for a full appearance, from last season plus FPL's own estimate."""
    minutes = p["minutes"]
    if minutes < MIN_MINUTES:
        # New signing / fringe: FPL's own estimate is all we have.
        return float(p["ep_next"] or 0)
    # Preseason, ep_next is a near-flat prior (4.0 for Haaland AND for a midtable
    # midfielder), so blending it in just flattens the premiums. Real minutes beat it.
    return p["total_points"] / (minutes / 90)


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


def score_players(elements, fdr, gameweeks, eo, gw1_weight=0.55):
    players = []
    for p in elements:
        if p["status"] in ("u", "n"):  # unavailable / not in squad
            continue
        base = base_points_per_game(p) * start_probability(p) * availability(p)
        if base <= 0:
            continue
        per_gw = []
        for gw in gameweeks:
            diff = fdr.get(p["team"], {}).get(gw)
            if diff is None:
                per_gw.append(0.0)  # blank gameweek
                continue
            per_gw.append(base * (1 + (3 - diff) * DIFFICULTY_STEP))
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
        # Owning a heavily-captained asset is risk reduction, not just points.
        + eo_weight * by_id[i]["eo"] * by_id[i]["ep_gw1"] * pick[i]
        + by_id[i]["ep_gw1"] * cap[i]
        for i in pick
    )

    for name in must_have:
        matches = [p["id"] for p in players if p["name"] == name]
        if not matches:
            raise SystemExit(f"no available player named {name!r}")
        prob += pulp.lpSum(pick[i] for i in matches) == 1

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
    ap.add_argument("--horizon", type=int, default=5, help="gameweeks of fixtures to weigh")
    ap.add_argument("--bench-weight", type=float, default=0.15)
    ap.add_argument("--must-have", nargs="*", default=[],
                    help="web_names to force into the squad, e.g. Haaland")
    ap.add_argument("--eo-weight", type=float, default=0.35,
                    help="0 = pure expected points, higher = hug the crowd")
    ap.add_argument("--gw1-weight", type=float, default=0.55,
                    help="1.0 = solve GW1 only, 0.0 = solve the whole horizon evenly")
    args = ap.parse_args()

    boot = get("bootstrap-static/")
    team_name = {t["id"]: t["short_name"] for t in boot["teams"]}
    gw1 = next(e["id"] for e in boot["events"] if e["is_next"])
    gameweeks = list(range(gw1, gw1 + args.horizon))

    players = score_players(boot["elements"], difficulty_by_team(gameweeks), gameweeks,
                            effective_ownership(gw1), args.gw1_weight)
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

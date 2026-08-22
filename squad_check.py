#!/usr/bin/env python3
"""Pre-deadline squad report: availability flags, then transfer options.

Run this before any gameweek deadline. It reports every player in the squad
whose availability is not clean, so a mid-week injury to anyone doesn't get
missed while attention is on one known doubt.

Usage:  python3 squad_check.py --state team_state.json
"""

import argparse
import datetime

from gw1_squad import POS, get


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="team_state.json")
    args = ap.parse_args()

    import json
    with open(args.state) as f:
        entry = json.load(f)["entry"]

    boot = get("bootstrap-static/")
    by_id = {p["id"]: p for p in boot["elements"]}
    team_name = {t["id"]: t["short_name"] for t in boot["teams"]}

    gw = next(e for e in boot["events"] if e["is_current"] or e["is_next"])
    nxt = next((e for e in boot["events"] if e["is_next"]), gw)
    deadline = datetime.datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    left = deadline - datetime.datetime.now(datetime.timezone.utc)

    picks = get(f"entry/{entry}/event/{gw['id']}/picks/")["picks"]

    print(f"squad {entry} | next deadline GW{nxt['id']} {nxt['deadline_time']} "
          f"({left.total_seconds()/3600:.1f}h away)\n")

    # When does each club next play? A player "back on the 29th" whose club plays
    # on the 29th is a different decision from one whose club played on the 28th.
    fixtures = get(f"fixtures/?event={nxt['id']}")
    kickoff = {}
    for f in fixtures:
        for t in (f["team_h"], f["team_a"]):
            kickoff[t] = f["kickoff_time"]

    problems = []
    for p in picks:
        e = by_id[p["element"]]
        chance = e["chance_of_playing_next_round"]
        if e["status"] == "a" and chance in (None, 100):
            continue
        problems.append(
            f"  {'XI ' if p['position'] <= 11 else 'BEN'} "
            f"{POS[e['element_type']]} {e['web_name']:<14} {team_name[e['team']]:<4} "
            f"status={e['status']} chance={chance}\n"
            f"       news: {e['news'] or '-'}\n"
            f"       club next plays: {kickoff.get(e['team'], 'no fixture')}")

    if problems:
        print("AVAILABILITY PROBLEMS")
        print("\n".join(problems))
    else:
        print("AVAILABILITY: all 15 clean")

    print("\nPrice changes since purchase are in the authenticated view only; "
          "re-export team_state.json if the bank or selling prices matter.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Decide whether the FPL squad needs saying anything, and say it on Discord.

Runs on a plain cron. All the intelligence is in deciding to stay QUIET: an
alert that fires every two hours is an alert nobody reads. It speaks only when
a player's availability actually changes, when a deadline is close, or when a
gameweek has finished scoring.

Env:  DISCORD_WEBHOOK_URL   required to post; without it the report goes to stdout
Usage: python3 notify.py [--state team_state.json] [--force]
"""

import argparse
import datetime
import json
import os
import urllib.request

from gw1_squad import POS, get

MEMORY = ".fpl-state.json"
# Hours before a deadline at which we speak up. Two nudges, not a countdown.
DEADLINE_ALERTS = (24, 3)


def post(text):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("(no DISCORD_WEBHOOK_URL set, printing instead)\n")
        print(text)
        return
    for chunk in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
        req = urllib.request.Request(
            url, data=json.dumps({"content": chunk}).encode(),
            # Discord's edge rejects the default Python-urllib agent with a 403.
            headers={"Content-Type": "application/json",
                     "User-Agent": "cunha-matata-fpl/1.0 (+github.com/stevengonsalvez/fpl)"})
        urllib.request.urlopen(req, timeout=20).read()


def load_memory():
    try:
        with open(MEMORY) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"flags": {}, "announced": []}


def availability(p):
    return f"{p['status']}|{p['chance_of_playing_next_round']}|{p['news']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="team_state.json")
    ap.add_argument("--force", action="store_true", help="post even if nothing changed")
    args = ap.parse_args()

    with open(args.state) as f:
        entry = json.load(f)["entry"]

    boot = get("bootstrap-static/")
    by_id = {p["id"]: p for p in boot["elements"]}
    club = {t["id"]: t["short_name"] for t in boot["teams"]}
    cur = next(e for e in boot["events"] if e["is_current"] or e["is_next"])
    nxt = next((e for e in boot["events"] if e["is_next"]), cur)

    picks = get(f"entry/{entry}/event/{cur['id']}/picks/")["picks"]
    mem = load_memory()
    lines = []

    # 1. availability changes — the only thing worth an unprompted ping
    changed = []
    flags = {}
    for p in picks:
        e = by_id[p["element"]]
        flags[str(e["id"])] = availability(e)
        was = mem["flags"].get(str(e["id"]))
        if was is not None and was != flags[str(e["id"])]:
            changed.append(f"**{e['web_name']}** ({club[e['team']]}) "
                           f"{'starting XI' if p['position'] <= 11 else 'bench'}\n"
                           f"  was: `{was}`\n  now: `{flags[str(e['id'])]}`")
    if changed:
        lines.append("**Availability changed**\n" + "\n".join(changed))

    # 2. deadline proximity
    deadline = datetime.datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    hours = (deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
    for mark in DEADLINE_ALERTS:
        key = f"gw{nxt['id']}-t{mark}"
        if 0 < hours <= mark and key not in mem["announced"]:
            mem["announced"].append(key)
            flagged = [f"{by_id[p['element']]['web_name']} "
                       f"({by_id[p['element']]['status']}/"
                       f"{by_id[p['element']]['chance_of_playing_next_round']})"
                       for p in picks
                       if by_id[p["element"]]["status"] != "a"
                       or by_id[p["element"]]["chance_of_playing_next_round"] not in (None, 100)]
            lines.append(
                f"**GW{nxt['id']} deadline in {hours:.0f}h** ({nxt['deadline_time']})\n"
                + ("flagged: " + ", ".join(flagged) if flagged else "no availability problems"))
            break

    # 3. gameweek results, once scoring is final
    if cur["finished"] and cur["data_checked"]:
        key = f"gw{cur['id']}-done"
        if key not in mem["announced"]:
            mem["announced"].append(key)
            e = get(f"entry/{entry}/")
            lines.append(
                f"**GW{cur['id']} final** — {e['summary_event_points']} pts "
                f"(average {cur['average_entry_score']}, best {cur['highest_score']})\n"
                f"overall rank {e['summary_overall_rank']:,} on {e['summary_overall_points']} pts")

    # 4. a manual run should always say something useful, so build a status block
    if args.force and not lines:
        e = get(f"entry/{entry}/")
        flagged = [f"{by_id[p['element']]['web_name']} "
                   f"({by_id[p['element']]['status']}/"
                   f"{by_id[p['element']]['chance_of_playing_next_round']})"
                   for p in picks
                   if by_id[p["element"]]["status"] != "a"
                   or by_id[p["element"]]["chance_of_playing_next_round"] not in (None, 100)]
        cap = next((by_id[p["element"]]["web_name"] for p in picks if p["is_captain"]), "?")
        lines.append(
            f"**Status** — GW{cur['id']}: {e['summary_event_points']} pts, "
            f"overall {e['summary_overall_points']} pts (rank {e['summary_overall_rank']:,})\n"
            f"captain: {cap}\n"
            f"GW{nxt['id']} deadline: {nxt['deadline_time']} ({hours:.0f}h)\n"
            f"flagged: {', '.join(flagged) if flagged else 'none'}")

    mem["flags"] = flags
    with open(MEMORY, "w") as f:
        json.dump(mem, f, indent=1, sort_keys=True)

    if lines or args.force:
        post(f"__**Cunha Matata**__\n" + "\n\n".join(lines or ["nothing to report"]))
        print("posted:\n" + "\n\n".join(lines or ["(forced, nothing to report)"]))
    else:
        print(f"quiet: no changes, GW{nxt['id']} deadline in {hours:.0f}h")


if __name__ == "__main__":
    main()

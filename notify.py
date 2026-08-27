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
import sys
import tempfile
import urllib.error
import urllib.request

from fpl_api import POS, UA, current_and_next_event, get

MEMORY = ".fpl-state.json"
# Hours before a deadline at which we speak up. Kept ascending and checked
# tightest-first: a run that lands inside the tightest window must file itself
# there even when the earlier alert never fired, or the nudge that matters most
# is silently consumed by the one that does not. Three marks rather than two so
# a dropped run loses one reminder instead of all of them.
DEADLINE_ALERTS = (2, 6, 24)


def post(text):
    """Send to Discord. Raises if delivery fails, so state is not advanced."""
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("(no DISCORD_WEBHOOK_URL set, printing instead)\n")
        print(text)
        return
    for chunk in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
        req = urllib.request.Request(
            url, data=json.dumps({"content": chunk}).encode(),
            # Discord's edge rejects the default Python-urllib agent with a 403.
            headers={"Content-Type": "application/json", "User-Agent": UA})
        urllib.request.urlopen(req, timeout=20).read()


def load_memory():
    """Never let a corrupt state file wedge every future run."""
    try:
        with open(MEMORY) as f:
            mem = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        mem = {}
    return {"flags": mem.get("flags", {}), "announced": mem.get("announced", [])}


def save_memory(mem, current_gw):
    # ~3 keys per gameweek for 38 weeks is noise in the diff; keep it recent.
    mem["announced"] = [k for k in mem["announced"]
                        if not k.startswith("gw")
                        or _key_gw(k) >= current_gw - 1]
    d = os.path.dirname(os.path.abspath(MEMORY))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(mem, f, indent=1, sort_keys=True)
    os.replace(tmp, MEMORY)          # atomic; a killed run cannot truncate it


def _key_gw(key):
    try:
        return int(key[2:].split("-")[0])
    except (ValueError, IndexError):
        return 0


def availability(p):
    return f"{p['status']}|{p['chance_of_playing_next_round']}|{p['news']}"


def build_report(entry, force):
    boot = get("bootstrap-static/")
    by_id = {p["id"]: p for p in boot["elements"]}
    club = {t["id"]: t["short_name"] for t in boot["teams"]}
    cur, nxt = current_and_next_event(boot)
    if cur is None and nxt is None:
        return None, None, None          # between seasons, nothing to do
    ref = cur or nxt
    nxt = nxt or cur

    picks = get(f"entry/{entry}/event/{ref['id']}/picks/")["picks"]
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

    deadline = datetime.datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    hours = (deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600

    def flagged():
        return [f"{by_id[p['element']]['web_name']} "
                f"({by_id[p['element']]['status']}/"
                f"{by_id[p['element']]['chance_of_playing_next_round']})"
                for p in picks
                if by_id[p["element"]]["status"] != "a"
                or by_id[p["element"]]["chance_of_playing_next_round"] not in (None, 100)]

    # 2. deadline proximity — tightest unfired window wins
    for mark in sorted(DEADLINE_ALERTS):
        key = f"gw{nxt['id']}-t{mark}"
        if 0 < hours <= mark and key not in mem["announced"]:
            mem["announced"].append(key)
            f = flagged()
            lines.append(f"**GW{nxt['id']} deadline in {hours:.0f}h** ({nxt['deadline_time']})\n"
                         + ("flagged: " + ", ".join(f) if f else "no availability problems"))
            break

    # 3. gameweek results, once scoring is final
    if cur and cur["finished"] and cur["data_checked"]:
        key = f"gw{cur['id']}-done"
        if key not in mem["announced"]:
            mem["announced"].append(key)
            e = get(f"entry/{entry}/")
            lines.append(
                f"**GW{cur['id']} final** — {e['summary_event_points']} pts "
                f"(average {cur['average_entry_score']}, best {cur['highest_score']})\n"
                f"overall rank {e['summary_overall_rank']:,} on {e['summary_overall_points']} pts")

    # 4. a manual run should always say something useful
    if force and not lines:
        e = get(f"entry/{entry}/")
        cap = next((by_id[p["element"]]["web_name"] for p in picks if p["is_captain"]), "?")
        f = flagged()
        lines.append(
            f"**Status** — GW{ref['id']}: {e['summary_event_points']} pts, "
            f"overall {e['summary_overall_points']} pts (rank {e['summary_overall_rank']:,})\n"
            f"captain: {cap}\n"
            f"GW{nxt['id']} deadline: {nxt['deadline_time']} ({hours:.0f}h)\n"
            f"flagged: {', '.join(f) if f else 'none'}")

    mem["flags"] = flags
    return lines, mem, ref["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="team_state.json")
    ap.add_argument("--force", action="store_true", help="post even if nothing changed")
    args = ap.parse_args()

    with open(args.state) as f:
        entry = json.load(f)["entry"]

    try:
        lines, mem, gw = build_report(entry, args.force)
    except Exception as e:
        # A cron that dies quietly is indistinguishable from a cron with
        # nothing to say, which is the failure this whole script exists to avoid.
        try:
            post(f"__**Cunha Matata**__\n**FPL watch failed**\n`{type(e).__name__}: {e}`")
        except Exception:
            pass
        raise

    if lines is None:
        print("no active gameweek")
        return

    if lines or args.force:
        # Post BEFORE persisting: if Discord is down, the alert must survive to
        # the next run rather than be marked announced and lost forever.
        post("__**Cunha Matata**__\n" + "\n\n".join(lines or ["nothing to report"]))
        print("posted:\n" + "\n\n".join(lines or ["(forced, nothing to report)"]))
    save_memory(mem, gw)
    if not lines:
        print("quiet: nothing to report")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Send FPL gameweek deadline reminders to WhatsApp groups via wacli."""

import argparse
import datetime
import subprocess
import sys
from fpl_api import get, current_and_next_event

GROUPS = [
    ("sports", "120363406157678834@g.us"),
    ("core", "447563241014-1580510037@g.us"),
]
WACLI = "/opt/homebrew/bin/wacli"


def build_reminder_text():
    boot = get("bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}

    cur, nxt = current_and_next_event(boot)
    target = nxt or cur
    if not target:
        return None

    gw_id = target["id"]
    dl = target["deadline_time"]
    dt = datetime.datetime.fromisoformat(dl.replace("Z", "+00:00"))
    bst_time = dt.astimezone(datetime.timezone(datetime.timedelta(hours=1)))
    deadline_str = bst_time.strftime("%A %d %B, %H:%M BST")

    fixtures = get(f"fixtures/?event={gw_id}")
    fix_lines = []
    for f in fixtures:
        th = teams[f["team_h"]]
        ta = teams[f["team_a"]]
        kt = datetime.datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00"))
        kt_bst = kt.astimezone(datetime.timezone(datetime.timedelta(hours=1))).strftime("%a %H:%M")
        fix_lines.append(f"• {th} v {ta} ({kt_bst})")

    tin = sorted(boot["elements"], key=lambda x: x["transfers_in_event"], reverse=True)[:3]
    tin_str = ", ".join(f"{p['web_name']} ({teams[p['team']]})" for p in tin)

    body = (
        f"FPL GW{gw_id} reminder\n\n"
        f"Deadline: {deadline_str} ({dl[:16]} UTC).\n\n"
        f"Key Fixtures:\n" + "\n".join(fix_lines[:5]) + "\n\n"
        f"Transfer momentum: {tin_str}."
    )
    return body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    msg = build_reminder_text()
    if not msg:
        print("No active GW found.")
        sys.exit(1)

    print("Reminder message:\n---")
    print(msg)
    print("---\n")

    for name, jid in GROUPS:
        if args.dry_run:
            print(f"[DRY-RUN] Would send to {name} ({jid})")
            continue
        print(f"Sending to {name} ({jid})...")
        cmd = [WACLI, "send", "text", "--to", jid, "--message", msg]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Failed to send to {name}: {res.stderr}", file=sys.stderr)
        else:
            print(f"Successfully sent to {name}")


if __name__ == "__main__":
    main()

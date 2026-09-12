#!/usr/bin/env python3
"""Capture weekly FPL research headless without credentials.

Collects public signals from official FPL API, LiveFPL predicted EOs,
price change predictions, and points model outputs.
Persists structured research outcomes to data/research/gw{gw}.json and .md.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request
import urllib.error

from fpl_api import UA, current_and_next_event, get, POS


def fetch_livefpl_json(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def generate_research(state_path="team_state.json", output_dir="data/research"):
    os.makedirs(output_dir, exist_ok=True)

    boot = get("bootstrap-static/")
    by_id = {p["id"]: p for p in boot["elements"]}
    team_name = {t["id"]: t["short_name"] for t in boot["teams"]}

    cur, nxt = current_and_next_event(boot)
    target_event = nxt or cur
    if not target_event:
        return None

    gw_id = target_event["id"]
    deadline = target_event["deadline_time"]

    # 1. Fixtures
    fixtures = get(f"fixtures/?event={gw_id}")
    fixture_list = []
    for f in fixtures:
        th = team_name[f["team_h"]]
        ta = team_name[f["team_a"]]
        fixture_list.append({
            "home": th,
            "away": ta,
            "kickoff": f["kickoff_time"],
        })

    # 2. LiveFPL Predicted EO
    eo_raw = fetch_livefpl_json(f"https://livefpl.us/predictedEOs/{gw_id}.json")
    top_eo = []
    if isinstance(eo_raw, dict) and "error" not in eo_raw:
        sorted_eo = sorted(eo_raw.items(), key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0, reverse=True)
        for pid_str, val in sorted_eo[:15]:
            p = by_id.get(int(pid_str))
            if p:
                top_eo.append({
                    "id": p["id"],
                    "name": p["web_name"],
                    "team": team_name[p["team"]],
                    "predicted_eo_pct": round(float(val) * 100, 1),
                })

    # 3. Price Move Predictions
    preds_raw = fetch_livefpl_json("https://livefpl.us/prediction.json")
    rises = []
    falls = []
    if isinstance(preds_raw, dict) and "error" not in preds_raw:
        for pid_str, val in preds_raw.items():
            try:
                fval = float(val)
                p = by_id.get(int(pid_str))
                if not p:
                    continue
                if fval >= 0.8:
                    rises.append({
                        "id": p["id"],
                        "name": p["web_name"],
                        "team": team_name[p["team"]],
                        "target_pct": round(fval * 100, 1),
                        "cost": p["now_cost"] / 10,
                    })
                elif fval <= -0.8:
                    falls.append({
                        "id": p["id"],
                        "name": p["web_name"],
                        "team": team_name[p["team"]],
                        "target_pct": round(fval * 100, 1),
                        "cost": p["now_cost"] / 10,
                    })
            except (ValueError, TypeError):
                continue
        rises.sort(key=lambda x: x["target_pct"], reverse=True)
        falls.sort(key=lambda x: x["target_pct"])

    # 4. Squad Availability Check
    entry_id = None
    squad_availability = []
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state_data = json.load(f)
                entry_id = state_data.get("entry")
        except Exception:
            pass

    if entry_id:
        try:
            ref_gw = cur["id"] if cur else gw_id
            picks_data = get(f"entry/{entry_id}/event/{ref_gw}/picks/")
            for p in picks_data.get("picks", []):
                e = by_id[p["element"]]
                status = e["status"]
                chance = e["chance_of_playing_next_round"]
                squad_availability.append({
                    "id": e["id"],
                    "name": e["web_name"],
                    "team": team_name[e["team"]],
                    "position": POS[e["element_type"]],
                    "is_starter": p["position"] <= 11,
                    "status": status,
                    "chance": chance,
                    "news": e["news"] or "",
                    "clean": status == "a" and chance in (None, 100),
                })
        except Exception:
            pass

    # 5. Top Form Players
    form_players = sorted(
        boot["elements"],
        key=lambda x: float(x.get("form") or 0),
        reverse=True
    )[:10]
    top_form = [{
        "id": p["id"],
        "name": p["web_name"],
        "team": team_name[p["team"]],
        "position": POS[p["element_type"]],
        "form": float(p["form"]),
        "total_points": p["total_points"],
        "cost": p["now_cost"] / 10,
    } for p in form_players]

    # Assemble JSON object
    research_data = {
        "gameweek": gw_id,
        "deadline_utc": deadline,
        "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "fixtures": fixture_list,
        "predicted_eo": top_eo,
        "price_changes": {
            "imminent_rises": rises[:10],
            "imminent_falls": falls[:10],
        },
        "squad_availability": squad_availability,
        "top_form": top_form,
    }

    # Write JSON
    json_path = os.path.join(output_dir, f"gw{gw_id}.json")
    with open(json_path, "w") as f:
        json.dump(research_data, f, indent=2)

    # Write Markdown summary
    md_path = os.path.join(output_dir, f"gw{gw_id}.md")
    with open(md_path, "w") as f:
        f.write(f"# FPL Research Digest: Gameweek {gw_id}\n\n")
        f.write(f"**Deadline:** {deadline}\n")
        f.write(f"**Captured:** {research_data['captured_at_utc']}\n\n")

        f.write("## 1. Key Fixtures\n\n")
        for fix in fixture_list:
            f.write(f"- {fix['home']} vs {fix['away']} @ {fix['kickoff']}\n")
        f.write("\n")

        f.write("## 2. Top Predicted Effective Ownership (LiveFPL)\n\n")
        f.write("| Player | Team | Predicted EO |\n|---|---|---|\n")
        for eo in top_eo[:10]:
            f.write(f"| {eo['name']} | {eo['team']} | {eo['predicted_eo_pct']}% |\n")
        f.write("\n")

        f.write("## 3. Imminent Price Changes\n\n")
        f.write("### Rises (Target >= 80%)\n")
        for r in rises[:5]:
            f.write(f"- {r['name']} ({r['team']}) £{r['cost']:.1f}m: {r['target_pct']}%\n")
        f.write("\n### Falls (Target <= -80%)\n")
        for fl in falls[:5]:
            f.write(f"- {fl['name']} ({fl['team']}) £{fl['cost']:.1f}m: {fl['target_pct']}%\n")
        f.write("\n")

        if squad_availability:
            f.write("## 4. Squad Availability Doubts\n\n")
            doubts = [s for s in squad_availability if not s["clean"]]
            if doubts:
                for d in doubts:
                    slot = "XI" if d["is_starter"] else "BEN"
                    f.write(f"- [{slot}] {d['position']} {d['name']} ({d['team']}): status={d['status']}, chance={d['chance']}%, news: {d['news']}\n")
            else:
                f.write("All 15 players clean.\n")
            f.write("\n")

        f.write("## 5. Top Form Assets\n\n")
        f.write("| Player | Pos | Team | Form | Total Pts | Price |\n|---|---|---|---|---|---|\n")
        for tf in top_form[:8]:
            f.write(f"| {tf['name']} | {tf['position']} | {tf['team']} | {tf['form']} | {tf['total_points']} | £{tf['cost']:.1f}m |\n")
        f.write("\n")

    print(f"Research saved: {json_path} and {md_path}")
    return research_data


def main():
    parser = argparse.ArgumentParser(description="Capture weekly FPL research headless.")
    parser.add_argument("--state", default="team_state.json", help="Path to team_state.json")
    parser.add_argument("--output-dir", default="data/research", help="Directory for research artifacts")
    args = parser.parse_args()

    res = generate_research(args.state, args.output_dir)
    if not res:
        print("Could not generate research (no active event).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

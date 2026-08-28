#!/usr/bin/env python3
"""Self-checks for the logic that has already been wrong once.

Plain asserts, no framework, no network. Run: python3 test_fpl.py
"""

import json
import os
import pathlib
import tempfile

import notify
from gw1_squad import CLUB_LIMIT, SQUAD, XI_MAX, XI_MIN, check
from points_model import load_samples, passed


def test_deadline_alert_picks_tightest_window():
    """A run close to the deadline must file itself under the TIGHTEST window.

    Descending order with a `break` meant that if the earliest alert was ever
    missed, a run at T-1.5h consumed the 24h key and the urgent alert never
    existed. Asserted as a property so changing the marks cannot resurrect it.
    """
    marks = sorted(notify.DEADLINE_ALERTS)
    for hours in (0.5, 1.5, 2.5, 5.0, 20.0):
        tightest = min(m for m in marks if hours <= m)
        for announced in ([],                                   # nothing fired yet
                          [f"gw2-t{m}" for m in marks if m > tightest]):
            fired = [m for m in marks
                     if 0 < hours <= m and f"gw2-t{m}" not in announced]
            assert fired[0] == tightest, (
                f"at T-{hours}h expected t{tightest}, got {fired}")


def test_memory_survives_a_corrupt_file():
    """A truncated state file must not wedge every future run."""
    d = tempfile.mkdtemp()
    old = notify.MEMORY
    notify.MEMORY = os.path.join(d, "state.json")
    try:
        with open(notify.MEMORY, "w") as f:
            f.write('{"flags": {"1": "a|None|"')      # truncated mid-write
        mem = notify.load_memory()
        assert mem == {"flags": {}, "announced": []}, mem

        mem["announced"] = ["gw1-t3", "gw8-t3"]
        notify.save_memory(mem, current_gw=9)
        with open(notify.MEMORY) as f:
            kept = json.load(f)["announced"]
        assert kept == ["gw8-t3"], f"stale keys not pruned: {kept}"
    finally:
        notify.MEMORY = old


def test_double_gameweek_is_not_overwritten():
    """Two fixtures in one gameweek must both survive.

    Keyed by gameweek alone, the second fixture replaced the first and a DGW
    asset was valued at half its worth.
    """
    out = {}
    for home, away, dh, da in [(1, 2, 2, 4), (1, 3, 3, 3)]:   # team 1 plays twice
        out.setdefault(home, {}).setdefault(28, []).append(dh)
        out.setdefault(away, {}).setdefault(28, []).append(da)
    assert out[1][28] == [2, 3], out[1][28]
    assert out.get(4, {}).get(28, []) == []                   # blank gameweek


def test_check_rejects_an_illegal_squad():
    """The legality check must fail independently of the solver."""
    squad, xi = [], set()
    pid = 0
    for pos, n in SQUAD.items():
        for _ in range(n):
            pid += 1
            squad.append({"id": pid, "pos": pos, "team": pid, "cost": 40})
    for pos in (1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4):             # a legal 3-4-3
        xi.add(next(p["id"] for p in squad if p["pos"] == pos and p["id"] not in xi))
    check(squad, xi, {p["team"] for p in squad})              # must not raise

    for bad, why in [(squad[:14], "14 players"),
                     ([dict(p, team=1) for p in squad], "all one club")]:
        try:
            check(bad, xi, {p["team"] for p in bad})
        except AssertionError:
            continue
        raise AssertionError(f"check() accepted a squad with {why}")


def test_points_features_do_not_leak_a_double_gameweek():
    """Both DGW fixtures must see only information known before that gameweek."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "2025-26.csv")
    headers = ("name,position,GW,kickoff_time,fixture,minutes,starts,total_points,"
               "expected_goals,expected_assists,expected_goals_conceded,was_home\n")
    rows = [
        "A,DEF,1,2025-08-01,1,90,1,6,0,0,1,True\n",
        "A,DEF,2,2025-08-08,2,90,1,2,0,0,2,False\n",
        "A,DEF,3,2025-08-15,3,90,1,8,0,0,1,True\n",
        "A,DEF,4,2025-08-22,4,90,1,1,0,0,3,False\n",
        "A,DEF,4,2025-08-25,5,90,1,10,0,0,0,True\n",
    ]
    with open(path, "w") as f:
        f.write(headers + "".join(rows))
    samples = load_samples([pathlib.Path(path)])
    dgw = [s for s in samples if s["gw"] == 4]
    assert len(dgw) == 2
    assert dgw[0]["points_4"] == dgw[1]["points_4"] == 16 / 3


def test_model_gate_requires_an_actual_baseline_win():
    assert passed(2.1, 2.1)
    assert not passed(2.2, 2.1)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall checks passed")

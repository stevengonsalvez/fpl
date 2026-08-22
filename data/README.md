# data/

## `baseline-2025-26.json`

`bootstrap-static` as it stood on 2026-08-20, before the GW1 deadline, while it
still reported **2025/26** season totals per player.

At GW1 kickoff the live endpoint reset every per-player counter to the current
season, so `minutes`, `total_points`, `starts`, `expected_goals_conceded_per_90`,
`defensive_contribution` and the rest are no longer retrievable for last season
from the API. This file is the only copy. Do not delete or regenerate it.

Every scoring rate in `gw1_squad.py` and `transfer_plan.py` reads from here;
availability, price, team and status come from the live feed.

| use the baseline for | use the live feed for |
|---|---|
| minutes, starts, total_points | status, news, chance_of_playing |
| xG, xA, xGC/90, defcon, bps | now_cost, selling price |
| per-90 scoring rates | team (players move clubs) |

Known limits of a single-season baseline:
- A player injured for most of last season (e.g. Isak, 694 mins) is scored as a
  rotation risk. The model cannot tell "was injured" from "is a squad player".
- A player who changed club carries his old club's output into a new context.
- A player whose role changed (promoted to starter, new manager) is mispriced.

These are the cases where human football knowledge should override the model.

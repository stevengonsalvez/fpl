---
name: fpl-scout
description: Headless quantitative FPL research and solver. Ingests official FPL APIs, LiveFPL predicted EOs, price change models, fixture difficulty, and outputs structured weekly research artifacts.
---

# FPL Scout

Extracts and models quantitative FPL signals headlessly without credentials.

## When to Use
- Generating the weekly pre-deadline research digest (`data/research/gw{gw}.json`).
- Fetching live crowd Effective Ownership (EO) from LiveFPL to gauge rank defense vs differential upside.
- Tracking price rise and fall probabilities to protect team value.
- Solving legal squad upgrades using expected points (EP) and MILP solvers.

## Core Commands
Run from the fpl workspace (`/Users/stevengonsalvez/orca/workspaces/fpl/penguin`):

1. **Generate Weekly Research Digest**:
   ```bash
   python3 research.py --state team_state.json
   ```
   Outputs:
   - `data/research/gw{gw}.json` (machine-readable)
   - `data/research/gw{gw}.md` (human-readable summary)

2. **Evaluate Legal Transfer Swaps**:
   ```bash
   python3 transfer_plan.py --state team_state.json --exclude-club MCI --top 10
   ```

3. **Check Squad Availability**:
   ```bash
   python3 squad_check.py --state team_state.json
   ```

## Signals Captured
- **FPL Bootstrap**: Player injury status (`status`, `chance_of_playing_next_round`), net transfer delta, form.
- **LiveFPL Predicted EO**: Top-10k and overall effective ownership percentages (`https://livefpl.us/predictedEOs/{gw}.json`).
- **LiveFPL Price Moves**: Imminent risers (target >= 80%) and fallers (target <= -80%) (`https://livefpl.us/prediction.json`).
- **Fixtures**: Kickoff times, home/away splits, FDR ratings.

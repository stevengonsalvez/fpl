---
name: fpl-manager
description: Autonomous FPL manager decision and squad execution engine. Synthesizes quantitative data from fpl-scout and qualitative intelligence from fpl-twitter to formulate final transfer, captain, and bench decisions, and coordinate team changes.
---

# FPL Manager

Synthesizes multi-source FPL research into definitive gameweek decisions for Cunha Matata (entry 7424382).

## Responsibilities
1. **Decision Synthesis**:
   - Ingest quantitative digest from `data/research/gw{gw}.json` (fpl-scout).
   - Ingest late injury / leak intelligence (fpl-twitter).
   - Filter moves by standing preferences: exclude Manchester City transfers (`--exclude-club MCI`), protect against Isak historical minutes distortion.
2. **Squad Plan Formulation**:
   - Captain and Vice-Captain call (lead with recommendation).
   - Transfer moves (weighing point gain over 5 GWs against hit threshold of 6.0 pts).
   - Bench priority order (placing fit playing bench assets first).
   - Chip strategy evaluation (WC, FH, BB, TC).
3. **Execution**:
   - Update `team_state.json` with current bank, free transfers, and accurate selling prices.
   - Present final decision cleanly via AskUserQuestion for user sign-off.
   - Coordinate submission to FPL.

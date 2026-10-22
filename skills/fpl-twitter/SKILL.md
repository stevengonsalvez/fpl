---
name: fpl-twitter
description: FPL qualitative intelligence scout across X / Twitter. Scans beat reporters, press conference roundups, early injury updates, and late lineup leaks using local browser sessions or search.
---

# FPL Twitter Intelligence

Scans and extracts qualitative signals from X / Twitter to resolve late injury doubts, tactical rotations, and early lineup leaks.

## Key Target Accounts & Searches
- **Injuries & Pressers**:
  - `@BenDinnery` / Premier Injuries (injury classifications, return dates)
  - `@ColmH14` (press conference manager quotes, starting doubt resolutions)
  - `@FPLStatus` (real-time status changes and official updates)
- **Early Lineup Leaks (T-90m to T-30m before deadline)**:
  - Club beat reporters and verified ITKs
  - Search query: `"(team name) leak" OR "(team name) lineup" OR "(player name) starting"`

## Workflow
1. Read current squad doubts from `data/research/gw{gw}.json` (e.g. 75% or 50% flags).
2. For each doubt, check latest tweets from press conference aggregators:
   - Example query: `from:ColmH14 (player_name OR club_name)`
   - Example query: `from:BenDinnery (player_name)`
3. In pre-deadline window (1 to 2 hours before deadline):
   - Check for early leaks for early kickoff matches.
4. Output structured intelligence:
   - Confirmed starters
   - Confirmed benched / ruled out
   - Tactical / role changes

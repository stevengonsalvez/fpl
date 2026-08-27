# Agent Handover — FPL autonomous manager (Cunha Matata)

**Generated**: 2026-08-27
**Agent Task**: continue building and running the autonomous FPL manager
**Repo**: https://github.com/stevengonsalvez/fpl (branch `main`)

> This document is deliberately self-contained. Do not assume you can see the
> user's skills, AGENTS.md, hooks or global rules — ainb codex sessions run
> under a separate CODEX_HOME and will not have them.

## Who this is for

Steven Gonsalvez ("Stevie"). Address him as Stevie. He wants decisions, not
option menus: lead with a recommendation, keep reasoning short, end with
concrete next steps. Never use em-dashes in any output. Sign commits (`-S`),
never mention AI/Claude/Codex in commit messages, one concern per commit,
never `git add -A`.

## The situation in one paragraph

Stevie plays Fantasy Premier League (entry **7424382**, team **Cunha Matata**).
The goal is a system that manages the team autonomously for the whole 2026/27
season: predict points, solve the optimal legal squad, decide transfers,
captain, bench and chips, and eventually submit them to FPL itself. GW1 is
finished (54 pts vs a 50 average, overall rank ~3.2m). GW2's deadline is
**2026-08-28T17:30:00Z**. The tooling and alerting are live; the real model
and auto-submit are not built yet.

## IMMEDIATE — before 2026-08-28T17:30:00Z

**Recommendation already reached: HOLD. Make no transfer.**

Pedro Porro was flagged injured (`status=i`, 0%) and has since cleared
(`status=a`, `chance_of_playing_next_round=100`, news empty). All 15 players
are available. The best available transfer gains only ~+1.4 pts over five
gameweeks, far below the ~+6 threshold that justifies anything. Not using the
free transfer banks it, giving two in GW3.

Re-verify before the deadline (things change):
```bash
python3 squad_check.py --state team_state.json
python3 transfer_plan.py --state team_state.json --exclude-club MCI --top 10
```

**Stevie must make any actual transfer himself** — see "What you must not do".

## Current squad (GW1)

```
XI   GK  Kinsky (TOT)
     DEF Gabriel (ARS)  Calafiori (ARS)  Hume (SUN)
     MID B.Fernandes (MUN)  Szoboszlai (LIV)  Mbeumo (MUN)  Rogers (CHE)
     FWD Calvert-Lewin (LEE)  Isak (LIV)  Joao Pedro (CHE)
BEN  Button (IPS)  Pedro Porro (TOT)  Schade (BRE)  Shaw (MUN)
```
1 free transfer, GBP 0.5m bank, all four chips unused (wildcard, free hit,
bench boost, triple captain).

Stevie's standing preference: **do not transfer in Manchester City players**
(his read: Rodri gone, new coach). Pass `--exclude-club MCI`. Mention it if a
City player would otherwise top the list, but respect the exclusion.

## What exists and works

| file | purpose |
|---|---|
| `fpl_api.py` | FPL public API access, retry+backoff, required User-Agent |
| `gw1_squad.py` | MILP squad optimiser (PuLP), effective-ownership aware |
| `transfer_plan.py` | ranks legal single swaps by expected points |
| `squad_check.py` | pre-deadline availability report |
| `notify.py` | decides whether to speak, posts to Discord |
| `test_fpl.py` | self-checks, no framework, no network — run this |
| `data/baseline-2025-26.json` | archived season stats — read `data/README.md` |
| `plans/fpl-ai-manager-spec.md` | full spec and design decisions |
| `.github/workflows/fpl.yml` | cron every 30 min, runs tests then `notify.py` |

Live: GitHub Actions runs every 30 minutes and posts to Discord only when
something changed, a deadline is within 24/6/2 hours, or a gameweek finished.
`DISCORD_WEBHOOK_URL` is set as a repo secret.

```bash
pip install pulp
python3 test_fpl.py                       # must pass before you commit
python3 notify.py --state team_state.json --force   # prints if no webhook set
```

## Traps that have already cost time

1. **`data/baseline-2025-26.json` is irreplaceable.** The live `bootstrap-static`
   endpoint reset every per-player counter to zero at GW1 kickoff. Last season's
   minutes, points, xG and defensive numbers cannot be re-fetched. Every scoring
   rate depends on this file. Never delete or regenerate it.
2. **Discord's edge 403s the default Python urllib User-Agent.** `fpl_api.UA`
   exists for this. Keep it on every request.
3. **GitHub drops scheduled runs.** Gaps of 8.2h were observed against a 2h
   cron, which is why it now runs every 30 minutes with three deadline marks.
   Do not reduce the frequency.
4. **`team_state.json` (bank, selling prices, free transfers) is hand-exported**
   from the authenticated `/api/my-team/{entry}/` endpoint and goes stale.
   `transfer_plan.py` deliberately fails loudly rather than guessing a selling
   price, because selling price is below market price for any player who rose.
5. **Scheduled workflows only fire from the default branch.** Anything that
   must run on cron has to land on `main`.
6. The Discord webhook posts to a channel named via webhook "Spidey Bot";
   Stevie initially could not find the messages.

## Known model limitations — human judgement should override

The scoring model uses a single season of history and is blind to:
- players injured last season (scored as rotation risks — **Isak is the known
  example, do not recommend selling him on a low score**)
- players who changed club (old club's output carried into a new context)
- players whose role changed, a new manager, or a departed teammate

If the model's advice contradicts obvious football knowledge, the model is
probably wrong. Say so rather than defending the number.

## Work still to do, in priority order

1. **Re-verify and act on the GW2 deadline** (2026-08-28T17:30:00Z). Highest
   priority; everything else can wait.
2. **A real points model.** Currently a heuristic: last season's points-per-90,
   scaled by start rate and fixture difficulty. The spec calls for a per-position
   gradient-boosted model with a separate minutes model, plus free xG/xA/xGC
   scraped from FBref/Understat. Backtest before trusting it.
3. **Auto-submit.** Nothing is submitted automatically yet. Needs an
   authenticated FPL session; the plan is a headless-browser login that caches
   the session cookie into a GitHub secret. Login is at
   `account.premierleague.com` (Ping OAuth); `users.premierleague.com` is dead
   and the login form carries a `dvResponse` device-fingerprint field.
4. **Chip strategy.** All four chips are unused. Bench Boost and Triple Captain
   are available from GW1; Wildcard only from GW2. Needs a scheduler that scans
   for blank and double gameweeks.
5. **GitHub Pages dashboard** — squad, predicted vs actual, rank over time.
6. **Mini-league rival tracking** once Stevie joins leagues (he has not yet).

## Useful data sources found

livefpl publishes open JSON, no auth:
- `https://livefpl.us/predictedEOs/{gw}.json` — predicted effective ownership,
  **current and reliable**, this is what the rank-aware objective uses
- `https://livefpl.us/planner/extended_api.json` — element data + price projections
- `https://livefpl.us/api/prices.json`, `https://livefpl.us/prediction.json` — price moves
- **stale, do not use**: `top10k.json`, `elite.json`, `top_transfers.json` all
  carry last season's final figures

## What you must not do

- **Do not log in to FPL or type Stevie's password anywhere.** Credentials are
  in his Bitwarden. Ask him to authenticate; he can do it in seconds.
- **Do not make transfers, activate chips or change the team on his behalf**
  without him explicitly approving that specific change first.
- Do not post to Discord outside the existing `notify.py` behaviour.
- Do not force-push, and do not rewrite `main`.

## Success criteria for your session

- The GW2 deadline passes with the right decision made and no deadline missed.
- `python3 test_fpl.py` passes and CI stays green.
- Any new work is committed in small signed commits and pushed to `main` via a
  PR, with the spec updated if a design decision changed.

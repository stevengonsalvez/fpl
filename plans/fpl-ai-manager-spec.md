# Specification: Cunha Matata — Autonomous FPL Manager

**Generated from:** interactive interview (no prior plan file)
**Interview date:** 2026-08-20
**Version:** 1.0
**Season:** 2026/27 (38 gameweeks)
**Team name:** `Cunha Matata` (12 chars, within FPL's 20-char limit)
**FPL entry id:** `7424382` (created 2026-08-21, GW1)
**Login:** account.premierleague.com (Ping OAuth); `users.premierleague.com` is dead

## Executive Summary

A Python system that manages a Fantasy Premier League team autonomously for a full
season: it predicts player points, solves for the optimal legal squad under FPL's
constraints, decides transfers/captain/bench/chips, and submits those decisions to
FPL itself before every deadline. A human sees a Discord report and a GitHub Pages
dashboard, and can override until the deadline, but takes no action by default.

**Hard near-term constraint:** GW1 deadline is `2026-08-21T17:30:00Z` (21 Aug, 18:30 BST).
A legal squad must be entered before then via a throwaway script, ahead of any real
engineering.

## Objectives

### Primary Goals
- Enter a squad before the GW1 deadline (~21h from spec authoring).
- Self-manage all 38 gameweeks with zero required human input.
- Beat the overall average manager score materially; target top 10% overall rank.
- Win the mini-leagues Stevie joins (rival-aware strategy).

### Success Metrics
| Metric | Target |
|--------|--------|
| Overall rank (final) | Top 10% (≈ top 725k of 7.25m) |
| Stretch rank | Top 100k |
| Deadlines missed | 0 of 38 |
| Model calibration (MAE, predicted vs actual player pts) | < 1.6 pts/player/GW |
| Points vs global average | +250 pts over season |
| Human interventions required | ≤ 3 over season |

## Scope

### In Scope
- FPL API ingestion, historical store, weekly refresh
- Free xG/xA/xGC scraping (FBref / Understat)
- Minutes-played model + points prediction model (per position)
- MILP squad/transfer optimiser with multi-GW lookahead
- Effective-ownership / rank-aware objective
- Crowd signal via livefpl's open JSON (no manager scraping needed)
- Chip scheduling (WC ×2, FH ×2, BB ×2, TC ×2)
- Authenticated auto-submit of transfers, lineup, captain, chips
- Discord pre-deadline + post-gameweek reports
- Static GitHub Pages dashboard
- Mini-league rival tracking and strategy adjustment
- GitHub Actions cron scheduling

### Out of Scope
- Paid data feeds (FPL Review, Fantasy Football Fix)
- Social/Twitter/Reddit sentiment scraping
- Public blog of the season
- Mobile app, real-time in-play features
- Multi-team / multi-user support

### Future Considerations
- Blend a paid predicted-points feed and A/B it against the in-house model
- Press-conference / injury-news LLM ingestion
- Bayesian team-strength model (Dixon-Coles) replacing FDR
- Season-long backtest harness on prior seasons' data

## Technical Requirements

### Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ FPL API      │   │ FBref /      │   │ Top-10k      │
│ bootstrap,   │   │ Understat    │   │ manager      │
│ fixtures,    │   │ xG/xA/xGC    │   │ squads       │
│ live, prices │   │              │   │              │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └────────┬─────────┴─────────┬────────┘
                ▼                   ▼
        ┌───────────────┐   ┌───────────────┐
        │ ingest layer  │──▶│ store         │
        │ (rate-limited)│   │ parquet+sqlite│
        └───────────────┘   └───────┬───────┘
                                    ▼
                         ┌──────────────────────┐
                         │ feature build        │
                         │ form, xGI/90, mins,  │
                         │ FDR, EO, price, set  │
                         │ pieces, home/away    │
                         └──────────┬───────────┘
                                    ▼
             ┌──────────────────────┴────────────────┐
             ▼                                       ▼
    ┌──────────────────┐                  ┌──────────────────┐
    │ minutes model    │                  │ points model     │
    │ P(start),P(60+)  │──── EP = ───────▶│ GBM per position │
    └──────────────────┘   P(mins)×pts    └────────┬─────────┘
                                                   ▼
                                        ┌──────────────────────┐
                                        │ MILP optimiser       │
                                        │ 5-8 GW horizon       │
                                        │ squad+transfers+chips│
                                        └──────────┬───────────┘
                                                   ▼
                                   ┌───────────────┴────────────┐
                                   ▼                            ▼
                        ┌────────────────────┐      ┌────────────────────┐
                        │ FPL submit         │      │ report + dashboard │
                        │ (Playwright cookie)│      │ Discord + GH Pages │
                        └────────────────────┘      └────────────────────┘
```

### Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `ingest/fpl.py` | Pull bootstrap-static, fixtures, element-summary, live | `httpx` + retry/backoff |
| `ingest/xg.py` | Weekly xG/xA/xGC scrape, name-matched to FPL IDs | `httpx` + `beautifulsoup4` / `soccerdata` |
| `ingest/crowd.py` | Effective ownership + top-10k ownership, from livefpl's open JSON | plain HTTP, no scraping |
| `store/` | Immutable per-GW snapshots + season history | parquet (history) + sqlite (state) |
| `features/` | Feature engineering, leak-free per-GW joins | `pandas` / `polars` |
| `models/minutes.py` | P(appears), P(60+ mins) classifier | LightGBM / sklearn |
| `models/points.py` | Expected points per position, 1..8 GW ahead | LightGBM + ridge baseline |
| `optimiser/squad.py` | MILP: squad selection, transfers, captain, bench order, chips | PuLP or OR-Tools CBC |
| `submit/session.py` | Login → cookie cache → authenticated FPL calls | Playwright + `httpx` |
| `submit/actions.py` | Transfers, lineup, captain/vice, chip activation | FPL private endpoints |
| `report/discord.py` | Pre-deadline plan + post-GW review | webhook POST |
| `report/dashboard.py` | Static HTML build committed to `docs/` | jinja2 + plotly/vega |
| `.github/workflows/` | Cron triggers, secrets, artifact commits | GitHub Actions |

### Domain rules the optimiser MUST encode

| Rule | Value |
|------|-------|
| Squad size | 15 (2 GK, 5 DEF, 5 MID, 3 FWD) |
| Budget | £100.0m |
| Max per Premier League club | 3 |
| Valid formations | 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD, 11 starters |
| Free transfers | 1/GW, roll up to 5 banked; extra transfers cost −4 |
| Transfer cap | 20 per gameweek |
| Sell-on fee | 50% of profit, rounded down to £0.1m |
| Chips (per half-season) | Wildcard, Free Hit, Bench Boost, Triple Captain |
| Chip windows | GW1–19 and GW20–38; Wildcard 1 available GW2–19 |
| Captain | 2× points; vice auto-applies if captain plays 0 mins |
| Bench | Auto-subs in bench order if a starter plays 0 mins; GK sub is GK-only |
| Price changes | ±£0.1m nightly, driven by net transfer flow |

### What the model must "take into account" (feature inventory)

**Player-level**
- Minutes: starts, rotation risk, sub-appearance rate, congestion (Euro/cup fixtures)
- Underlying: xG/90, xA/90, xGI/90, shots in box, big chances, touches in box
- Set pieces: penalties, direct FKs, corners — the single biggest points multiplier
- Defensive: xGC/90, clean-sheet probability, defensive-contribution points, saves rate (GK)
- Form vs baseline: recent 4-6 GW weighted, regressed to season/career mean
- Availability: injury flag, `chance_of_playing_next_round`, suspension (yellow-card accumulation)
- Bonus: BPS rate per 90 — a systematically underweighted points source
- Age/transfer status, new signings with no PL history (prior from league-adjusted stats)

**Fixture-level**
- Opponent strength, split home/away, attack vs defence separately (not the blunt FDR number)
- Fixture *runs*, not single fixtures — a 6-GW rolling difficulty
- Blanks and doubles (cup progression, postponements) — drives chip timing
- Kickoff congestion and European commitments

**Value-level (the "per million" question)**
- Raw points-per-million is a trap: it over-rewards cheap bench fodder that never plays.
  Use **EP per £m on starters only**, plus explicit £4.0–4.5m non-playing bench slots.
- Team-level budget allocation: the optimiser resolves this globally, not per player —
  the real question is never "is Haaland worth £15.5m" but "does the £15.5m squad
  beat the best £100m squad without him".
- Price-change forecasting: buy before a rise, sell before a fall — worth ~£2-4m of
  team value over a season, which converts into better squads later.

**Crowd/rank-level**
- Effective ownership (EO) = ownership + captaincy%, weighted to top-10k not overall
- Transfer flow in/out — mass moves often precede official injury news
- Template risk: the cost of *not* owning a 70%-owned asset is a real, asymmetric risk
- Mini-league rival squads: differential aggression when behind, template-shield when ahead

### Objective function

**Rank-aware expected points.** Maximise expected points over a rolling 5–8 GW
horizon, penalised by variance relative to effective ownership:

```
maximise  Σ_gw Σ_p ( EP[p,gw] × start[p,gw] + EP[p,gw] × captain[p,gw] )
        − λ_hit × 4 × extra_transfers
        − λ_eo  × Σ_p ( EO[p] × (1 − own[p]) × EP[p] )     # template risk
```

- `λ_eo` is tuned so the agent will captain a 70%-owned premium at slightly lower raw
  EP, but will still take a genuine differential when the EP edge is clear.
- Hits taken only when net gain over the horizon clears ≈ +6 pts.

### Auth strategy

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Bitwarden    │──▶│ Playwright   │──▶│ cookie cache │
│ (bw CLI)     │   │ headless     │   │ (GH secret / │
│ creds        │   │ login        │   │  encrypted)  │
└──────────────┘   └──────────────┘   └──────┬───────┘
                                             ▼
                                   ┌────────────────────┐
                          reuse ──▶│ httpx + cookie     │
                          until    │ direct API submit  │
                          401/403  └────────────────────┘
```

- Credentials live in Bitwarden; CI reads them from GitHub Actions secrets.
- Cookie re-used until it 401s, then a fresh headless login.
- **Never** commit cookies, credentials, or the Bitwarden master key.
- Fallback chain on failure: retry login → full browser UI automation → Discord alert
  to Stevie with the exact moves to make manually.

### Performance Requirements
- Full weekly pipeline (ingest → predict → optimise → submit) completes in < 10 min
- Top-10k crowd scrape completes in < 25 min, rate-limited, resumable
- MILP solves in < 60s for an 8-GW horizon
- Submission fires no later than T−2h before deadline, with a T−30m retry pass

### Security Requirements
- All secrets in GitHub Actions secrets / Bitwarden; zero secrets in the public repo
- Public repo must be scanned for accidental credential commits pre-push
- Scraping respects rate limits and identifies honestly; no aggressive parallelism
- Submission is idempotent — a retry must never double-apply transfers

## Operational Flows

### Weekly cycle

```
GW ends          T−72h            T−3h          T−2h       deadline
   │               │                │             │            │
   ▼               ▼                ▼             ▼            ▼
┌──────┐      ┌─────────┐     ┌──────────┐  ┌─────────┐  ┌─────────┐
│ingest│─────▶│ retrain │────▶│ optimise │─▶│ SUBMIT  │─▶│ locked  │
│+score│      │ + crowd │     │ + Discord│  │ + verify│  │         │
│report│      │  scrape │     │  preview │  │         │  │         │
└──────┘      └─────────┘     └──────────┘  └─────────┘  └─────────┘
                                    │
                                    ▼
                            Stevie may override
                            any time before deadline
```

### Edge cases

| Scenario | Expected behaviour |
|----------|--------------------|
| Deadline moved / GW rescheduled | Cron re-reads `deadline_time` from API every run; never hardcode |
| Cookie expired at T−2h | Re-login; if that fails, Discord alert with manual instructions + retry at T−30m |
| FPL API down | Exponential backoff, use last cached state, alert if still down at T−1h |
| Solver infeasible | Fall back to "no transfer, best XI from current squad", alert |
| Player flagged injured after submit | Re-run at T−30m; apply a corrective transfer if EP gain justifies it |
| Double gameweek announced | Re-plan chips; Bench Boost / Triple Captain candidates re-scored |
| Blank gameweek | Free Hit considered; solver must handle < 11 available players |
| Price change makes plan illegal | Re-solve at submit time against live prices, never against cached |
| Two GitHub Actions runs overlap | Lock file in repo / concurrency group on the workflow |
| Model predicts nonsense (NaN, negative) | Sanity gate before optimise; fall back to heuristic EP, alert |

## Constraints & Dependencies

### Technical Constraints
- FPL private endpoints are undocumented and can change without notice
- Cloudflare fronts the login; headless automation may be blocked at any time
- GitHub Actions free tier: 2000 min/month (ample; the pipeline uses ~60 min/month)
- GitHub Pages requires a public repo on the free tier

### External Dependencies
| Dependency | Risk if it breaks |
|------------|-------------------|
| `fantasy.premierleague.com/api` | Total — no data, no submission |
| FBref / Understat | Degraded model; falls back to FPL-only features |
| Bitwarden CLI | Cannot re-login; cached cookie carries until expiry |
| Discord webhook | Reports lost; submission unaffected |

### Timeline Constraints
| Milestone | When |
|-----------|------|
| GW1 squad entered | **2026-08-21 by 18:30 BST — hard** |
| Repo scaffold + ingest + store | GW1–2 |
| Baseline model + optimiser (recommend-only) | by GW3 deadline |
| Auto-submit live | by GW5 deadline |
| Dashboard + crowd signal | by GW8 |
| Rival tracking | when mini-leagues are joined |

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Missed deadline (auth/cron failure) | High | Med | T−2h submit + T−30m retry + Discord alert + manual fallback instructions |
| Cloudflare blocks automated login | High | Med | Cookie caching minimises logins; browser-UI fallback; recommend-only mode as last resort |
| Model worse than gut instinct | Med | Med | Backtest on prior seasons before enabling auto-submit; keep a heuristic baseline to compare |
| FPL private API changes shape | High | Low | Contract tests on endpoints; alert on schema drift |
| Overfitting to a small sample | Med | High | Regularised models, per-position, walk-forward validation only |
| Secrets leak in public repo | High | Low | Secrets only in Actions secrets; pre-commit secret scan |
| Chips wasted early | Med | Med | Chip scheduler requires a modelled threshold, not a calendar heuristic |
| GW1 squad is bad | Low | Med | Wildcard available GW2 onwards — a bad start is fully reversible for free |

## Decisions Made

| Decision | Chosen | Alternatives considered | Rationale |
|----------|--------|-------------------------|-----------|
| GW1 approach | Throwaway optimiser script + Stevie approves | Manual gut pick; skip GW1 | Gets a real team scoring in 21h; Wildcard makes any error free to fix |
| Autonomy | Auto-submit, notify after | Propose-and-approve; hybrid | Matches the stated aim of a genuinely self-managing team |
| Stack | Python + GitHub Actions cron | CF Workers; TypeScript/Vercel | Best optimisation + ML ecosystem; free hosting; repo is the deployment |
| Data | FPL API + free xG scrape + GBM | FPL-only heuristic; paid feeds; ensemble | Real edge over template, zero ongoing cost, own the model |
| Objective | Rank-aware expected points | Pure EP; aggressive differential; safety-first | Balances the asymmetric risk of missing a template premium |
| Auth | Playwright login → cached cookie | Manual cookie; full UI automation | Only approach that survives a whole season unattended |
| Crowd signal | Scrape top-10k manager squads | Named elites; social scraping; none | Free, quantified elite ownership + early injury signal |
| Transfers | Solver decides; hits only if +EP over 5GW | Conservative; aggressive | Disciplined without leaving points on the table |
| Comms | Discord webhook + GH Pages dashboard | Silent; LLM writeup | Visibility without obligation |
| Repo | Public | Private | GH Pages free; secrets stay in Actions secrets |
| Leagues | Overall rank + mini-league rival tracking | Overall only | Rival-aware strategy is where the real fun is |
| Team name | `Cunha Matata` | Bruno Mars Attacks; Rashford Gump; Yoro Only Live Once | Man Utd + Lion King (1994); 12 chars; changeable free anytime |

### Deferred Decisions
- Which mini-leagues to join — Stevie supplies codes when he has them
- Paid-feed blending — revisit if in-house model underperforms by GW12
- Discord channel/server target — supplied at setup
- Backtest depth (how many prior seasons) — depends on data availability

## Implementation Notes

### Priority Order
1. **GW1 squad in before 21 Aug 18:30 BST** (throwaway solver + manual entry) — blocking
2. Repo scaffold, FPL ingest, parquet/sqlite store, GH Actions skeleton
3. Feature build + baseline points model + minutes model
4. MILP optimiser (recommend-only), Discord pre-deadline report
5. Backtest harness — prove the model before trusting it
6. Auth layer + auto-submit + verification + retry
7. Top-10k crowd scrape → effective ownership feature
8. Chip scheduler
9. GH Pages dashboard
10. Mini-league rival tracking

### Technical Debt Accepted
- GW1 script is throwaway — deliberately not the real architecture
- Name-matching FPL players to FBref/Understat is fuzzy; a manual override map is fine
- First model ships without a full backtest; auto-submit stays off until backtested

## Open Questions

- [ ] Discord server/channel for the webhook
- [ ] Mini-league codes to join
- [ ] Prior-season data availability for backtesting (FPL historical repos vs own archive)
- [ ] Does Stevie want a Wildcard planned for a specific early GW, or left to the solver

---

*This specification was generated through systematic interview of the plan author.*


## Addendum — livefpl open JSON (found 2026-08-20)

livefpl.net's planner is a static SPA over public, unauthenticated JSON. This
removes the entire "scrape top-10k manager squads" epic from the plan.

| Endpoint | Contents | Freshness |
|----------|----------|-----------|
| `livefpl.us/predictedEOs/{gw}.json` | predicted effective ownership per player, per GW | **current** — use this |
| `livefpl.us/top10k.json` | top-10k ownership | **stale** — last season's final snapshot |
| `livefpl.us/elite.json` | elite-manager ownership | **stale** — same |
| `livefpl.us/planner/extended_api.json` | full element data + price-change projections | current |
| `livefpl.us/planner/all_player_info.json` | last-season per-player stat dump (xg, xa, defcon, bps) | last season |
| `livefpl.us/planner/fdr_ratings.json` | per-fixture difficulty + display colours | current |
| `livefpl.us/api/prices.json`, `livefpl.us/prediction.json` | price-rise/fall predictions | current |
| `livefpl.us/top_transfers.json` | net transfer flow, `[id_in, id_out, count, share]` | current |

Traps found:
- `top10k.json` and `elite.json` carry LAST season's final ownership. Timber reads
  89% there against 0% actual. Validate any ownership feed against
  `bootstrap-static.selected_by_percent` before trusting it.
- The planner UI itself is gated on an FPL ID; the JSON is not.
- FPL's own `ep_next` is a near-flat preseason prior (4.0 for Haaland *and* for a
  midtable midfielder). Do not blend it into a points model preseason.
- `livefpl.net` 302s to `plan.livefpl.net` for some routes; data always lives on
  `livefpl.us`.

Chip note: Bench Boost and Triple Captain are available from **GW1**; Wildcard only
from GW2. A GW1 Bench Boost is a live strategic option the optimiser must consider.

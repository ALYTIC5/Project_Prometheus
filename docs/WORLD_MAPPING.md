# World State Mapping — WorldState fields ↔ Database Source

This document traces every field in `WorldState` to its source table/column/query.
Fields whose source doesn't exist yet are marked with the prompt that will build them.

**Last updated:** Prompt 1 — World deployed empty
**Next update:** Each prompt must update this when its building activates.

---

## WorldState Root Fields

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `tick` | `ohlcv_bars` row count | Live (Prompt 2) | Increments with each new bar ingested |
| `generated_at` | `NOW()` at projection time | Live | |
| `source_data_version` | `data_versions.id` (latest) | Prompt 2 | Set when ingestion runs |

---

## Climate (Market Regime)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `climate.regime` | `regime_classification.current_regime` | Prompt 5 | Bear/Bull/HighVol/LowVol/Trending/Ranging/Crisis |
| `climate.volatility_percentile` | `regime_classification.volatility_percentile` | Prompt 5 | 0-1 percentile of current vol vs history |
| `climate.trend_strength` | `regime_classification.trend_strength` | Prompt 5 | ADX or similar trend metric 0-1 |
| `climate.crisis_flag` | `regime_classification.crisis_flag` | Prompt 5 | Boolean from statistical classification |
| `climate.market_open` | `market_hours.is_open` | Prompt 2 | Always true for crypto 24/7 |

---

## Districts (Per Strategy Family)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `districts[].id` | `strategy_families.family` | Prompt 4 | e.g. "MOM", "MRV", "CARRY" |
| `districts[].name` | Derived from family | Live | Family + " District" |
| `districts[].archetype` | `strategy_families.archetype` | Prompt 4 | "momentum", "mean_reversion", etc. |
| `districts[].population_by_status.*` | `strategies` status counts | Prompt 4 | GROUP BY family, status |
| `districts[].health` | `strategies` avg OOS Sharpe | Prompt 5 | Normalized 0-1 from validation |
| `districts[].activity` | `experiments` running count | Prompt 4 | Running experiments / family |
| `districts[].portfolio_weight` | `portfolio.allocation_pct` | Prompt 8 | From paper trading positions |
| `districts[].building_state` | `construction_manifest` | Live | Mirrors structure phase |
| `districts[].alert_flags[]` | `strategy_alerts` table | Prompt 10 | Drawdown, divergence, drift |

---

## Agents (Active Jobs)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `agents[].id` | `jobs.id` | Prompt 4 | `JOB-YYYYMMDD-NNN` |
| `agents[].role` | `jobs.agent_role` | Prompt 4 | builder/scribe/engineer/... |
| `agents[].from_location` | `jobs.current_stage` | Prompt 4 | Building name |
| `agents[].to_location` | `jobs.next_stage` | Prompt 4 | Building name |
| `agents[].progress` | `jobs.progress_pct` | Prompt 4 | 0.0-1.0 |
| `agents[].experiment_id` | `jobs.experiment_id` | Prompt 4 | FK to experiments |

---

## Structures (Pipeline + Registry Components)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `structures[].id` | `construction_manifest` key | Live | library, forge, oracle, etc. |
| `structures[].kind` | `construction_manifest.kind` | Live | |
| `structures[].construction_phase` | Derived from `activates_on` row counts | Live | SCAFFOLDING → ACTIVE when table has rows |
| `structures[].load` | `jobs` queue depth / capacity | Prompt 4 | |
| `structures[].queue_depth` | `jobs` pending count for that building | Prompt 4 | |
| `structures[].status` | Derived from phase | Live | idle/active/degraded |
| `structures[].verdict` | `component_registry.verdict` | Prompt 6 | UNPROVEN/VALUABLE/NEUTRAL/HARMFUL |
| `structures[].description` | `construction_manifest.description` | Live | |
| `structures[].prompt_built` | `construction_manifest.prompt` | Live | |

---

## Events (Recent State Transitions)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `events[].type` | `world_events.event_type` | Prompt 1 | experiment_created, validation_completed, etc. |
| `events[].subject_id` | `world_events.subject_id` | Prompt 1 | experiment_id, strategy_id, etc. |
| `events[].severity` | `world_events.severity` | Prompt 1 | info/warning/critical |
| `events[].timestamp` | `world_events.created_at` | Prompt 1 | |
| `events[].drill_down_url` | `/world/drilldown/{type}/{id}` | Live | Frontend route |
| `events[].message` | `world_events.message` | Prompt 1 | Human-readable |

---

## Treasury

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `treasury.total_equity` | `portfolio.total_equity` | Prompt 8 | Paper trading equity |
| `treasury.allocation_by_family` | `portfolio.positions` by family | Prompt 8 | |
| `treasury.drawdown` | `portfolio.max_drawdown_pct` | Prompt 8 | |
| `treasury.paper_pnl_today` | `paper_trades` P&L today | Prompt 8 | |
| `treasury.benchmark.equity` | `benchmark_equity` latest | Prompt 2 | €1,000 buy-and-hold |
| `treasury.benchmark.return_pct` | `benchmark_equity` return | Prompt 2 | |
| `treasury.benchmark.sharpe` | `benchmark_metrics.sharpe` | Prompt 2 | |
| `treasury.benchmark.max_drawdown` | `benchmark_metrics.max_drawdown` | Prompt 2 | |
| `treasury.vs_benchmark.excess_return` | `portfolio` - `benchmark` | Prompt 8 | |
| `treasury.vs_benchmark.excess_sharpe` | `portfolio` - `benchmark` | Prompt 8 | |
| `treasury.vs_benchmark.winning` | `excess_return > 0` | Prompt 8 | |
| `treasury.infra_cost_mtd` | `cost_tracking.infra_usd_mtd` | Prompt 10 | Railway usage estimate |
| `treasury.llm_cost_mtd` | `llm_usage` sum | Prompt 9 | |

---

## Laws (Compliance Status)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `laws[].law_id` | Hardcoded (1-8) | Live | CLAUDE.md laws |
| `laws[].name` | Hardcoded | Live | |
| `laws[].compliant` | `law_violations` table check | Prompt 10 | True if no open violations |
| `laws[].last_violation` | `law_violations` latest | Prompt 10 | |
| `laws[].summary` | Hardcoded | Live | One-line reminder |

---

## Scoreboard (The Ultimate Question)

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `scoreboard.starting_capital` | `1000` (constant) | Live | €1,000 |
| `scoreboard.currency` | `EUR` (constant) | Live | |
| `scoreboard.system_value` | `treasury.total_equity` | Prompt 8 | — while no live paper |
| `scoreboard.benchmark_value` | `treasury.benchmark.equity` | Prompt 2 | |
| `scoreboard.excess` | `system_value - benchmark` | Prompt 8 | |
| `scoreboard.infra_cost_to_date` | `cost_tracking.infra_usd_total` | Prompt 10 | |
| `scoreboard.net_after_costs` | `excess - infra_cost` | Prompt 8+10 | |
| `scoreboard.verdict` | Derived from `net_after_costs` | Prompt 8 | SYSTEM_WINNING / HOLDING_WINNING / INCONCLUSIVE / NOT_STARTED |

---

## Build Progress

| WorldState Field | Source | Status | Notes |
|---|---|---|---|
| `build_progress.total` | `len(CONSTRUCTION_MANIFEST)` | Live | 12 buildings |
| `build_progress.active` | Count of ACTIVE structures | Live | |
| `build_progress.scaffolding` | Count of SCAFFOLDING structures | Live | |

---

## Table Activation Schedule by Prompt

| Prompt | Tables Created | Buildings Activated |
|---|---|---|
| 0 | (core: experiments, results, decisions, id_counters, policy_versions) | watchtower, monument |
| 1 | world_events, health | watchtower, monument |
| 2 | ohlcv_bars, data_versions, benchmark_equity | library, treasury |
| 3 | (core config) | — |
| 4 | strategies, experiments, results, decisions | forge, arena, archive, underworld |
| 5 | validation_results, holdout, regime_classification | oracle, vault |
| 6 | ablation, component_registry | temple |
| 7 | population, mutations | (districts populate) |
| 8 | paper_trades, portfolio, paper_reconciliation | harbour |
| 9 | llm_hypotheses, llm_ingestion, llm_budget | scholars |
| 10 | alerts, cost_tracking, strategy_alerts | all buildings get events |
| 11 | knowledge_facts, validation_experiments | temple inscriptions |

---

## Frontend Tooltip Mapping

| Building | Tooltip Text |
|---|---|
| Library | "Under Construction — Built in Prompt 2: Research data ingestion" |
| Forge | "Under Construction — Built in Prompt 4: Strategy generation and backtest engine" |
| Oracle | "Under Construction — Built in Prompt 5: Validation and falsification" |
| Arena | "Under Construction — Built in Prompt 4: Comparative experiments" |
| Vault | "SEALED — The Holdout. Prompt 5 enforces Law 3: sacred, never accessed twice" |
| Treasury | "Under Construction — Built in Prompt 2: Portfolio and benchmark" |
| Harbour | "Under Construction — Built in Prompt 8: Paper trading" |
| Archive | "Under Construction — Built in Prompt 4: Retired strategies" |
| Underworld | "Under Construction — Built in Prompt 4: Rejected strategies" |
| Watchtower | "ACTIVE — Monitoring system health" |
| Temple | "Under Construction — Built in Prompt 6: Meta-learning" |
| Monument | "ACTIVE — €1,000 Buy-and-hold benchmark. The only thing that works today." |
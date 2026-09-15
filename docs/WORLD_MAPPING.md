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

---

## WorldEntity contract (W0)

`WorldState.entities[]` (`prometheus/world/entities.py`'s `WorldEntity`,
populated by `prometheus/world/projection.py`'s `build_entities`) is additive
alongside the pre-existing `districts`/`agents`/`structures` fields -- those
still feed `/buildings/` and the renderer directly; migrating them onto
`entities[]` is a separate, later effort, not bundled into this addition.

| WorldEntityType | Source | Status | Notes |
|---|---|---|---|
| `BUILDING` | One per real `Structure` row (`CONSTRUCTION_MANIFEST`) | Live | `state` = the real `ConstructionPhase` value, verbatim |
| `GOD` | `construction.GOD_BY_BUILDING_KIND` (3 of 12 imported gods) | Live | `parent_entity_id` = its real building; `state` mirrors the building's phase |
| `TEMPLE` | `strategy_families` table | Prompt 4 | Empty until then -- same rule as `districts[]` above |
| `HERO` | `strategies` table | Prompt 4 | Empty; no `StrategySpec` schema exists yet either (see hero-archetype table above) |
| `AGENT` | `jobs` table | Prompt 4 | Empty -- same rule as `agents[]` above. The static idle-decoration figures in `render/builders.ts` are NOT AGENT entities: they're a rendering detail of a BUILDING's real phase + `agent_roles`, not an individuated job |
| `EXPERIMENT` | `experiments` table | Prompt 4 | Empty |
| `ARENA_MATCH` | `experiments` (comparative) | Prompt 4 | Empty |
| `RESEARCH_SOURCE` | `llm_ingestion` | Prompt 9 | Empty |
| `PORTFOLIO` | `portfolio` | Prompt 8 | Empty |
| `ALERT` | `strategy_alerts` | Prompt 10 | Empty |
| `REGIME` | `regime_classification` | Prompt 5 | Empty |
| `ARCHIVE_ENTRY` | `results` (retired) | Prompt 4 | Empty |

`source_entity_id` is a real DB row reference where one exists, or the
canonical code-defined `construction_manifest:<id>` for entities with no DB
row of their own (both `BUILDING` and `GOD` today, since neither has a table
row -- a building's row is itself the manifest entry, and a god has no row
at all). `visual_state` deliberately does NOT exist on the wire -- the
state→visual mapping is frontend-only, one file, not yet built (planned:
`frontend/src/mapping/stateToVisual.ts`, W2).

Live view: `/entities` (dev route, `frontend/app/entities/page.tsx`) lists
every populated and every still-empty type straight from `/world/state`.

## State -> visual mapping (W2)

The one source of visual truth: `frontend/src/mapping/stateToVisual.ts`. If a
visual decision is made anywhere else, that is a bug -- with one documented
exception: `frontend/src/sprites/registry.ts`'s `MANIFEST` remains the actual
renderer implementation for BUILDING construction-phase visuals (it predates
this file and is cross-checked against the Python atlas pipeline); the new
file's `mapBuildingStateToVisual` documents the same semantic mapping without
replacing that already-working system.

Every function is pure (state in, visual descriptor out) and tested against
fixture inputs (`stateToVisual.test.ts`) -- not live data, because for every
row below except the phase/queue_depth ones, no live data of that kind exists.
**Wired** means the function's output is actually connected to the renderer
today; unwired functions are complete and tested, ready for the prompt that
makes their input real.

| Source state | Function | Visual | Source field | Wired? |
|---|---|---|---|---|
| family HEALTHY | `mapFamilyStateToVisual` | lights on, construction activity, agents present | `strategy_families.status` (Prompt 4) | No -- table doesn't exist |
| family QUARANTINED | `mapFamilyStateToVisual` | chains, guards, sealed gate, warning pulse | `strategy_families.status` (Prompt 4) | No |
| family DORMANT | `mapFamilyStateToVisual` | overgrown, dark, sleeping | `strategy_families.status` (Prompt 4) | No |
| family RETIRED | `mapFamilyStateToVisual` | ruins | `strategy_families.status` (Prompt 4) | No |
| strategy PROMISING | `mapStrategyStateToVisual` | RISING_HERO: halo, upward particles, no crown, not in champion temple | `strategies.status` (Prompt 4) | No |
| strategy VALIDATED | `mapStrategyStateToVisual` | CHAMPION_CANDIDATE: formal banner, arena-eligible | `strategies.status` (Prompt 4) | No |
| strategy CHAMPION | `mapStrategyStateToVisual` | crowned, throne | `strategies.status` (Prompt 4) | No |
| strategy RETIRED | `mapStrategyStateToVisual` | statue, Hall of Legends | `strategies.status` (Prompt 4) | No |
| strategy REJECTED | `mapStrategyStateToVisual` | Underworld, tombstone + cause of death | `strategies.status` + `decisions.reason` (Prompt 4) | No |
| building queue_depth high | `mapBuildingStateToVisual` | BUSY: dense agent traffic, full board | `jobs` count per building (Prompt 4); `busy` threshold is a required function argument, deliberately not defaulted -- no real queue data exists to calibrate "high" against yet | No (`queueDepth` is real and always 0; the flag is exercised, never true) |
| oracle validation bottleneck | `mapBuildingStateToVisual` | CONGESTED: visible queue of scribes | `validation_results` backlog (Prompt 5) | No -- field doesn't exist |
| harbour execution divergence | `mapBuildingStateToVisual` | WARNING: warning lamps, disordered motion | `paper_reconciliation` divergence flag (Prompt 8) | No |
| risk breach | `mapBuildingStateToVisual` | guardian BLOCKING | A real risk-limit breach signal; Law 4's env-var limits exist, but no breach-detection event does yet | No |
| regime BEAR | `mapRegimeToClimate` | storm: rain, darker ambient, reduced activity (0.6x) | `regime_classification.current_regime` (Prompt 5) | No -- `climate.regime` is hardcoded `"unknown"` today |
| regime CRISIS | `mapRegimeToClimate` | earthquake, emergency activity | `regime_classification.crisis_flag` (Prompt 5) | No |
| regime (all others incl. UNKNOWN) | `mapRegimeToClimate` | neutral/CALM, no features | n/a -- source prompt specifies no visual for these; not invented here | No |
| component VALUABLE | `mapComponentVerdictToVisual` | tool shrine grows | `component_registry.verdict` (Prompt 6); `Structure.verdict` is a real field, always `null` today | No |
| component HARMFUL | `mapComponentVerdictToVisual` | shrine neglected, abandoned | `component_registry.verdict` (Prompt 6) | No |
| diversification up | `mapDiversificationToAllianceVisual` | alliance bridge between temples | Portfolio return correlation between families (Prompt 8); complementary/redundant thresholds are required function arguments, not defaulted -- no correlation data exists to calibrate against | No |

## Truth layer (W1)

`TruthDrawer.tsx` (right-side Sheet, opens on clicking a building in the
world) renders content driven by `entity_type`, same real-data-only rule as
the contract above: BUILDING shows `description`/`phase`/`prompt_built` (all
real, from `/buildings/`) plus `queue_depth`/verdict from `entities[].metrics`
(honestly "0"/"not yet evaluated" — no jobs table, no component_registry
yet); GOD shows its real parent building. Every other type falls back to an
explicit "no real backend source yet" line rather than empty space.
`BenchmarkStrip.tsx` is the fixed Law-8 header, straight from the real
`Scoreboard`. `SearchPalette.tsx` (Cmd/Ctrl-K) searches the same real
`entities[]` feed and both flies the camera and opens the drawer on
selection — it will surface HERO/EXPERIMENT/etc automatically once those
entity types are ever populated, no changes needed here.

---

## Character sprites (PixelLab import)

38 characters imported from `art/characters/` (`tools/art/import_pixellab.py`)
into `characters_atlas.png` / `manifest.production.json`. Only characters with
a **real, live anchor** are ever spawned in the world; the rest are imported
and atlased (visible on the `/sprites` dev roster route) but never rendered as
a world entity, per the same rule `projection.py` already applies to
`agents`/`districts`: a fabricated figure would be the world lying about
something that isn't real yet.

### Rotation index ↔ compass direction

PixelLab's own order. Mirrored exactly on both sides — Python
(`tools/art/import_pixellab.py`'s `ROTATION_INDEX`) and TypeScript
(`frontend/src/sprites/direction.ts`) reimplement this independently rather
than sharing one file, matching the existing `snap_to_palette`/`palette.ts`
precedent for cross-language constants.

| Index | Compass |
|---|---|
| r0 | south |
| r1 | south-east |
| r2 | east |
| r3 | north-east |
| r4 | north |
| r5 | north-west |
| r6 | west |
| r7 | south-west |

Every static character on screen today faces the Monument (grid 13,13) —
thematically the city faces the benchmark it has to beat, and it means the
facing direction is a pure function of position, never random.

### Agent role → sprite (LIVE)

`CONSTRUCTION_MANIFEST[building].agent_roles[0]` (real, `prometheus/world/construction.py`)
resolves directly against `resolveAgentSprite(role, 'idle', rotation)`
(`frontend/src/sprites/registry.ts`), replacing the procedural stick figure
in `render/builders.ts` on SCAFFOLDING/FOUNDATION buildings. A role with no
matching art (currently only `builder`, harbour's role) keeps the original
procedural figure — never a wrong character.

Roles with real art: `scribe, engineer, statistician, experimenter, guardian,
auditor, scholar, blacksmith, historian, messenger, necromancer, prophet`.

### God → building (LIVE)

Only 3 of the 12 imported gods have a real building to stand at. The god IS
the building's identity, not its activity, so it renders whenever the
building renders — no phase threshold.

| Building kind | God |
|---|---|
| archive | archive_keeper |
| oracle | oracle_validation |
| vault | risk_guardian |

The other 9 (`god_momentum, god_mean_reversion, god_macro, god_value,
god_volatility, god_stat_arb, god_machine_learning, god_event_driven,
god_evolution`) are per strategy **family** — `districts[]` is always empty
(no `strategy_families` table yet, Prompt 4) — so they are imported/atlased
only, never spawned. Revisit once districts are real.

### Hero (StrategySpec → sprite) — NOT YET IMPLEMENTED

11 hero sprites represent individual strategies. `prometheus/strategy/` has
no `StrategySpec` schema yet and zero strategies exist, so there is nothing
real to derive a mapping *from* — implementing `hero_mapping.ts` now would
mean guessing the schema it maps against, the exact "inventing thresholds"
failure CLAUDE.md warns about. The archetype **rule** is documented here so
Prompt 4 can wire it directly once `StrategySpec` is real:

| Hero | Criteria (future) |
|---|---|
| tank | long holding period, low turnover, high drawdown resilience |
| rogue | short holding period, high turnover |
| fast | high signal responsiveness |
| scout | exploratory / early-generation strategies |
| duelist | market-neutral, paired/long-short |
| mage | ML or model-driven families |
| alchemist | feature-engineering heavy |
| hybrid | crossover offspring of two families |
| volatility | volatility / regime-specialist families |
| rising | PROMISING status, evidence still accumulating |
| dormant | DORMANT status (overrides family archetype) |

Harbour NPCs (`harbor_courier, harbor_guard, harbor_trader`) are the same
situation as heroes: imported/atlased only, spawned once Prompt 8's paper
trading produces real activity to represent.
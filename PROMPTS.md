# Project Prometheus — Claude Code Build Prompts

Run these **in order**, one per Claude Code session, in a fresh session each time.
Do not run two at once. After each, run the stated verification command yourself
before moving on.

`CLAUDE.md` must be at the repo root before Prompt 0 — Claude Code reads it
automatically and it is what keeps the laws enforced across sessions.

**The build order is designed so you can watch the world come alive.**

Prompt 0 lays the foundation. Prompt 1 deploys an empty world to Railway — just
bare ground, a construction site, and builder sprites. From Prompt 2 onward,
every prompt builds a real backend system AND activates its corresponding
building in the world. You will literally see the Library rise when data
ingestion lands, the Forge light up when the backtest engine ships, the Oracle
open its doors when validation goes live. Builder sprites migrate to the next
construction site after each prompt.

The falsification-before-generation principle still holds: the Oracle (validation)
opens before the Forge starts accepting external strategies. The world simply
makes that sequence visible.

---

## PROMPT 0 — Skeleton, laws, and database

```
Initialise the Project Prometheus repository. Read CLAUDE.md first; it governs
everything below.

Build:

1. Repo scaffold matching the layout in CLAUDE.md. Python 3.11, pyproject.toml
   with pinned deps, ruff + mypy config (strict on core/ and validation/),
   pytest config, pre-commit hooks running ruff and mypy.

2. core/config.py — pydantic-settings. Two config classes, strictly separated:
   - RiskLimits: read ONLY from environment, frozen, no setters, no reload.
     MAX_POSITION_PCT, MAX_GROSS_EXPOSURE_PCT, MAX_LEVERAGE, MAX_DAILY_LOSS_PCT,
     MAX_DRAWDOWN_PCT, KILL_SWITCH. Import raises at startup if any is missing.
   - ResearchPolicy: loaded from config/research_policy.yaml, hot-reloadable,
     versioned (every load writes a row to policy_versions with a content hash).
   These must live in different classes with different loading paths so it is
   structurally impossible for policy mutation to touch a risk limit.

3. core/db.py — SQLAlchemy 2.x async engine, session factory, Alembic set up
   with an initial migration enabling the timescaledb extension.

4. Append-only enforcement: a Postgres trigger on experiments, results and
   decisions that raises on UPDATE and DELETE. Write it as a migration.

5. core/ids.py — deterministic ID generation. Experiment IDs EXP-YYYY-NNNNNN,
   strategy IDs {FAMILY}-{NNN}, both collision-safe under concurrency.

6. tests/laws/ with the test scaffolding and these tests implemented now, even
   though the code they guard doesn't exist yet (mark them as expected-to-fail
   ONLY with an explicit reason string naming the prompt that will satisfy them):
   - test_risk_limits_immutable: attempting to set any RiskLimits attribute
     raises; monkeypatching the module doesn't change the running instance.
   - test_history_append_only: UPDATE and DELETE on the three tables raise.
   - test_policy_cannot_reach_risk: static check that no module importing
     ResearchPolicy also has write access to RiskLimits.

7. docs/DEPENDENCIES.md with a row per dependency: name, version, purpose,
   what it replaces, why not stdlib.

8. GitHub Actions CI: ruff, mypy, pytest, and a dedicated job that runs
   tests/laws/ separately and fails loudly with the message "LAW VIOLATION".

Do NOT create Redis, Docker Compose, or any deployment config yet.

Verify with: pytest tests/laws/ -v && ruff check . && mypy core/
```

---

## PROMPT 1 — The world, deployed empty

**This is the first thing that goes live.** An empty world, deployed to Railway,
that you can open in a browser and watch. Everything is under construction.
Builder sprites wander between scaffolded buildings. The Monument (buy-and-hold
benchmark) stands alone on bare ground — the only "finished" structure, because
the benchmark doesn't need the system to exist.

```
Build the world view, the API shell, deploy it, and make it live. Read CLAUDE.md.

PART A — The world state contract

1. world/entities.py — the WorldState schema. This is the contract between every
   backend system and the frontend. Define it completely NOW even though most
   source tables don't exist yet.

   WorldState {
     tick, generated_at, source_data_version,
     climate:    { regime, volatility_percentile, trend_strength,
                   crisis_flag, market_open },
     districts:  [ per strategy FAMILY: id, name, archetype,
                   population_by_status {champion, promising, experimental,
                   regime_specialist, dormant, quarantined, retired},
                   health 0-1, activity 0-1, portfolio_weight,
                   building_state enum, alert_flags[] ],
     agents:     [ per ACTIVE JOB: id, role (builder/scribe/engineer/
                   experimenter/statistician/guardian/auditor/necromancer),
                   from_location, to_location, progress 0-1, experiment_id ],
     structures: [ per pipeline component + per registry component:
                   id, kind, construction_phase enum, load 0-1, queue_depth,
                   status, verdict ],
     events:     [ recent state transitions: type, subject_id, severity,
                   timestamp, drill_down_url ],
     treasury:   { total_equity, allocation_by_family, drawdown,
                   paper_pnl_today,
                   benchmark: { equity, return_pct, sharpe, max_drawdown },
                   vs_benchmark: { excess_return, excess_sharpe, winning },
                   infra_cost_mtd, llm_cost_mtd },
     laws:       [ each law + current compliance status + last violation ],
     scoreboard: { starting_capital: 1000, currency: "EUR",
                   system_value, benchmark_value, excess,
                   infra_cost_to_date, net_after_costs,
                   verdict: "SYSTEM_WINNING"|"HOLDING_WINNING"|"INCONCLUSIVE"|"NOT_STARTED" }
   }

   CRITICAL — the construction_phase enum for structures:
     PLANNED        — grey silhouette, no activity
     SCAFFOLDING    — wireframe with builder sprites actively working
     FOUNDATION     — base visible, walls going up
     ACTIVE         — fully built, operational, lit, agents entering/leaving
     DAMAGED        — cracks, sparks, warning lights (for failures)
     SEALED         — chains, locks (for the Vault / holdout)
     OVERGROWN      — vines, dust (for dormant)

   Right now, ALL structures start as SCAFFOLDING except:
   - The Monument (benchmark) — starts ACTIVE immediately, showing €1,000
   - The Vault (holdout) — starts SEALED from day one, because it's sacred
   - The Watchtower (alerts) — starts ACTIVE, already monitoring

2. world/projection.py — build_world_state(session) -> WorldState. Pure function.
   When a source table doesn't exist yet, that structure stays in SCAFFOLDING.
   The projection NEVER errors on missing tables — it gracefully degrades.
   The building "activates" the moment its backing tables have data.

   The rule: a building transitions from SCAFFOLDING to ACTIVE when its source
   query returns at least one real row. This means the world will AUTOMATICALLY
   come alive as you run subsequent prompts — no frontend changes needed.

3. world/construction.py — a construction_manifest dict mapping each structure
   to: the prompt number that builds it, the database tables that activate it,
   and the roles of agents that will work there once active. Example:

     "library": {
       "prompt": 2,          # Prompt 2 builds data ingestion
       "activates_on": ["ohlcv_bars"],  # table name
       "agent_roles": ["scribe"],
       "description": "Research data ingestion"
     },
     "forge": {
       "prompt": 4,
       "activates_on": ["strategies"],
       "agent_roles": ["engineer"]
     },
     "oracle": {
       "prompt": 5,
       "activates_on": ["validation_results"],
       "agent_roles": ["statistician"]
     },
     ...etc for every building

   This manifest IS the documentation of what each prompt will build. The
   frontend reads it to show "Coming in Prompt N" tooltips on scaffolded
   buildings.

4. docs/WORLD_MAPPING.md — every field in WorldState traced to its source
   table/column/query. For fields whose source doesn't exist yet, write
   "Source: [table_name] — built in Prompt N". This file is the ground truth
   for what's real and what's scaffolded.

PART B — The frontend

Next.js App Router + TypeScript + PixiJS v8.

Use PixiJS, not three.js: this is 2.5D sprite work, and Pixi's batched sprite
renderer handles hundreds of animated agents at 60fps in a way a 3D scene graph
won't. Isometric at the 2:1 pixel ratio (~26.565 degrees), NOT true 30-degree
isometric — 2:1 is the convention that keeps pixel edges clean.

WORLD VIEW:
- Tile-based isometric city. One DISTRICT per strategy family, but right now
  they're all empty lots with surveyor stakes.
- EVERY building from the construction manifest exists as a physical location
  in the world, but most are in SCAFFOLDING state: wireframe outlines with
  small builder sprites hammering, carrying planks, measuring.
  Buildings in the world:
    Library (data ingestion) — SCAFFOLDING
    Forge (strategy generation / backtest) — SCAFFOLDING
    Oracle (validation) — SCAFFOLDING
    Arena (comparative experiments) — SCAFFOLDING
    Vault (holdout) — SEALED (locked from the start, visually imposing)
    Treasury (portfolio) — SCAFFOLDING
    Harbour (paper trading) — SCAFFOLDING
    Archive (retired strategies) — SCAFFOLDING
    Underworld (rejected strategies) — SCAFFOLDING
    Watchtower (alerts/monitoring) — ACTIVE (blinking light, watching)
    Temple of Knowledge (meta-learning) — SCAFFOLDING
    Monument (buy-and-hold benchmark) — ACTIVE

- THE MONUMENT — a stone pillar at the city centre with "€1,000" carved into
  its base and the current benchmark value at its top. It GROWS taller as
  buy-and-hold appreciates. It is the only fully rendered structure on day one.
  It stands alone on bare ground, surrounded by construction — a visual
  statement: "this is what you're trying to beat, and nothing else works yet."

- Builder sprites: 8-12 small characters with hard hats, visibly working on
  scaffolded buildings. They have idle animations (hammering, measuring,
  carrying). As each prompt activates a building, the builders migrate to the
  next SCAFFOLDING structure. When all buildings are ACTIVE, the builders
  become a small permanent maintenance crew.

- Climate: default clear sky. Will respond to regime data once Prompt 5 lands.

- Everything is clickable. Clicking a SCAFFOLDING building shows:
  "Under Construction — Built in Prompt N: [description]"
  Clicking the Monument shows the benchmark equity curve (initially flat €1,000).
  Clicking the Watchtower shows system health.

- A subtle "Build Progress" indicator in the corner: "3/12 systems online" etc.

TRUTH VIEW:
- Conventional React + Recharts panel that slides in from the right when you
  click any world object.
- Initially mostly empty panels with "Awaiting: [system name]" placeholders.
- The benchmark panel works from day one: €1,000 starting value, current value
  (fetched from a simple crypto price API), return %. This is live immediately.
- A scoreboard header always visible:
  "Your system: €— | Just holding: €X,XXX | Verdict: NOT_STARTED"
  The system value shows "—" until strategies exist. The benchmark value is
  live from minute one.

Art: programmatic placeholder sprites — coloured isometric prisms with distinct
silhouettes per role and building type. Builder sprites are yellow hard-hat
figures. Buildings are geometric shapes with role-appropriate outlines (Oracle
has columns, Forge has a chimney, Harbour has a dock outline, etc). The state
machine must be provably correct before anyone commissions pixel art. Ship a
sprite-swap layer so real art drops in without touching logic.

Performance budget: 60fps with 300 agents, under 40MB of textures, degrades
to static view on slow connections.

PART C — API shell

1. api/routes/world.py — GET /world/state (returns full WorldState JSON) and a
   WebSocket that pushes deltas on change. GET /world/drilldown/{entity_type}/{id}
   returning the real metrics behind any visual object.

2. api/routes/health.py — /health and /ready endpoints.

3. api/routes/scoreboard.py — the permanent scoreboard endpoint:
   GET /scoreboard returns the vs-benchmark comparison and verdict.

4. main.py — FastAPI app serving the API and the Next.js static export.

PART D — Deploy to Railway

Railway bills per second at ~$20/vCPU-month and ~$10/GB-RAM-month. Build cheap.

Services:
1. api — FastAPI + static frontend in ONE container. 0.5 vCPU / 512MB.
   Always on. This is the only always-on compute besides Postgres.
2. postgres — Railway managed Postgres with timescaledb extension. Always on.
3. worker — NOT YET. Will be added in a later prompt as a CRON service.

Build:
- Dockerfile, multi-stage, non-root user, no secrets in layers.
- Alembic migrations run on deploy via a release command.
- GitHub Actions CI deploys on push to main, blocked by tests/laws/.

Repo: https://github.com/ALYTIC5/Project_Prometheus.git

After this prompt, you should be able to open a URL and see: an isometric
construction site with builder sprites working, a glowing Monument showing the
live BTC benchmark value, scaffolded building outlines for every future system,
and a "Build Progress: 1/12 systems online" indicator. The Watchtower blinks.
Everything else is under construction. It's beautiful and it's honest.

Verify with: open the deployed URL, confirm the world renders at 60fps,
confirm the Monument shows a live benchmark price, confirm clicking any
scaffolded building shows its "Coming in Prompt N" tooltip, confirm the
scoreboard shows "NOT_STARTED" for the system and a real number for benchmark.
```

---

## PROMPT 2 — Point-in-time data layer (Library rises)

**After this prompt:** the Library building transitions from SCAFFOLDING to ACTIVE.
Scribe agents appear inside it. Builder sprites migrate to the next site. The
Monument starts showing a REAL historical benchmark curve instead of just today's
price. You can watch data flow into the Library for the first time.

**Decision I'm making for you:** start with **crypto spot majors** (BTC, ETH, SOL
+ ~15 liquid pairs) on Binance/Coinbase via ccxt, daily and 4h bars.

Reasoning: the data is free and complete, there is no survivorship or corporate-
action problem for majors, no point-in-time restatement problem, the market is
24/7 so paper trading gathers evidence 3× faster than equities, and Qubx already
speaks it. Free equity data (yfinance) is survivorship-biased and split-adjusted
in place, which silently violates Laws 1 and 2 — you'd be building a liar. Keep
the interface generic so equities can be added later behind the same abstraction.

```
Build the data layer. Read CLAUDE.md.

When this prompt completes, the world view should automatically detect that the
ohlcv_bars table has data and transition the Library from SCAFFOLDING to ACTIVE.
You do NOT need to touch the frontend — the projection layer handles it.

1. data/schema.py — every price/feature row carries FIVE timestamps:
   event_time, available_at, ingested_at, source, revision. available_at is the
   only one strategies may filter on. Make this structurally enforced: the
   dataframe accessor used by feature code physically cannot see event_time.

2. data/ingestion.py — ccxt adapter for Binance spot, daily + 4h OHLCV, for the
   universe in config/universe.yaml. Idempotent (re-running never duplicates),
   resumable, rate-limit aware, writes raw responses to a raw_ingest table
   before any normalisation.

3. data/universe.py — as_of(date) -> list[symbol]. Membership is reconstructed
   from listing/delisting dates stored in a universe_membership table, NOT from
   today's exchange listing. Include at least 5 known dead/delisted pairs in the
   seed data so survivorship tests have something to bite on.

4. data/versioning.py — every ingest run produces a data_version row:
   content hash of the resulting dataset, row count, date range, source
   versions. Backtests reference a data_version and can be replayed against it.

5. data/quality.py — checks run on every ingest: gaps, duplicate timestamps,
   zero/negative prices, impossible OHLC relationships (high < low etc),
   volume spikes >20 sigma, stale bars. Failures quarantine the batch and alert;
   they do not silently pass through.

6. backtest/benchmark.py — THE BUY AND HOLD BENCHMARK. Law 8 requires this.
   Starting capital €1,000. For a single-asset strategy: buy €1,000 worth of
   that asset at the first bar, hold forever. For a multi-asset strategy:
   equal-weight across the universe at inception, no rebalancing. Apply the
   SAME cost model for the initial purchase (entry fee, spread, slippage).
   For now, use a simple fixed-fee model since the full cost engine doesn't
   exist yet — but the interface must accept a CostModel so it can be swapped
   later. The benchmark result (equity curve, Sharpe, max drawdown, final value)
   is stored and the Monument in the world view starts showing real history.

7. tests/laws/test_no_lookahead.py — REAL implementation now:
   - Construct a dataset where a future value is deliberately planted in a
     column. Assert the point-in-time accessor cannot return it.
   - Truncation proof: for a random sample of 200 (symbol, date) pairs, compute
     features on the full dataset and on the dataset truncated at that date.
     Assert the values are identical. Any difference means the future is
     leaking backwards. This is the single most valuable test in the repo.

8. tests/laws/test_survivorship.py — a universe query for 2021 must return
   symbols that no longer trade today.

Verify with:
- pytest tests/laws/ -v (all must PASS, no xfail)
- python -m prometheus.data.ingestion --backfill --days 800
- Open the world view: the Library should now be ACTIVE with scribe agents.
  The Monument should show the real BTC buy-and-hold curve from 800 days ago.
  Builders should have moved to other scaffolded buildings.
```

---

## PROMPT 3 — Strategy spec and backtest engine (Forge ignites)

**After this prompt:** the Forge building transitions from SCAFFOLDING to ACTIVE,
glowing with furnace light. Engineer agents appear. The Arena becomes FOUNDATION
(partially built — it needs validation before it can host real contests).

```
Build the strategy representation and backtest engine. Read CLAUDE.md.

1. strategy/spec.py — StrategySpec as a frozen pydantic model: strategy_id,
   parent_id, family, description, universe, timeframe, features, signals,
   entry_rules, exit_rules, position_sizing, risk_rules, parameters,
   expected_horizon, source, lineage. Serialises to canonical JSON with a
   stable content hash — two semantically identical specs hash identically.

2. strategy/dsl.py — a restricted expression language for signals. Whitelisted
   operators and indicator functions only, no eval, no exec, no imports, AST-
   validated. This is what LLM generation will later emit, so it must be safe
   to execute untrusted strings today.

3. backtest/costs.py — a configurable cost model, per-venue and per-asset:
   maker/taker fees, half-spread, slippage as a function of order size relative
   to trailing ADV, and a market-impact term (square-root law). NO single global
   BPS number anywhere. Costs are loaded from config/costs.yaml with a version
   hash recorded in every result.

4. backtest/execution_sim.py — decision-to-fill modelling: signal computed on
   bar close, order placed next bar open, configurable latency, partial fills
   when order size exceeds a share of bar volume, rejection on illiquidity.

5. backtest/engine.py — event-driven, vectorised where safe. Takes
   (StrategySpec, data_version, cost_config, seed) and returns a BacktestResult
   with an equity curve, per-trade log, turnover, exposure and the full config
   hash set. Deterministic: same inputs, bit-identical output.

6. Update backtest/benchmark.py to use the REAL cost model from costs.py now
   that it exists. Every BacktestResult carries a vs_benchmark field:
   { excess_return, excess_sharpe, information_ratio, tracking_error,
   periods_underperforming_pct, max_relative_drawdown }. A strategy with
   negative excess_return after costs is flagged WORSE_THAN_HOLDING.

7. tests/laws/test_cost_model.py and the NULL SUITE — tests/test_null_strategies.py:
   - random entry/exit at the strategy's turnover
   - always-flat
   - a coin-flip signal
   - a signal that is pure lagged noise
   Assert: none produces a positive Sharpe after costs at p<0.05 across 1000
   seeds. Also assert: buy-and-hold produces a POSITIVE return on BTC (sanity).

8. tests/laws/test_benchmark_always_present.py — every BacktestResult has a
   non-null vs_benchmark field.

The Forge should transition to ACTIVE in the world view. Engineer agents appear.

Verify with: pytest tests/ -v, the null-suite Sharpe distribution (centred
slightly negative), and the Forge glowing in the world view.
```

---

## PROMPT 4 — Experiments, lineage, queue (Arena and Archive open)

**After this prompt:** the Arena opens for comparative experiments. The Archive
lights up to store results. The world starts to feel populated — experiment
agents carry results between buildings.

```
Build experiment tracking and lineage. Read CLAUDE.md.

1. experiments/models.py — Experiment table: experiment_id, strategy_id,
   parent_experiment_id, hypothesis, change_set (structured diff), data_version,
   code_sha, config_hash, seed, metrics, regime_results, decision, reason_codes,
   timestamp, compute_cost. Append-only enforced by Prompt 0 triggers.

2. experiments/lineage.py — the family tree. Parent/child edges, efficient
   ancestor and descendant queries, and a diff function that answers "what
   exactly changed between generation N and N+1, and did OOS performance move
   in the direction the hypothesis predicted?"

3. experiments/queue.py — Postgres-backed job queue using
   SELECT ... FOR UPDATE SKIP LOCKED. No Redis. Priority, expected information
   value, estimated cost, retry with backoff, idempotency keys, dead-letter
   table. Jobs must be safe to interrupt.

4. experiments/failure.py — the failure taxonomy as an enum with auto-classifier.
   Aggregate queries: "top failure modes this month", "which mutation types
   most often produce TRANSACTION_COST_FAILURE".

5. experiments/violations.py — RESEARCH_VIOLATION detection per Law 7: threshold
   changing while a strategy is pending, repeated holdout access attempts,
   cost config loosening after failure, universe/benchmark changing after
   results are seen. Logged and surfaced in the API.

6. experiments/runner.py — takes a queued job, runs backtest -> validation ->
   decision -> persist. Records compute cost.

The Arena and Archive should transition to ACTIVE. Experimenter agents appear,
carrying scrolls between buildings.

Verify with: seed 200 synthetic experiments across a 4-generation tree, query
lineage for "changes that improved OOS Sharpe", confirm correctness.
```

---

## PROMPT 5 — Validation and falsification (Oracle opens its doors)

**After this prompt:** the Oracle — the most important building in the world —
transitions from SCAFFOLDING to ACTIVE. It should look visually imposing:
columns, glowing runes, an aura of authority. Statistician agents enter with
hypotheses and leave with verdicts. The Vault remains SEALED beside it.

```
Build the validation layer. Read CLAUDE.md.

Use cpz-quant (github.com/CPZ-Lab/cpz-quant, pip install cpz-quant, Apache-2.0)
for PBO, Deflated Sharpe, Probabilistic Sharpe and the purged/combinatorial CV
splitters. Read its actual API first. Pin the version. Record in
docs/DEPENDENCIES.md.

1. validation/splits.py — walk-forward with PURGING and EMBARGO. Window sizes
   DERIVED from the strategy's expected_horizon and available history.

2. validation/holdout.py — Law 3 enforcement. The final slice stored in a
   separate schema with restricted DB role. Access audited, second access for
   the same strategy fingerprint = hard error.

3. validation/metrics.py — Sharpe, Sortino, max drawdown, Calmar, turnover,
   hit rate, IC, ICIR, tail ratio. IC/ICIR carry NO hardcoded pass/fail.

4. validation/decay.py — IC at horizons [1,2,3,5,10,20,30,50,100] days. The
   test is "does the strategy have power at the horizon it CLAIMS".

5. validation/regime.py — classify into bull/bear/high-vol/low-vol/trending/
   ranging/crisis. Output is CLASSIFICATION, never automatic rejection.

6. validation/multiple_testing.py — global trials counter. Deflated Sharpe
   uses the ACTUAL cumulative count. Evidence requirements tighten as count grows.

7. validation/scoring.py — composite score with vs_benchmark excess metrics as
   REQUIRED inputs. Underperforming buy-and-hold on both excess_return AND
   excess_sharpe = hard score cap preventing PROMOTE. This is Law 8.

8. validation/decision.py — PROMOTE / PROMISING / CONTINUE_RESEARCH /
   REGIME_SPECIALIST / DORMANT / QUARANTINE / REJECT / RETIRE with
   reason_codes. WORSE_THAN_HOLDING is the FIRST check before PBO/DSR.

9. tests/laws/test_holdout_sacred.py — second access raises. DB credential
   isolation tested with real connection.

The Oracle should transition to ACTIVE. When the regime classifier has data,
the world's CLIMATE layer should come alive — weather changes based on the
current market regime. Rain in bear markets, lightning in high vol, sunshine
in calm bull runs. The world now breathes with the market.

Verify with: run a deliberately overfit strategy (50 free params fit to noise)
through the pipeline — PBO must exceed 0.5, decision must be REJECT with
OVERFITTING. The Oracle should visually reject it (red flash, agent turned away).
```

---

## PROMPT 6 — Ablation harness (Temple of Knowledge awakens)

**After this prompt:** the Temple of Knowledge building activates. This is where
the system stores what it learns about ITSELF. It should look ancient and wise —
a place of accumulated knowledge, not flashy power.

```
Build the component ablation harness. Read CLAUDE.md.

The author of AgentQuant published that their own walk-forward validation showed
the context-aware LLM agent LOSING to a static baseline. Treat "the clever
component adds nothing" as the default hypothesis for every component.

1. experiments/ablation.py — A/B harness. N matched experiments with component
   enabled vs disabled, SAME data_version, seeds, costs, budget. Report OOS
   Sharpe difference with confidence interval plus cost delta.

2. ComponentRegistry table: component, version, families affected, experiments,
   median/mean/worst/best OOS improvement, risk impact, compute cost, failure
   rate, verdict (UNPROVEN / VALUABLE / NEUTRAL / HARMFUL).

3. Hard gate: HARMFUL or >200 experiments + UNPROVEN = auto-disabled.

4. The FIRST component: deterministic parameter grid search over classic
   templates (momentum crossover, Bollinger mean reversion, volatility
   breakout, carry). Everything must beat THIS.

5. Interaction testing: pairwise and triple combinations.

The Temple of Knowledge should activate. Its walls display discovered truths —
component verdicts, failure pattern aggregates, meta-learning insights.
Initially it shows only the baseline registration.

Verify with: run a placebo component (changes only the seed). Must return
NEUTRAL with CI straddling zero. If a placebo shows improvement, the harness
is broken.
```

---

## PROMPT 7 — Deterministic generation and evolution (districts populate)

**After this prompt:** strategy districts start populating with hero sprites.
The first strategies are born in the Forge, tested in the Arena, judged by the
Oracle. Some survive, some enter the Underworld. The world starts feeling ALIVE.

```
Build strategy generation. Read CLAUDE.md. No LLMs in this prompt.

1. research/templates.py — baseline strategy family templates as StrategySpecs.

2. research/mutations.py — typed mutation operators: change lookback, add/remove
   filter, change sizing, change rebalance, add vol targeting, swap indicator.
   Each records a structured change_set and hypothesis.

3. research/crossover.py — combine components of two parents, preserving lineage.

4. research/population.py — population management: CHAMPION / PROMISING /
   EXPERIMENTAL / REGIME_SPECIALIST / DORMANT / QUARANTINED / REJECTED / RETIRED.
   Five selection modes (exploitation, exploration, diversification, revival,
   cross-breeding). Nothing is ever hard-deleted.

5. research/complexity.py — parameter counting and complexity penalty.

6. research/prioritisation.py — expected-information-value scoring for the queue.

7. The worker CRON service — add the Railway CRON config now. It wakes on
   schedule, drains the Postgres queue, runs experiments, and exits. Schedules
   configurable: data ingest hourly, research drain every 30 min, paper
   reconciliation every 15 min when live.

Evaluate stratevo (github.com/NeuZhou/stratevo) — note that evolution/paper
trading appear to be in a paid "Pro" tier. If the open repo doesn't contain
the full GA, use our own. Register either as a component and ablate.

After this prompt, the world should show: strategies being born (new hero sprites
appearing in districts), experiments running (agents moving between Forge, Arena,
Oracle), some strategies entering the Underworld (rejected), the lineage tree
visible in Truth View, and the Temple of Knowledge updating with component
verdicts.

Verify with: 500 generations against baseline, then ablation: does
mutation+selection beat grid search on OOS? Report honestly including "no".
```

---

## PROMPT 8 — Paper trading (Harbour launches)

**After this prompt:** the Harbour building activates. Ships appear at the dock.
When a strategy passes validation, its hero sprite boards a ship and sails to
the live-market waters. Paper P&L flows back. The Monument now has something
to compare against — the golden light mechanic activates.

```
Build the paper-trading layer. Read CLAUDE.md. Law 5: no real money, ever.

1. paper/broker.py — Binance testnet adapter. Asserts testnet URL on init.
   PAPER_ prefixed env vars only; raises if live-sounding vars exist.

2. paper/execution.py — order lifecycle, position tracking, reconnection,
   idempotent submission.

3. paper/reconciliation.py — compare every paper trade against backtest
   predictions: expected vs actual entry/exit/fill/slippage/latency/cost/P&L.
   Also compare paper P&L against buy-and-hold over the same period.
   PAPER_WORSE_THAN_HOLDING is a prominently surfaced finding.

4. paper/divergence.py — when slippage or fill rate materially diverges,
   PAPER_DIVERGENCE finding, quarantine the strategy, propose cost-model
   recalibration as a new experiment.

5. paper/duration.py — observation period derived from horizon and independent
   trade count needed for significance.

6. Evaluate Qubx (github.com/xLydianSoftware/Qubx). Register as component,
   ablate, be willing to conclude our adapter is simpler.

The Harbour should activate. When a strategy's hero boards a ship, the Monument
comparison activates: golden light radiates from Treasury toward Monument when
the system portfolio beats holding; the light reverses when it doesn't.

The scoreboard header should now show real numbers:
"Your system: €X,XXX | Just holding: €X,XXX | Verdict: [result]"

Verify with: 48h paper run against testnet, reconciliation populates,
divergence fires when cost model deliberately mis-specified.
```

---

## PROMPT 9 — LLM research layer (Scholars arrive, gated by ablation)

**After this prompt:** new agent types appear — scholars carrying scrolls from
the Library to the Forge, prophets generating hypotheses. But ONLY if the
ablation harness shows they add value. If LLMs don't beat grid search, the
scholars remain idle and a prominent notice appears in the Temple of Knowledge:
"LLM Generation: NEUTRAL — does not improve OOS results net of cost."

```
Add the LLM research layer. Read CLAUDE.md. This ships LAST and gated.

1. research/llm/hypothesis.py — LLM emits: structured hypothesis, StrategySpec
   in the restricted DSL, stated expected effect. Never sees holdout, never
   evaluates its own output.

2. research/llm/ingestion.py — arXiv/paper ingestion. Look at VibeQuant for
   extraction ideas; keep our validation.

3. research/llm/budget.py — hard monthly cap from env. At 80% switch to
   cheaper model; at 100% LLM generation halts, deterministic continues.

4. Register LLM generation as component, ablate against baseline. Report OOS
   improvement per euro of API spend. If negative, leave disabled — and display
   that result prominently in the Temple of Knowledge.

Optionally evaluate AgentQuant and QuantEvolve. Read current code first.

Verify with: ablation report, and test proving LLM path cannot reach holdout.
```

---

## PROMPT 10 — Monitoring, alerts, and polish (Watchtower fully online)

**After this prompt:** the Watchtower gets its full alert system. The world
responds to failures visually: storms on drawdown, sparks on data outage,
guards at quarantined strategies. The full event system makes the world feel
like it's constantly responding to real conditions.

```
Build monitoring and alerting. Read CLAUDE.md.

1. monitoring/health.py — strategy health tracking: live IC, realized vs
   expected returns, drawdown, turnover, execution quality, signal strength,
   feature drift detection.

2. monitoring/retirement.py — evidence-based retirement triggers: persistent
   loss of predictive power, large deviation from expected, execution
   deterioration, excessive drawdown, feature drift.

3. monitoring/revival.py — periodic dormant strategy reconsideration. Original
   strategy + new regime filter + different universe, preserving lineage.
   In the world: forgotten temples glow, necromancer agents appear.

4. monitoring/alerts.py — Discord webhook alerting: law violations, research
   violations, paper divergence, data quality, drawdown breach, worker crash,
   budget cap. Alerts also create world events visible as visual phenomena.

5. /costs endpoint — Railway usage + LLM spend month-to-date.
6. /scoreboard endpoint — the ultimate question, net of infra costs.

7. Full visual event mapping in the world:
   - Strategy drawdown → storm over its district
   - Data outage → lightning strikes the Library
   - Broker outage → Harbour goes dark
   - Worker crash → building loses workers
   - Validation failure → Oracle flashes red
   - Risk breach → Guardian blocks hero
   - Successful discovery → fireworks/celestial event
   - Strategy degradation → hero visibly weakens

8. Nightly pg_dump backup. Test the RESTORE path in CI.
9. Graceful shutdown that requeues in-flight jobs.

Verify with: deploy, kill worker mid-job, confirm no lineage lost. Trigger
each alert type and confirm both Discord notification and world visual event.
```

---

## PROMPT 11 — Meta-validation and self-improvement (the world learns)

**After this prompt:** the Temple of Knowledge becomes the most fascinating
building in the world. Its walls fill with discovered patterns. The system
demonstrates that it can improve its own research process — or honestly report
that it cannot.

```
Build meta-learning. Read CLAUDE.md.

1. meta/knowledge.py — aggregate learned patterns:
   "Which strategy families tend to work?"
   "Which mutations improve strategies?"
   "Which features cause instability?"
   "Which models add value?"
   "Which combinations are redundant?"
   Store as structured KnowledgeFact records with supporting experiment IDs.

2. meta/validation_experiments.py — the system tests its own validation:
   compare validation rule sets across historical experiments, determine which
   rules find genuinely robust strategies vs produce false positives. Only
   promote a new validation rule if it improves the research system as a whole.

3. meta/resource_optimisation.py — prioritise experiments by expected
   information value relative to compute cost. Spend more on promising areas,
   less on repeatedly failed ones.

4. Surface all meta-learning in the Temple of Knowledge and in Truth View.
   The Temple's walls should visually display discovered truths as inscriptions.

Verify with: run meta-analysis on accumulated experiments, confirm at least
3 non-trivial patterns are detected and surfaced.
```

---

## What I deliberately left out, and why

- **Redis.** Postgres `SKIP LOCKED` is sufficient and saves a container.
- **RL, LSTMs, transformers.** Experiments, not components. Add after ablation.
- **Multi-asset from day one.** One market, done honestly, beats four done badly.
- **Hard threshold numbers.** Window count and horizon are derived per-strategy.
- **"100% uptime."** Design for restart safety instead.

## On the €20-40/month goal

Two things need to be true and neither is under your control. Infrastructure
stays near €10/month (the two-service design makes this plausible). A strategy
survives falsification AND paper AND real money — at 10% net annual return,
€30/month needs ~€3,600 of capital.

Honest framing: build this to find out whether an edge exists, with falsification
strong enough you'd believe a negative answer. The first six months aim for a
trustworthy result; treat any profit as a surprise, not a plan.

## The construction metaphor

The most important thing about this build order: at no point does the world lie.

An empty construction site IS the honest state of the system at Prompt 1.
Scaffolding IS the honest state of a building whose backend doesn't exist.
A lone Monument on bare ground IS the honest representation of "you have
nothing yet but a benchmark to beat."

And when buildings start lighting up, strategies start being born, the Oracle
starts rendering verdicts, and the Monument starts being compared against —
that's not decoration. That's the system becoming real, and you're watching
it happen.

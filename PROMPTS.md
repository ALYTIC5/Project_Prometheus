# Project Prometheus — Claude Code Build Prompts

Run these **in order**, one per Claude Code session, in a fresh session each time.
Do not run two at once. After each, run the stated verification command yourself
before moving on.

`CLAUDE.md` must be at the repo root before Prompt 0 — Claude Code reads it
automatically and it is what keeps the laws enforced across sessions.

**Order matters more than anything else here.** Prompts 1–5 build the machinery
that can prove a strategy is fake. Prompts 6+ build the machinery that invents
strategies. Doing that in the other order is how you get a beautiful dashboard
displaying nonsense.

---

## PROMPT 0 — Skeleton and laws

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

## PROMPT 1 — Point-in-time data layer

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

6. tests/laws/test_no_lookahead.py — REAL implementation now:
   - Construct a dataset where a future value is deliberately planted in a
     column. Assert the point-in-time accessor cannot return it.
   - Truncation proof: for a random sample of 200 (symbol, date) pairs, compute
     features on the full dataset and on the dataset truncated at that date.
     Assert the values are identical. Any difference means the future is
     leaking backwards. This is the single most valuable test in the repo.

7. tests/laws/test_survivorship.py — a universe query for 2021 must return
   symbols that no longer trade today.

Verify with: pytest tests/laws/ -v (all must now PASS, no xfail)
and: python -m prometheus.data.ingestion --backfill --days 800
```

---

## PROMPT 2 — Strategy spec and the backtest engine

```
Build the strategy representation and backtest engine. Read CLAUDE.md.

1. strategy/spec.py — StrategySpec as a frozen pydantic model, exactly the
   schema in section 46 of docs/blueprint_a.md: strategy_id, parent_id, family,
   description, universe, timeframe, features, signals, entry_rules, exit_rules,
   position_sizing, risk_rules, parameters, expected_horizon, source, lineage.
   It must serialise to canonical JSON with a stable content hash — two
   semantically identical specs hash identically. This hash is the strategy's
   fingerprint and prevents rediscovering the same strategy forever.

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

6. tests/laws/test_cost_model.py and a NULL SUITE — tests/test_null_strategies.py.
   This is critical. Run these through the full engine:
   - random entry/exit at the strategy's turnover
   - always-long buy and hold
   - always-flat
   - a coin-flip signal
   - a signal that is pure lagged noise
   Assert: none produces a positive Sharpe after costs at p<0.05 across 1000
   seeds. If your engine can make a coin flip look profitable, the engine is
   broken and everything downstream is fiction. Print the distribution.

Verify with: pytest tests/ -v and inspect the null-suite Sharpe distribution —
it must be centred on something slightly NEGATIVE (costs), not zero.
```

---

## PROMPT 3 — Validation and falsification

```
Build the validation layer. Read CLAUDE.md.

Use cpz-quant (github.com/CPZ-Lab/cpz-quant, pip install cpz-quant, Apache-2.0)
for PBO, Deflated Sharpe, Probabilistic Sharpe and the purged/combinatorial CV
splitters. Read its actual API first and wrap it behind our own thin interface in
validation/ — do not let its types leak into the rest of the codebase. Pin the
version. Record in docs/DEPENDENCIES.md what it replaced and why.

1. validation/splits.py — walk-forward with PURGING and EMBARGO. Window sizes
   are DERIVED, not hardcoded: from the strategy's expected_horizon, the
   available history, and a minimum-samples-per-fold policy in the research
   policy YAML. A strategy claiming a 5-day horizon and one claiming a 90-day
   horizon must get different windows automatically.

2. validation/holdout.py — Law 3 enforcement. The final slice (last 15% of
   history, plus a random contiguous 10% from the middle so it isn't purely
   recent) is stored in a separate schema with its own DB role that the research
   worker's credentials CANNOT read. Access goes through one audited function
   requiring an experiment_id, which writes to holdout_access_log and returns
   a hard error on second access for the same strategy fingerprint.

3. validation/metrics.py — Sharpe, Sortino, max drawdown, Calmar, turnover,
   hit rate, IC, ICIR, tail ratio. IC and ICIR are computed and REPORTED but
   carry NO hardcoded pass/fail threshold — they are evidence, evaluated
   relative to horizon, universe and sample size.

4. validation/decay.py — IC measured at horizons [1,2,3,5,10,20,30,50,100] days.
   Output the decay curve and the inferred optimal holding period. The test is
   "does the strategy have power at the horizon it CLAIMS", not "does it survive
   50 days". A 3-day strategy that dies at day 8 passes if it claimed 3 days.

5. validation/regime.py — classify history into bull/bear/high-vol/low-vol/
   trending/ranging/crisis using statistical percentile methods (not absolute
   thresholds). Report per-regime performance. Output is a CLASSIFICATION, never
   an automatic rejection — regime specialists are a valid outcome.

6. validation/multiple_testing.py — a global trials counter. Every backtest ever
   run increments it. Deflated Sharpe uses the ACTUAL cumulative trial count,
   not a guess. Evidence requirements tighten automatically as the count grows.

7. validation/scoring.py — composite score from the section-23 inputs, with
   weights loaded from research policy. Changing weights requires a policy
   version bump; the old score is retained on every historical result.

8. validation/decision.py — returns one of PROMOTE / PROMISING /
   CONTINUE_RESEARCH / REGIME_SPECIALIST / DORMANT / QUARANTINE / REJECT /
   RETIRE, plus machine-readable reason_codes, plus the metric values that
   drove it. The natural-language explanation is optional decoration; the codes
   and metrics are authoritative.

9. tests/laws/test_holdout_sacred.py — second access raises. The research role's
   DB credentials genuinely cannot SELECT from the holdout schema (test it with
   a real connection, not a mock).

Verify with: pytest tests/ -v and run a deliberately overfit strategy
(50 free parameters fit to noise) through the pipeline — PBO must exceed 0.5
and the decision must be REJECT with reason_code OVERFITTING.
```

---

## PROMPT 4 — Experiments, lineage, and the queue

```
Build experiment tracking and lineage. Read CLAUDE.md.

1. experiments/models.py — Experiment table per section 47 of blueprint_a:
   experiment_id, strategy_id, parent_experiment_id, hypothesis, change_set
   (structured diff, not prose), data_version, code_sha, config_hash, seed,
   metrics, regime_results, decision, reason_codes, timestamp, compute_cost.
   Append-only (the Prompt 0 triggers already enforce this).

2. experiments/lineage.py — the family tree. Parent/child edges, efficient
   ancestor and descendant queries, and a diff function that answers "what
   exactly changed between generation N and N+1, and did OOS performance move
   in the direction the hypothesis predicted?" That last question is the whole
   point of the system; make it a first-class API method, not something you
   assemble by hand later.

3. experiments/queue.py — Postgres-backed job queue using
   SELECT ... FOR UPDATE SKIP LOCKED. No Redis. Priority, expected information
   value, estimated cost, retry with backoff, idempotency keys, dead-letter
   table. Jobs must be safe to interrupt: a killed worker loses no lineage.

4. experiments/failure.py — the failure taxonomy from blueprint_a section 26 as
   an enum, with a classifier that assigns codes from the metric evidence
   automatically. Aggregate queries: "what are the top failure modes this month",
   "which mutation types most often produce TRANSACTION_COST_FAILURE".

5. experiments/violations.py — RESEARCH_VIOLATION detection per Law 7 and
   blueprint_a section 62. Detect and log: a threshold changing while a
   specific strategy is pending, repeated holdout access attempts, a cost config
   loosening after a failed result, universe or benchmark changing after results
   are seen. These are logged prominently and surfaced in the API. The system
   snitching on itself is a feature.

6. experiments/runner.py — takes a queued job, runs backtest -> validation ->
   decision -> persist, fully instrumented, resumable, records compute cost.

Verify with: seed 200 synthetic experiments across a 4-generation tree,
then query the lineage API for "changes that improved OOS Sharpe" and confirm
the answer is correct against the seed data.
```

---

## PROMPT 5 — The ablation harness (BUILD THIS BEFORE ANY GENERATOR)

```
Build the component ablation harness. Read CLAUDE.md.

This exists before the generators deliberately. The author of AgentQuant — one of
the frameworks these blueprints recommend as the core self-improvement loop —
published that their own walk-forward validation showed the context-aware LLM
agent LOSING to a static baseline, and that investigating why led them to
discover look-ahead bias in their backtest. Treat "the clever component adds
nothing" as the default hypothesis for every component we add.

1. experiments/ablation.py — an A/B harness. Given a component under test,
   run N matched experiments with it enabled and N with it disabled, on the
   SAME data_version, SAME seeds, SAME cost config, SAME candidate budget.
   Report the difference in OOS Sharpe with a confidence interval, plus the
   compute and API cost delta.

2. A ComponentRegistry table per blueprint_a section 18: component, version,
   families affected, experiments run, median/mean/worst/best OOS improvement,
   risk impact, compute cost, latency, failure rate, and a verdict field
   (UNPROVEN / VALUABLE / NEUTRAL / HARMFUL). Every component starts UNPROVEN.

3. A hard gate: a component with verdict HARMFUL or with >200 experiments and
   still UNPROVEN is automatically disabled in the research policy. Log it.

4. The FIRST registered component is the baseline: a deterministic parameter
   grid search over a small set of classic strategy templates (momentum
   crossover, Bollinger mean reversion, volatility breakout, carry). Everything
   else in the system must beat THIS, measured, or it doesn't ship.

5. Interaction testing: support pairwise and triple combinations, since a
   component can be neutral alone and valuable in combination (blueprint_a
   section 17). Don't retire a component on solo evidence alone.

Verify with: run the harness on a placebo component (a flag that changes
nothing but the random seed). It must come back NEUTRAL with a CI straddling
zero. If a placebo shows improvement, your harness is broken.
```

---

## PROMPT 6 — Deterministic generation and evolution

```
Build strategy generation. Read CLAUDE.md. No LLMs in this prompt.

1. research/templates.py — the baseline strategy family templates as
   StrategySpecs with parameter ranges.

2. research/mutations.py — typed mutation operators over StrategySpec: change a
   lookback, add/remove a filter, change position sizing, change rebalance
   frequency, add volatility targeting, change entry/exit thresholds, swap an
   indicator. Each mutation records a structured change_set and a stated
   hypothesis about what it should improve and why.

3. research/crossover.py — combine components of two parent specs, preserving
   both lineages.

4. research/population.py — population management per blueprint_a section 25:
   states CHAMPION / PROMISING / EXPERIMENTAL / REGIME_SPECIALIST / DORMANT /
   QUARANTINED / REJECTED / RETIRED, and the five selection modes (exploitation,
   exploration, diversification, revival, cross-breeding) with ratios from the
   research policy. Nothing is ever hard-deleted.

5. research/complexity.py — parameter counting and a complexity penalty in
   scoring. Where two strategies are statistically indistinguishable, the
   simpler one wins.

6. research/prioritisation.py — expected-information-value scoring for the
   queue. Deprioritise regions of strategy space with a history of failure;
   use the failure taxonomy aggregates from Prompt 4 as input.

Evaluate stratevo (github.com/NeuZhou/stratevo) as an optional component here,
but note its README indicates the evolution engine and paper trading are in a
paid "Pro" tier — verify what the open repo actually contains before depending
on it. If it isn't fully open, use our own GA; register either choice as a
component and ablate it against the Prompt 5 baseline before keeping it.

Verify with: run 500 generations against the baseline. Then run the ablation
harness: does mutation+selection beat plain grid search on OOS, or not?
Report the honest answer, including if it's "no".
```

---

## PROMPT 7 — Paper trading

```
Build the paper-trading layer. Read CLAUDE.md. Law 5 applies absolutely: no
code path may reach a real-money endpoint.

1. paper/broker.py — an adapter interface with exactly one implementation:
   Binance testnet (or ccxt sandbox mode). The class must assert on init that
   the endpoint is a testnet URL and refuse to start otherwise. Credentials come
   from PAPER_ prefixed env vars only; the code raises if a variable name
   suggesting live credentials is present in the environment at all.

2. paper/execution.py — order lifecycle, position tracking, reconnection,
   idempotent order submission (a restart must not double-submit).

3. paper/reconciliation.py — the important part. For every paper trade, compare
   against what the backtest predicted: expected vs actual entry price, exit
   price, fill rate, slippage, latency, missed and rejected orders, realised
   cost, P&L. Persist the deltas.

4. paper/divergence.py — automatic investigation. When realised slippage
   materially exceeds modelled slippage, or fill rate drops, raise a
   PAPER_DIVERGENCE finding, quarantine the strategy, and — this is the useful
   feedback loop — propose a cost-model recalibration as a new experiment.
   The backtester learns from paper reality.

5. paper/duration.py — observation period derived from the strategy's horizon
   and the number of independent trades needed for a meaningful estimate, not a
   flat "2-4 weeks". A 3-day-horizon strategy reaches significance far sooner
   than a 90-day one.

6. Evaluate Qubx (github.com/xLydianSoftware/Qubx — note: NOT Qubx/Qubx, that
   path in the blueprint is wrong). It supports paper mode via
   `qubx run config.yml --paper` and is crypto-focused, which matches our
   universe. Read its actual API before wrapping. Register as a component,
   ablate, and be willing to conclude our own adapter is simpler.

Verify with: run a known strategy in paper for 48h against testnet, then run
reconciliation and confirm the backtest-vs-paper deltas are populated and
divergence detection fires when you deliberately mis-specify the cost model.
```

---

## PROMPT 8 — The world projection layer (do this before ANY art)

```
Build the world state projection. Read CLAUDE.md.

This is the contract between the quantitative system and the pixel world. It is
a PURE FUNCTION of database state. It contains no randomness, no art, no
business logic, and it is never a source of truth. Get this right and the
frontend is easy; get it wrong and you'll have a pretty dashboard that lies.

1. world/entities.py — the WorldState schema:

   WorldState {
     tick, generated_at, source_data_version,
     climate:   { regime, volatility_percentile, trend_strength,
                  crisis_flag, market_open },
     districts: [ per strategy FAMILY: id, name, archetype,
                  population_by_status {champion, promising, experimental,
                  regime_specialist, dormant, quarantined, retired},
                  health 0-1, activity 0-1, portfolio_weight,
                  building_state enum, alert_flags[] ],
     agents:    [ per ACTIVE JOB: id, role (scribe/engineer/experimenter/
                  statistician/guardian/auditor/necromancer), from_location,
                  to_location, progress 0-1, experiment_id ],
     structures:[ per pipeline component + per registry component:
                  id, kind, load 0-1, queue_depth, status, verdict ],
     events:    [ recent state transitions: type, subject_id, severity,
                  timestamp, drill_down_url ],
     treasury:  { total_equity, allocation_by_family, drawdown,
                  paper_pnl_today },
     laws:      [ each law + current compliance status + last violation ]
   }

   Every single field must be traceable to a SQL query. Write the mapping table
   in docs/WORLD_MAPPING.md: world field <- source table/column <- meaning.
   If you cannot name the query for a field, DELETE THE FIELD. No decorative
   state, no invented "power" numbers.

2. world/projection.py — build_world_state(session) -> WorldState. Pure,
   cached with a short TTL, target under 200ms. Property-test it: the same DB
   state always yields the identical WorldState.

3. Deterministic visual mapping, in code not in the frontend:
   strategy.status == QUARANTINED -> building_state SEALED + alert CHAINS
   strategy.status == DORMANT     -> building_state OVERGROWN
   drawdown > policy.storm_threshold -> alert_flags += STORM
   queue_depth high at validator  -> structures[oracle].load high
   Every mapping is a table in docs/WORLD_MAPPING.md, reviewable by a human.

4. api/routes/world.py — GET /world/state, and a WebSocket that pushes deltas
   (not full state) on change. Plus GET /world/drilldown/{entity_type}/{id}
   returning the real metrics behind any visual object — every clickable thing
   in the world resolves to actual evidence.

5. Agent animation is driven by the real job queue: an agent sprite exists
   because a job row exists, moves because the job changed stage, and vanishes
   when the job completes. Agent count IS queue depth. Never spawn decorative
   agents to make the scene look busy.

Verify with: property test that WorldState is a deterministic function of DB
state, and a test that asserts every field in the schema appears in
docs/WORLD_MAPPING.md.
```

---

## PROMPT 9 — The world view frontend

```
Build the frontend. Read CLAUDE.md and docs/WORLD_MAPPING.md.

Two modes, one data source (GET /world/state + the delta WebSocket). The
frontend holds NO business logic — it renders WorldState and nothing else.

WORLD VIEW — Next.js App Router + TypeScript + PixiJS v8.
Use PixiJS, not three.js: this is 2.5D sprite work, and Pixi's batched sprite
renderer handles hundreds of animated agents at 60fps in a way a 3D scene graph
won't. Isometric at the 2:1 pixel ratio (~26.565 degrees), NOT true 30-degree
isometric — 2:1 is the convention that keeps pixel edges clean.

- Tile-based isometric city. One DISTRICT per strategy family, sized by
  population, lit by health, weather-affected by climate.
- Buildings for pipeline structures: Library (ingestion), Forge (generation),
  Oracle (validation), Arena (comparative experiments), Vault (the holdout —
  rendered visibly sealed, and it must LOOK inaccessible because it IS),
  Treasury (portfolio), Harbour (paper trading), Archive and Underworld
  (retired and rejected strategies), Watchtower (alerts).
- Agents: small sprites pathfinding between buildings. One sprite per real
  queued/running job, role-coloured. Density is literally queue depth.
- Climate layer: rain/sun/lightning/fog driven by the regime classification.
- Everything is clickable. Click resolves to /world/drilldown and opens the
  Truth View panel for that entity. Two clicks maximum from any visual anomaly
  to the metrics that caused it.

TRUTH VIEW — conventional React + Recharts. Equity curves, walk-forward fold
results, IC decay curves, PBO and DSR values, regime breakdown tables, the
lineage tree (D3 hierarchy), experiment history, cost breakdowns, paper-vs-
backtest reconciliation. This view is plain, dense and professional. Sharpe is
displayed as a number, never as a health bar.

A single toggle switches modes, preserving the selected entity across both.

Art: generate placeholder programmatic sprites first (coloured isometric prisms
with distinct silhouettes per role and building type). The state machine must be
provably correct before anyone commissions pixel art. Ship a sprite-swap layer
so real art drops in without touching logic.

Performance budget: 60fps with 300 agents, under 40MB of textures, and it must
degrade to a static view rather than stall on a slow connection.

Verify with: a Storybook-style page that renders the world from a set of fixture
WorldState JSON files covering every enum value — healthy, quarantined, crisis
regime, empty queue, overloaded queue, law violation active.
```

---

## PROMPT 10 — LLM research layer (last, and gated)

```
Add the LLM research layer. Read CLAUDE.md. This ships LAST and only behind the
ablation harness from Prompt 5.

1. research/llm/hypothesis.py — the LLM emits ONLY: a hypothesis in structured
   form, a StrategySpec in the restricted DSL from Prompt 2, and a stated
   expected effect. It never sees the holdout. It never evaluates its own
   output. It never writes to any results table. It proposes; the quantitative
   engine judges.

2. research/llm/ingestion.py — arXiv and paper ingestion: fetch, parse, extract
   (hypothesis, variables, methodology, proposed signal, stated limitations),
   convert to a candidate StrategySpec, queue it as an ordinary experiment with
   no special status. A paper's claim earns a candidate a queue slot, nothing
   more. Look at VibeQuant (github.com/transcend-0/VibeQuant) for its extraction
   approach — but note it is built on the akquant engine and is A-share oriented,
   and its own docs describe its validation as an overfit-risk verdict from
   permutation testing with trial-count deflation, explicitly NOT sold as
   out-of-sample. Borrow the extraction ideas; keep our validation.

3. research/llm/budget.py — hard monthly spend cap from env. Every call logs
   model, tokens and estimated cost. At 80% of budget, switch to a cheaper
   model; at 100%, LLM generation halts and the deterministic generators
   continue. The research loop must degrade gracefully to zero LLM spend.

4. Register LLM generation as a component and run the full ablation against the
   Prompt 5 baseline before enabling it in the default policy. Report OOS
   improvement per euro of API spend. If it doesn't beat grid search net of
   cost, leave it disabled — and put that result in the Temple of Knowledge
   panel, because a well-measured negative result is the most valuable thing
   this system can produce in its first six months.

Optionally evaluate AgentQuant (github.com/OnePunchMonk/AgentQuant) and
QuantEvolve (github.com/tarsyang/quantevolve, a fork of OpenEvolve) as
components. Read their current code before integrating; both blueprints
described them from stale or inaccurate summaries.

Verify with: the ablation report, and a test proving the LLM path cannot
reach the holdout schema with its DB credentials.
```

---

## PROMPT 11 — Deployment (cost-constrained)

```
Deploy to Railway. Read CLAUDE.md, especially the cost discipline section.

Railway bills a plan fee plus metered usage at roughly $20/vCPU-month and
$10/GB-RAM-month, per second. The $5 Hobby figure is a usage credit, not a cap —
a service genuinely holding 1 vCPU and 1GB around the clock prices near $30/mo.
The seven-container architecture in blueprint B would cost $40-70/month. Build
the two-service version.

Services:
1. api — FastAPI + the Next.js frontend served as static export from the same
   container. Always on. Size it at 0.5 vCPU / 512MB and profile before growing.
2. postgres — Railway managed Postgres with the timescaledb extension, with a
   persistent volume. Always on.
3. worker — a Railway CRON service, NOT an always-on process. It wakes on
   schedule, drains the Postgres queue for a bounded wall-clock budget, and
   exits. This is the single biggest cost saving in the whole design and it
   costs you nothing in capability, because research is not latency-sensitive.

Schedules (in config, not hardcoded): data ingest hourly; research drain every
30 min during low-cost hours; paper reconciliation every 15 min while a paper
strategy is live; nothing retrains on a fixed 4-hour timer — retraining is
triggered by drift detection, not a clock.

Also build:
- Dockerfile, multi-stage, non-root user, no secrets in layers.
- Alembic migrations run on deploy, never destructive, always reversible.
- Nightly pg_dump to object storage. Test the RESTORE path in CI, because an
  untested backup is not a backup.
- /health and /ready endpoints; graceful shutdown that requeues in-flight jobs.
- Alerting to Discord webhook: law violations, research violations, paper
  divergence, data quality failures, drawdown breach, worker crash, budget cap.
- A /costs endpoint reporting Railway usage estimate + LLM spend month-to-date,
  surfaced in the world view as the Treasury's running expenses.

Repo: https://github.com/ALYTIC5/Project_Prometheus.git — set up CI to deploy
the api service on push to main, and require the tests/laws/ job to pass first.
A law-test failure must block deploy.

Verify with: deploy, then kill the worker mid-job and confirm no lineage is lost
and the job is picked up on the next cron tick.
```

---

## What I deliberately left out, and why

- **Redis.** Postgres `SKIP LOCKED` is sufficient at your volume and saves an
  always-on container.
- **RL, LSTMs, transformers.** Blueprint A is right that these are experiments,
  not components. Add them only after the ablation harness has something to
  compare against. They are also the most expensive things to run 24/7.
- **Multi-asset from day one.** One market, done honestly, beats four done
  badly.
- **The "34+ rolling windows" and "50-day shelf life" numbers.** Invented in
  blueprint B and copied without justification. Window count and horizon are
  derived per-strategy in Prompt 3.
- **"100% uptime."** Blueprint A correctly refuses this. Design for restart
  safety instead.

## On the €20-40/month goal

Two things need to be true simultaneously and neither is under your control.
First, the infrastructure has to stay near €10/month, which the two-service
design makes plausible. Second, a strategy has to survive the falsification
gates *and* keep working in paper *and* keep working with real money — and at a
10% net annual return, €30/month requires roughly €3,600 of capital.

The honest framing: build this to find out whether an edge exists, with the
falsification machinery strong enough that you'd believe a negative answer. If
the answer comes back "no edge," the system worked correctly. Most systems like
this never find out, because they were built to confirm rather than to refute.
Aim the first six months at cost reduction and a trustworthy negative result;
treat any profit as a surprise rather than a plan.

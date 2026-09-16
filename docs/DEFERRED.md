# Deferred work

Things explicitly scoped OUT of a prompt during implementation, with why and
what should trigger picking them back up. Not a TODO list of forgotten
work — every entry here was a deliberate, user-approved scope call, made
because the alternative was building real complexity with no current
caller to validate it against (CLAUDE.md: "don't build for hypothetical
future requirements").

Check this file before starting a later prompt that might resolve an entry,
and update the entry's status when it does.

---

## PROMPT 4 (experiments, lineage, queue, violations)

- **`HOLDOUT_REPEATED_ACCESS` violation detector** — no substrate
  (`holdout_access_log` doesn't exist). Enum member exists, `xfail(strict=
  True)` stub at `tests/test_violations.py::test_holdout_repeated_access_
  detected`. **Trigger:** Prompt 5's `validation/holdout.py`.
- **`COST_CONFIG_LOOSENED` violation detector** — no substrate at the time
  (`backtest/costs.py` was hardcoded constants). `xfail(strict=True)` stub
  at `tests/test_violations.py::test_cost_config_loosened_detected`.
  **Update (Prompt 3):** the substrate now partly exists —
  `config/costs.yaml` is real and versioned via `config_snapshots` (same
  mechanism `violations.detect_universe_changed_after_results` already
  uses). The detector function itself is still not written. **Trigger:**
  implement `detect_cost_config_loosened` in `experiments/violations.py`,
  reusing the `config_snapshots` row `record_config_snapshot(session,
  "config/costs.yaml")` now writes (see Prompt 3 section below).
- **`world_events` table** — `world/projection.py`'s `_get_recent_events`
  queries a table with no migration; `WorldState.events` is always `[]`.
  Not touched in Prompt 4 (world wiring there was jobs→agents only).
  **Trigger:** Prompt 10 (monitoring/alerts) is where PROMPTS.md assigns
  visual event emission.

## PROMPT S (plain dashboard)

- **Law 7's `compliant` flag in `world/projection.py`'s static `LAWS`
  list** — always hardcoded `true`, does not reflect real
  `research_violations` rows. The dashboard's violations banner reads
  `GET /violations/` directly instead, which is real. **Trigger:** wiring
  `LAWS[6].compliant` to a live query is a `world/projection.py` change,
  deliberately out of scope while that file was being kept exact.
- **DATA section** — genuinely empty, no `/data` route exists. **Trigger:**
  Prompt 2's ingestion is now real (done), so this is now just a missing
  API route + frontend wiring, not a data gap. Revisit.
- **COSTS section** — genuinely empty, no cost-tracking table.
  **Trigger:** Prompt 10 (Railway usage + LLM spend).
- **ESLint** — `npm run lint` has never been runnable in this repo; no
  config was ever committed, and it prompts interactively. Pre-existing,
  not introduced by any prompt in this arc. **Trigger:** whenever someone
  decides to actually set up lint config; not gating anything today since
  CI has no frontend job.

## PROMPT 2 (data layer)

- **Benchmark Sharpe** — `backtest/benchmark.py`'s `BenchmarkResult` has
  `max_drawdown_pct`/`final_value` but no `sharpe` field. Established
  precedent (`backtest/engine.py`'s own docstring): no hand-rolled Sharpe
  anywhere until cpz-quant. **Trigger:** Prompt 5, once cpz-quant is
  installed and wrapped — add `sharpe` to `BenchmarkResult` using the same
  library call the Oracle uses for strategies, not a second hand-rolled
  implementation.
- **Multi-asset benchmark caller** — `compute_benchmark_curve` genuinely
  supports `len(symbols) > 1` (tested), but nothing calls it with more than
  one symbol — `StrategySpec` is still single-`symbol` (Prompt 3 kept it
  that way too, see below). **Trigger:** whenever `StrategySpec` gains a
  real multi-asset `universe` field with an engine that can trade it —
  no prompt has committed to that yet.

## PROMPT 3 (strategy spec, cost model, execution, null suite)

- **`strategy/dsl.py`** — restricted expression language for signals.
  Not built; `entry_rules`/`exit_rules`/`signals`/`position_sizing`/
  `risk_rules` were not added to `StrategySpec` either (they ARE the DSL
  surface). Explicitly Prompt 9's job (the LLM that will emit it doesn't
  exist yet). **Trigger:** Prompt 9, or any earlier prompt that needs a
  second strategy family expressive enough that typed fields
  (`fast_window`/`slow_window`) stop being sufficient.
- **`backtest/execution_sim.py`** — partial fills, latency, illiquidity
  rejection. `engine.py`'s existing same-bar-with-`available_at`-lag model
  stays. **Trigger:** Prompt 7+ once the research loop can produce order
  sizes large enough relative to bar volume to need fill modeling, or
  Prompt 8 (paper trading) if reconciliation shows real slippage
  diverging from the flat-bps assumption.
- **ADV-based slippage + market-impact (square-root law) in
  `backtest/costs.py`** — `CostConfig`/`config/costs.yaml` only carry flat
  `taker_fee_bps`/`slippage_bps`. No trailing-volume data pipeline exists
  to feed a real ADV-relative model, and no second venue to differentiate
  per-venue costs against. **Trigger:** whenever a trailing-ADV feature
  exists (Prompt 5+'s feature pipeline) and/or a second venue is added.
- **`VsBenchmark.excess_sharpe`** — not added, same Sharpe precedent as
  `BenchmarkResult`. **Trigger:** Prompt 5/cpz-quant.
- **`VsBenchmark.information_ratio` / `tracking_error`** — NOT added
  either, for a different reason than Sharpe: computing them correctly
  needs the strategy curve (keyed per-bar, any timeframe) and the
  benchmark curve (keyed per-date) aligned onto a shared period grid, and
  doing that carelessly is exactly how a subtle bug gets into money-math
  code. `excess_return`, `periods_underperforming_pct` (date-aligned),
  and `max_relative_drawdown` (simple scalar subtraction) shipped instead
  — all real arithmetic, no alignment risk. **Trigger:** a dedicated pass
  that designs the multi-timeframe alignment properly, not a rushed
  addition to an already-large change.
- **`experiments/violations.py`'s `COST_CONFIG_LOOSENED` detector** — the
  substrate now exists (`config/costs.yaml` is real and versioned via
  `config_snapshots`, same mechanism `universe.yaml` uses — see
  `experiments/runner.py`'s `record_config_snapshot` calls). The detector
  function itself is still not written; `xfail(strict=True)` stub
  unchanged. **Trigger:** whoever picks up Law 7 detection completeness
  next — this one now only needs the query, not new infrastructure.

## PROMPT 5 (validation and falsification)

- **Holdout role vs. app superuser (Law 3's real limit)** — migration
  0010 creates a genuinely restricted, non-superuser `HOLDOUT_DB_ROLE`,
  SELECT-only on the `holdout` schema, and `validation/holdout.py`'s
  `access_holdout()` is the only application code path that ever
  authenticates as it. But Railway provisions this app's OWN database
  user (`prometheus`) as a Postgres SUPERUSER, which bypasses every
  GRANT/REVOKE — confirmed by querying `pg_roles` against the live
  deployment before writing the migration, not assumed. So today's real
  guarantee is: the restricted role is genuinely restricted, and
  `access_holdout()` is the only place that uses it. What is NOT true:
  nothing stops a *different*, buggy code path from using the app's own
  superuser DATABASE_URL to query `holdout.ohlcv_bars` directly — Postgres
  itself cannot prevent that for a superuser connection. **Trigger:**
  migrating the app's own DATABASE_URL off superuser to a real
  least-privilege role — a separate, higher-risk infra change touching
  the credential both live Railway services authenticate with today; the
  user explicitly chose not to do this in the same pass as this plan's
  own risk/benefit tradeoff.
- **`validation/splits.py`'s `derive_folds` not wired into a per-spec
  walk-forward re-backtest loop** — the function itself is real, tested,
  and used for real (metrics.py's `information_coefficient_ratio` slices
  IC per fold to compute ICIR). What PROMPTS.md's fuller framing implies
  — re-running `run_backtest` on each fold's held-out TEST window to get
  genuinely repeated out-of-sample performance draws per spec, not just
  per-fold IC — is not built. That would multiply `validate_grid`'s
  compute cost by the fold count per spec and needs its own careful
  design (mapping bar-index folds back to real timestamps for
  `load_point_in_time`). **Trigger:** if PBO/DSR alone prove insufficient
  evidence in practice, or a dedicated pass has budget for the added
  per-cycle compute.
- **`validation/regime.py`'s `classify_current_regime` not wired into
  `world/projection.py`'s `ClimateState`** — deliberate PROMPT 5 scope
  decision (user chose "validation layer + Oracle ACTIVE, climate after"
  over "everything including live climate"). The function is real,
  tested, and returns the exact 7-value uppercase enum
  `frontend/src/mapping/stateToVisual.ts` already expects — wiring it in
  is purely a `projection.py` change (call it inside `build_world_state`,
  where `row_counts`/`benchmark_curve` are already in scope) plus removing
  `ClimateState()`'s hardcoded empty default. **Trigger:** a focused
  follow-up pass, per the plan approved for this prompt.
- **`Verdict.RETIRE` structurally unreachable today** — `decision.py`'s
  `decide()` only returns RETIRE when `evidence.previous_verdict ==
  "PROMOTE"` and the strategy has since fallen WORSE_THAN_HOLDING. No
  strategy has ever been PROMOTEd yet (this is the first pass validation
  has ever run), so this branch is real code with no current caller that
  reaches it — same "empty exactly when nothing is actually claimed,
  never fabricated" rule `world/projection.py` already documents
  elsewhere. **Trigger:** nothing to do; it activates itself the first
  time a real PROMOTE later regresses.
- **DSR/PSR: hand-rolled, not cpz-quant** — not really a deferral (the
  work is done, see `validation/multiple_testing.py`), but recorded here
  too since it's the one place PROMPT 5's own text ("use cpz-quant for
  ... Deflated Sharpe") is not literally followed. cpz-quant 1.1.0's OSS
  package does not compute DSR/PSR at all — verified by reading its
  source before writing any code against it (`docs/DEPENDENCIES.md`'s
  cpz-quant entry has the full finding). **Trigger:** none expected;
  revisit only if a future cpz-quant release actually ships the
  computation cpz-ai's proprietary SDK currently reserves.

## PROMPT 6 (ablation harness, the Temple of Knowledge)

- **Carry template not built** — PROMPTS.md names four classic baseline
  templates (momentum crossover, Bollinger mean-reversion, volatility
  breakout, carry); only the first three are real. Carry needs futures
  funding-rate or spot-futures basis data, and this project's ccxt
  pipeline is spot-OHLCV only — confirmed by reading
  `config/universe.yaml` and every file under `prometheus/data/`, no
  futures ingestion exists anywhere. Building it would mean fabricating
  a signal from data that doesn't exist. **Trigger:** a real futures/
  funding-rate ingestion pipeline, which nothing in this project's
  current scope adds.
- **Interaction testing has no real second component to combine yet** —
  `experiments/ablation.py`'s `pairwise_interactions`/
  `triple_interactions` are real, tested machinery (composition,
  aggregation), exercised in `tests/test_ablation_interactions.py` with
  synthetic no-op component functions. Today only two components are
  ever registered: the deterministic grid baseline (zero trials,
  UNPROVEN by definition — it has nothing to be ablated against) and the
  placebo (NEUTRAL, the harness's own calibration proof). There is
  nothing real for the interaction functions to combine. **Trigger:**
  Prompt 7's evolution loop or Prompt 9's LLM layer registering a real
  second component — the moment one exists, pairwise/triple testing
  against it is a `run_ablation`-style call away, not a rebuild.
- **Ablation trials are cross-sectional (across symbols/params), not
  time-based walk-forward OOS** — each trial is a different real
  (symbol, spec) pair from the baseline grid, run once over the full
  window; generalization across the universe is this pass's
  out-of-sample dimension. This is the same limitation already logged
  under PROMPT 5: `validation/splits.py`'s `derive_folds` is real and
  tested but not wired into a per-fold re-backtest loop. Ablation
  inherits that gap rather than reintroducing a new one. **Trigger:**
  same as PROMPT 5's entry — a dedicated pass with budget for the added
  per-cycle compute of re-running every trial across multiple time folds.
- **`component_registry.failure_rate` is per-batch, not cumulative** —
  `ablation_trials` only ever stores trials that succeeded (a
  `ValueError`, e.g. insufficient bars for a spec's warm-up, is counted
  and never inserted), so a lifetime cumulative failure rate would need
  a separate attempted-trial counter this pass doesn't add. The
  registry's `failure_rate` column reflects only the most recent
  `run_ablation` batch. **Trigger:** if failure-rate trending over time
  turns out to matter once Prompt 7/9 run ablation batches routinely;
  a small addition (an attempts counter table) at that point, not a
  redesign.
- **Ablation batches are not wired into `worker.py`'s scheduled cycle**
  — `experiments/ablation.py`'s functions are real and tested (including
  a real DB-verified run in `tests/test_ablation_placebo.py`), but
  nothing calls `run_ablation`/`register_baseline` from the production
  worker cron yet, so `component_registry` stays empty in production
  until manually invoked once (same verification step Prompt 5 used:
  `railway ssh` + a one-off script, then confirmed via `/buildings/`).
  **Trigger:** deliberate — there is exactly one real component
  (baseline + placebo) to register today; wiring a recurring cron call
  makes sense once Prompt 7/9 give the worker something to actually
  re-evaluate on a schedule, not before.
- **Open research question, found while building the placebo acceptance
  test, not resolved: does a randomized position path carry a real cost
  relative to a structured one at matched exposure AND matched
  turnover?** Two genuinely different seed-driven "neutral" placebo
  designs were built and both reliably registered HARMFUL against real
  synthetic data (not statistical noise — stable across repeated
  independent draws): (1) independently coin-flipping ~5% of bars (adds
  real round-trip turnover, a real transaction-cost drag — understood,
  not mysterious), and (2) a true random permutation of the baseline's
  own position values (exact same total exposure time AND, since it's a
  permutation, arguably comparable turnover statistics) — this one's
  bias is NOT fully explained. The leading hypothesis is that a
  structured (trend-following/mean-reverting) position path compounds
  differently than a randomly-shuffled one with the identical exposure
  count, on any SPECIFIC finite realized price series, independent of
  drift or turnover — but this was not run down to a confirmed
  mechanism; `placebo_component` (ablation.py) shipped as a literal
  zero-variance no-op instead (a valid, defensible reading of PROMPTS.md's
  "changes only the seed", and the only version that is neutral by
  construction rather than merely observed-neutral-so-far). **Trigger:**
  genuinely curious follow-up, or relevant if a future real component
  (Prompt 7's evolution, Prompt 9's LLM layer) turns out to primarily
  work by changing WHEN trades happen rather than HOW MANY or how
  exposed — the ablation harness would need a placebo actually proven
  neutral against that specific kind of perturbation, not this one.

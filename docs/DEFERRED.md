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

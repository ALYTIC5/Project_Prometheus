# Random-Forest Strategy Family + Grid/Validate Family-Scoping Fix

## Goal

Add a new, genuinely ML-based strategy family (a RandomForestClassifier
predicting next-bar direction from engineered features) that runs through
the exact same backtest -> validate -> decision -> champion -> paper-trade
pipeline every other strategy uses, with a real A/B ablation against the
deterministic baseline grid (CLAUDE.md: "every component earns its place").

Fix a pre-existing production gap discovered while designing this, without
which RF (and the RSI/MACD families added earlier this session) can never
reach CHAMPION status at all.

## Background: the family-scoping bug

`worker.py`'s `_run_research()` is the only place that runs the
deterministic pipeline in production (the scheduled cron worker). It calls
two functions, both hardcoded to `_FAMILY = "MOMENTUM"`:

- `enqueue_grid(symbol, timeframe, family, days, ...)` -> internally calls
  `generate_grid(symbol, timeframe, family)`, which **raises** for any
  family except MOMENTUM.
- `validate_grid(session, symbol, timeframe, family, days)` -> internally
  calls the same `generate_grid`, re-scores those specs with real PBO/DSR/
  decay/regime evidence, and is the **only** code path that can write a
  `PROMOTE` verdict, which is the **only** verdict that sets
  `strategies.status = 'VALIDATED'` (`population.py`'s
  `_VERDICT_TO_STATUS`). `elect_champions()` only ever promotes a
  `VALIDATED` strategy to `CHAMPION`, and only a `CHAMPION` strategy is
  ever paper-traded.

So today: BOLLINGER/VOL_BREAKOUT/RSI/MACD strategies exist (created via
`swap_family` mutations, which call `run_one` directly, bypassing
`enqueue_grid`), get a quick ACCEPT/REJECT check, but are **structurally
unreachable** by `validate_grid` and can therefore never become
`VALIDATED`, never become `CHAMPION`, never get paper-traded — regardless
of actual strategy quality. This is the real reason the Harbour has been
empty and 1176/1176 recorded verdicts are REJECT: those are all MOMENTUM's
own REJECTs; every other family has never been through the Oracle at all.

`elect_champions()` itself is family-agnostic real SQL
(`DISTINCT ON (s.family) ... WHERE status = 'VALIDATED'`) — it was never
the blocker. `enqueue_grid`/`validate_grid`'s hardcoded MOMENTUM-only call
sites are.

## Fix: generalize the two call sites

Refactor `enqueue_grid`/`validate_grid` (`experiments/runner.py`) into a
family-agnostic core plus thin existing-signature wrappers, so nothing
that currently calls `enqueue_grid`/`validate_grid` with an explicit
family breaks:

- `enqueue_specs(symbol, timeframe, specs, days, *, priority, ...) -> list[str]`
  — the real body of today's `enqueue_grid`, taking a spec list directly
  instead of generating one internally.
- `enqueue_grid(symbol, timeframe, family, days, ...)` — unchanged
  signature, now just `enqueue_specs(symbol, timeframe, generate_grid(symbol, timeframe, family), days, ...)`.
- `enqueue_baseline_grid(symbol, timeframe, days, ...)` — new,
  `enqueue_specs(symbol, timeframe, generate_baseline_grid(symbol, timeframe), days, ...)`.
- Same three-way split for `validate_grid` -> `validate_specs` +
  `validate_grid` (unchanged) + `validate_baseline_grid` (new).

`worker.py`'s `_run_research()` changes its two call sites:

```python
for symbol in symbols:
    await enqueue_baseline_grid(symbol, _TIMEFRAME, _GRID_LOOKBACK_DAYS, ...)
    await enqueue_specs(
        symbol, _TIMEFRAME, generate_random_forest_grid(symbol, _TIMEFRAME),
        _GRID_LOOKBACK_DAYS, ...,
    )

ran = await drain_queue()

validated: list[str] = []
async with get_session() as session:
    for symbol in symbols:
        validated.extend(await validate_baseline_grid(session, symbol, _TIMEFRAME, _GRID_LOOKBACK_DAYS))
        validated.extend(await validate_specs(
            session, symbol, _TIMEFRAME,
            generate_random_forest_grid(symbol, _TIMEFRAME), _GRID_LOOKBACK_DAYS,
        ))
```

`enqueue_specs`/`enqueue_grid`'s existing idempotency-key dedup
(`sha256(kind, config_hash, days)`, `ON CONFLICT DO NOTHING`) means turning
this on produces a one-time backlog of the previously-unreachable
BOLLINGER/VOL_BREAKOUT/RSI/MACD grid combinations (~24 specs/symbol,
~50 symbols ≈ 1200 new jobs), then goes quiet — every subsequent cycle
enqueues nothing new for those same fixed grids, same steady-state cost
shape as MOMENTUM today. Cheap: each backtest is one vectorized polars
pass over ≤800 daily bars.

## RANDOM_FOREST: why it's a separate component, not a sixth baseline family

`generate_baseline_grid`'s own docstring: this combined set "IS the real,
deterministic parameter grid... every future component has to beat."
MOMENTUM/BOLLINGER/VOL_BREAKOUT/RSI/MACD are all cited, static, technical
constructions — the baseline. RANDOM_FOREST is a genuinely new *generation
mechanism* (like Prompt 7's evolution and Prompt 9's LLM hypothesis layer),
not a sixth template to add to that same baseline set. Consequences of
that distinction, all deliberate:

- `FAMILY_RANDOM_FOREST` is added to `StrategySpec`'s `_FAMILY_PARAMS` (so
  a valid spec can be constructed and validated) but **not** to the
  `FAMILIES` tuple. `FAMILIES` gates `swap_family`'s "which family could I
  mutate into" list and the LLM hypothesis system prompt's advertised
  options — RF strategies are not swap-family-reachable and the LLM is
  never asked to invent RF hyperparameters from a paper abstract. This
  matches the same reasoning `generate.py` already uses to keep Carry out
  entirely (not everything belongs in every mechanism).
- It gets its own generator (`generate_random_forest_grid`, not folded
  into `generate_baseline_grid`) and its own ablation registration
  (`register_ml_component`, mirroring `register_evolution_component`/
  `register_llm_component`: best RF score vs. best baseline-grid score,
  per symbol, on real out-of-sample data, recorded via `record_trial`).
- `elect_champions()`, `population_summary()`'s real SQL, the dashboard's
  `/strategies/`, `/experiments/`, `/paper/` routes, and `parameter_tune`
  mutation are all already family-agnostic (driven by `spec.parameters`/
  real DB rows, not the `FAMILIES` tuple) — RF strategies flow through
  every one of them with zero additional code once they exist as real
  `Strategy` rows. This is the whole reason the earlier Harbour work pays
  off here: no new paper-trading code is needed at all.

## New dependency: scikit-learn

Recorded in `docs/DEPENDENCIES.md`: `scikit-learn==1.5.2` (pinned, latest
stable compatible with this repo's `numpy==2.4.6`/`python>=3.11` floor).
Replaces nothing (first ML dependency in the repo). Not stdlib/pandas/
polars-expressible: a real random-forest fit is a recursive, greedy
tree-building algorithm, not a vectorizable column expression — this is
the first strategy family whose signal is NOT a pure polars pipeline.

## Feature engineering (`prometheus/backtest/ml_features.py`)

Pure polars, six columns, all computed from each bar's own close/volume
(same "raw condition uses today's own close" convention every other
family's signal function already uses — the look-ahead guard is the
walk-forward loop's own discipline below, not hidden inside this module):

| Feature | Formula |
|---|---|
| `f_ret1` | `close.pct_change(1)` |
| `f_ret5` | `close.pct_change(5)` |
| `f_vol10` | `close.rolling_std(10) / close` |
| `f_rsi` | Wilder's RSI(14), raw value (reuses `engine.py`'s avg-gain/avg-loss construction, unthresholded) |
| `f_macd_hist` | MACD(12,26,9) line minus its own signal line (reuses `engine.py`'s EMA construction) |
| `f_vol_chg` | `volume.pct_change(1)` |

Feature periods (14/12/26/9/10/5) are fixed constants, not spec fields —
these are the fixed "sensor" the model reads, not the strategy's own
tunable hypothesis; keeping them out of the spec keeps the family's
identity space bounded (3 tunable fields, same order as MACD's 3) instead
of exploding the grid.

Label (training-only, never used as a feature, never used for the row
being predicted): `label = (close.shift(-1) > close).cast(int)`. Null on
the frame's final row (no next bar exists) — that row is dropped from any
training set, never trained on, never predicted with a fabricated label.

## Walk-forward signal (`prometheus/backtest/ml_signal.py`)

`StrategySpec` gains three new tunable fields for `FAMILY_RANDOM_FOREST`:

- `rf_train_window: int` — trailing bars used for each fit (grid: 120,
  250 — roughly 6mo/1yr of daily bars).
- `rf_retrain_interval: int` — bars between refits (grid: 20, 40 —
  roughly 1mo/2mo).
- `rf_predict_threshold: float` — predicted-up probability cutoff to go
  long (grid: 0.5, 0.55).

`expected_horizon = 1` for every RF spec, fixed, not derived from any of
the above — the model's actual, honest claim is "predicts one bar ahead,"
regardless of how often it's retrained or how much history it trains on.

`StrategySpec`'s `_params_match_family` validator gains one more
family-specific block, same shape as MOMENTUM's/VOL_BREAKOUT's/MACD's own
inequality checks: `rf_train_window > 0`, `0 < rf_retrain_interval <= rf_train_window`
(a retrain cadence longer than the training window itself would mean the
model only ever fits once and then goes stale forever — not invalid
mechanically, but not a real "walk-forward" claim either, so it's
rejected the same way `exit_window >= breakout_window` is), and
`0.0 < rf_predict_threshold < 1.0` (a probability, not a raw score).

Algorithm (Python loop over checkpoints — this is the one signal function
in the codebase that is not a pure vectorized polars expression, and its
docstring says so plainly):

1. Build the feature+label frame once (`ml_features.build_feature_frame`).
2. `raw = [0.0] * n` (flat until the first checkpoint — same "insufficient
   warm-up defaults to flat" honesty every other family's `fill_null(0.0)`
   already expresses).
3. For each `checkpoint` in `range(rf_train_window, n, rf_retrain_interval)`:
   - Train rows: `[checkpoint - rf_train_window, checkpoint)`, dropping
     any row whose label is null (only possible for the frame's own final
     row, and only relevant if a checkpoint lands there).
   - Fit `RandomForestClassifier(n_estimators=100, max_depth=4, min_samples_leaf=10, random_state=0, n_jobs=1)`
     on those rows' six features -> label. Fixed, small, shallow-tree
     hyperparameters — not spec fields, not tuned per grid point: a small
     forest is what keeps a few-hundred-row daily-bar training set from
     both overfitting and costing real compute across dozens of symbols
     times 8 grid points times however many retrains per backtest, and
     `random_state=0`/`n_jobs=1` make every fit exactly reproducible
     (CLAUDE.md's "deterministic core," same seed-everywhere posture as
     `core.ids`/`experiments.runner`'s own `derive_seed`/`rng_for`).
   - Predict rows `[checkpoint, min(checkpoint + rf_retrain_interval, n))`
     from that fitted model's own `predict_proba`; `raw[row] = 1.0` if the
     predicted-up probability ≥ `rf_predict_threshold`, else `0.0`.
4. `position = raw.shift(1).fill_null(0.0)` — the same final discipline
   `_sma_signal`/`_bollinger_signal`/`_rsi_signal`/`_macd_signal` all end
   with: today's prediction becomes tomorrow's held position, never
   today's own.

No Law 1 violation: every training row at `checkpoint` is strictly before
`checkpoint`; every prediction row's own features use only that row's own
close/volume (same as every other family's raw condition); the model
trained to predict rows `[checkpoint, checkpoint+interval)` never saw a
label requiring data at or beyond its own training cutoff. No Law 3
interaction: this runs entirely inside `PointInTimeFrame.as_of(cutoff)`'s
already-bounded frame, the same mechanism every other family relies on —
there is nothing holdout-specific here to build, because the holdout
schema is physically separate and simply never appears in this data at
all.

`backtest/engine.py`'s `signal_for()`/`_min_bars_for()` gain a fourth
dispatch branch (`FAMILY_RANDOM_FOREST` -> `ml_signal.random_forest_signal`;
minimum bars = `rf_train_window + 30`, the +30 covering the feature
columns' own warm-up — RSI/MACD/rolling-std need up to 26 bars before
their first non-null value).

## Generator (`prometheus/research/ml/generate.py`)

`generate_random_forest_grid(symbol, timeframe) -> list[StrategySpec]`:
the 2×2×2 = 8-point grid above (`rf_train_window` × `rf_retrain_interval`
× `rf_predict_threshold`), each spec's `expected_horizon=1`,
`family=FAMILY_RANDOM_FOREST`. New `prometheus/research/ml/__init__.py`
package — physically separate from `research/generate.py`, matching the
conceptual separation above (this is not part of the baseline grid).

## Ablation (`experiments/ablation.py`)

`register_ml_component(session, *, symbols, timeframe, start, end, version, cost_model)`:
same shape as `register_evolution_component`/`register_llm_component` —
per symbol, score every baseline-grid spec and every
`generate_random_forest_grid` spec with the real backtest engine on real
out-of-sample data, `record_trial` (enabled = best RF score, disabled =
best grid score), `_recompute_registry(session, "random_forest", version, ["RANDOM_FOREST"], ...)`.
Reported honestly, including a NEUTRAL or HARMFUL verdict — this is the
real answer to "does training a model on this data find anything the
static baselines don't," not assumed in advance.

## Mutation

`research/mutations.py`'s `_SMOOTHING_FIELDS` gains `rf_train_window`
(longer training history -> a more stable model -> predicted lower
drawdown, same directional-claim reasoning already applied to every other
family's own window fields). `rf_retrain_interval` and
`rf_predict_threshold` are left out — retraining less often could smooth
or could just mean a staler model reacting to a changed regime, and a
higher probability threshold makes entries rarer but not obviously
"smoother"; both get the honest "no hypothesis" `parameter_tune` already
gives fields outside `_SMOOTHING_FIELDS`. `crossover.py`/`templates.py`
need no changes (already generic over `spec.parameters`); `swap_family`
never reaches RANDOM_FOREST (it is not in `FAMILIES`, by design above).

## Dashboard

`frontend/src/dashboard/LiveActivity.tsx`'s `FAMILY_COLOR` gains a
`RANDOM_FOREST` entry. No other frontend change — `/strategies/`,
`/experiments/`, `/paper/`, `BacktestScatterSection` all already render
whatever `family`/verdict values actually exist in the data.

## Testing

- `tests/test_ml_features.py`: `build_feature_frame` produces the six
  columns, respects the no-look-ahead convention (a planted future spike
  affects no feature value at or before that bar), the label column is
  correctly shifted and null only on the final row.
- `tests/test_ml_signal.py`: `random_forest_signal` warms up flat before
  the first checkpoint, retrains on schedule, a real synthetic trending
  series (constructed so next-bar direction is trivially predictable from
  `f_ret1`'s own sign) produces nonzero turnover, and — critically — a
  planted extreme move on the frame's own final bar cannot affect any
  position held before that bar (same no-look-ahead test shape as every
  other family, adapted for the walk-forward loop: assert the checkpoint
  arithmetic itself never lets a training window reach a row ≥ its own
  checkpoint).
- `tests/test_strategy_spec.py`: RANDOM_FOREST validator round-trip
  (valid spec constructs; missing/foreign fields raise; `FAMILY_RANDOM_FOREST not in FAMILIES`
  asserted explicitly, documenting the deliberate exclusion so a future
  edit can't silently "fix" it into the tuple).
- `tests/test_research_generate.py`-equivalent for the new module:
  `generate_random_forest_grid` produces 8 valid specs, all
  `family == RANDOM_FOREST`, none appear in `generate_baseline_grid`'s
  output.
- `tests/test_queue_semantics.py`/`experiments/runner.py`'s existing
  tests: extend for `enqueue_specs`/`validate_specs` for the extracted
  generic core, and add a regression test that
  `enqueue_baseline_grid`/`validate_baseline_grid` actually produce
  non-MOMENTUM jobs/verdicts (the exact bug this spec fixes — a test that
  would have caught it originally).
- `tests/test_ablation.py`-equivalent additions for `register_ml_component`,
  mirroring the existing evolution/LLM ablation tests' shape.

## Deployment / cost note

The `enqueue_baseline_grid`/`validate_baseline_grid` fix produces a
one-time backlog (~1200 jobs across the existing crypto+ETF universe) the
worker's cron will drain over its next several 30-minute cycles — bounded,
CPU-only, no schema change, no new Railway service. `scikit-learn` adds a
real but modest wheel size to the worker/API container (pure compiled
wheel, no GPU dependency) — within this project's "two always-on services
+ one worker" cost target, no new service required.

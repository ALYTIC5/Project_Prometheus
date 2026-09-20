# Random-Forest Strategy Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `RANDOM_FOREST` strategy family (walk-forward-retrained
RandomForestClassifier predicting next-bar direction) that runs through
the real backtest/validate/decision/champion/paper-trade pipeline with its
own A/B ablation, and fix the pre-existing bug where `enqueue_grid`/
`validate_grid` are hardcoded to MOMENTUM in production, meaning no other
family (BOLLINGER/VOL_BREAKOUT/RSI/MACD included) has ever been able to
reach `VALIDATED` status.

**Architecture:** A new, non-vectorized signal function
(`backtest/ml_signal.py`) walk-forward-trains a small RandomForestClassifier
on six lag-safe polars-computed features (`backtest/ml_features.py`),
dispatched from `backtest/engine.py`'s existing `signal_for()`/
`_min_bars_for()`. `RANDOM_FOREST` is deliberately kept out of
`StrategySpec.FAMILIES` (it is a generation *component*, like evolution/
LLM hypotheses, not a sixth baseline template) with its own generator
(`research/ml/generate.py`) and ablation registration
(`experiments/ablation.register_ml_component`). `experiments/runner.py`'s
`enqueue_grid`/`validate_grid` are refactored into a generic
`enqueue_specs`/`validate_specs` core plus thin family-specific and
baseline-grid wrappers; `worker.py`'s `_run_research()` is rewired to use
the baseline-grid wrappers (fixing the MOMENTUM-only bug) and to enqueue/
validate the RF grid directly.

**Tech Stack:** Python 3.11, polars, scikit-learn (new), SQLAlchemy async,
pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md`

## Global Constraints

- `RANDOM_FOREST` is added to `StrategySpec._FAMILY_PARAMS` but **NOT** to
  the `FAMILIES` tuple — deliberate, tested explicitly (Task 1).
- `expected_horizon = 1` for every RF spec, always, regardless of
  `rf_train_window`/`rf_retrain_interval`.
- Feature periods (RSI 14, MACD 12/26/9, rolling-vol 10, return lags 1/5)
  are fixed module constants in `ml_features.py`, never `StrategySpec`
  fields.
- Model hyperparameters (`n_estimators=100`, `max_depth=4`,
  `min_samples_leaf=10`, `random_state=0`, `n_jobs=1`) are fixed module
  constants in `ml_signal.py`, never `StrategySpec` fields.
- Every signal function ends with `.shift(1).fill_null(0.0)` on the final
  `position` column — RF's walk-forward loop is no exception.
- `enqueue_grid`/`validate_grid`'s existing signatures and behavior must
  not change (no breaking changes to any existing caller/test) — they
  become thin wrappers over the new generic functions.
- No new Railway service; scikit-learn is CPU-only, no GPU dependency.

---

### Task 1: `RANDOM_FOREST` family in `StrategySpec` + dependency + wiring

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `docs/DEPENDENCIES.md` (new table row)
- Modify: `prometheus/strategy/spec.py`
- Modify: `prometheus/research/mutations.py` (`_SMOOTHING_FIELDS`)
- Modify: `frontend/src/dashboard/LiveActivity.tsx` (`FAMILY_COLOR`)
- Test: `tests/test_strategy_spec.py`

**Interfaces:**
- Produces: `FAMILY_RANDOM_FOREST: str` constant, `StrategySpec` fields
  `rf_train_window: int | None`, `rf_retrain_interval: int | None`,
  `rf_predict_threshold: float | None` — every later task constructs
  `StrategySpec(family=FAMILY_RANDOM_FOREST, ..., rf_train_window=..., rf_retrain_interval=..., rf_predict_threshold=..., expected_horizon=1)`.

- [ ] **Step 1: Install scikit-learn and pin the resolved version**

Run: `pip install scikit-learn`

Note the exact version pip resolves (`pip show scikit-learn`), then add
this line inside `pyproject.toml`'s `dependencies = [...]` list, right
after the `"cpz-quant==1.1.0",` line:

```python
    "scikit-learn==<RESOLVED_VERSION>",
```

- [ ] **Step 2: Record the dependency in `docs/DEPENDENCIES.md`**

Add a new row to the dependency table, after the `cpz-quant` row:

```markdown
| scikit-learn | <RESOLVED_VERSION> | The RANDOM_FOREST strategy family's walk-forward RandomForestClassifier (`backtest/ml_signal.py`) -- the first strategy family whose signal is not a pure vectorized polars expression. | No prior ML dependency existed | A random-forest fit is a real, sequential, greedy tree-building algorithm, not a column expression polars/pandas can express; hand-rolling one would be reimplementing a well-established, heavily-optimized algorithm CLAUDE.md's "don't reimplement from scratch" spirit (already applied to PBO/DSR via cpz-quant) argues against. CPU-only, no GPU dependency, no new Railway service. |
```

- [ ] **Step 3: Write the failing spec tests**

Add to `tests/test_strategy_spec.py` (check its existing imports first —
add `FAMILY_RANDOM_FOREST` and `FAMILIES` to whatever it already imports
from `prometheus.strategy.spec`):

```python
def test_random_forest_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
        rf_train_window=120, rf_retrain_interval=20, rf_predict_threshold=0.5,
        expected_horizon=1,
    )
    assert spec.family == FAMILY_RANDOM_FOREST
    assert spec.parameters == {
        "rf_train_window": 120.0, "rf_retrain_interval": 20.0, "rf_predict_threshold": 0.5,
    }


def test_random_forest_missing_fields_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d", expected_horizon=1,
        )


def test_random_forest_retrain_interval_exceeding_train_window_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
            rf_train_window=20, rf_retrain_interval=50, rf_predict_threshold=0.5,
            expected_horizon=1,
        )


def test_random_forest_threshold_out_of_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
            rf_train_window=120, rf_retrain_interval=20, rf_predict_threshold=1.5,
            expected_horizon=1,
        )


def test_random_forest_deliberately_excluded_from_families_tuple() -> None:
    """RANDOM_FOREST is a separate generation component (like evolution/
    LLM hypotheses), not part of the classic-template baseline FAMILIES
    tuple swap_family/the LLM system prompt draw from. This test
    documents the exclusion so a future edit can't silently 'fix' it
    into the tuple."""
    assert FAMILY_RANDOM_FOREST not in FAMILIES
```

(`pytest` must already be imported in this file — check before adding a
duplicate import.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategy_spec.py -k random_forest -v`
Expected: FAIL with `AttributeError`/`ImportError` (`FAMILY_RANDOM_FOREST` doesn't exist yet)

- [ ] **Step 4: Add the family constant, fields, and validator to `prometheus/strategy/spec.py`**

Add the constant right after `FAMILY_MACD`, **without** adding it to `FAMILIES`:

```python
FAMILY_RANDOM_FOREST = "RANDOM_FOREST"
```

Add to `_FAMILY_PARAMS`:

```python
    FAMILY_RANDOM_FOREST: ("rf_train_window", "rf_retrain_interval", "rf_predict_threshold"),
```

Add fields, right after the MACD fields:

```python
    # RANDOM_FOREST: a walk-forward-retrained RandomForestClassifier
    # predicting next-bar direction. Deliberately NOT in FAMILIES (see
    # docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md)
    # -- a generation component measured against the baseline, not a
    # member of it.
    rf_train_window: int | None = None
    rf_retrain_interval: int | None = None
    rf_predict_threshold: float | None = None
```

Add to `_params_match_family`'s validator, right after the MACD check:

```python
        if self.family == FAMILY_RANDOM_FOREST:
            if self.rf_train_window <= 0:  # type: ignore[operator]
                raise ValueError("rf_train_window must be positive")
            if not (0 < self.rf_retrain_interval <= self.rf_train_window):  # type: ignore[operator]
                raise ValueError("rf_retrain_interval must be in (0, rf_train_window]")
            if not (0.0 < self.rf_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("rf_predict_threshold must be in (0, 1)")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_strategy_spec.py -k random_forest -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Add the smoothing-field mutation hint**

In `prometheus/research/mutations.py`, add `"rf_train_window"` to the
`_SMOOTHING_FIELDS` set (longer training history -> a more stable model
-> predicted lower drawdown, same directional-claim reasoning already
applied to every other family's own window fields):

```python
_SMOOTHING_FIELDS = {
    "slow_window", "fast_window", "lookback_window", "breakout_window",
    "exit_window", "band_multiplier", "rsi_lookback", "macd_fast",
    "macd_slow", "macd_signal", "rf_train_window",
}
```

- [ ] **Step 7: Add the dashboard color**

In `frontend/src/dashboard/LiveActivity.tsx`'s `FAMILY_COLOR`:

```typescript
  RANDOM_FOREST: 'border-sky-500/60 text-sky-700 dark:text-sky-400',
```

- [ ] **Step 8: Run the full non-DB backend suite**

Run: `pytest tests/ -q -m "not db"`
Expected: PASS, no new failures

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml docs/DEPENDENCIES.md prometheus/strategy/spec.py prometheus/research/mutations.py frontend/src/dashboard/LiveActivity.tsx tests/test_strategy_spec.py
git commit -m "feat(strategy): add RANDOM_FOREST family fields and dependency"
```

---

### Task 2: Feature engineering (`prometheus/backtest/ml_features.py`)

**Files:**
- Create: `prometheus/backtest/ml_features.py`
- Test: `tests/test_ml_features.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (pure polars over a bars
  DataFrame with `close`/`volume` columns, the same schema every other
  `_family_signal` function in `backtest/engine.py` already takes).
- Produces: `FEATURE_COLUMNS: tuple[str, ...]` (six names),
  `build_feature_frame(bars: pl.DataFrame) -> pl.DataFrame` — returns
  `bars` with `FEATURE_COLUMNS` and a `label` column appended. Task 3's
  `ml_signal.py` imports both.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_features.py`:

```python
"""prometheus/backtest/ml_features.py's build_feature_frame -- the
RANDOM_FOREST family's feature engineering. Real synthetic price paths,
same _bar_row pattern tests/test_null_strategies.py already
establishes."""
from __future__ import annotations

import polars as pl

from prometheus.backtest.ml_features import FEATURE_COLUMNS, build_feature_frame
from tests.test_null_strategies import _bar_row

_SYMBOL = "BTC/USDT"


def test_feature_columns_are_produced() -> None:
    rows = [_bar_row(_SYMBOL, i, 100.0 + i) for i in range(40)]
    bars = pl.DataFrame(rows)
    frame = build_feature_frame(bars)
    for column in FEATURE_COLUMNS:
        assert column in frame.columns
    assert "label" in frame.columns


def test_label_is_shifted_forward_and_null_on_the_final_row() -> None:
    prices = [100.0, 105.0, 103.0, 110.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    frame = build_feature_frame(bars)
    labels = frame["label"].to_list()
    # bar 0 -> 1 rises (100 -> 105): label 1.0
    # bar 1 -> 2 falls (105 -> 103): label 0.0
    # bar 2 -> 3 rises (103 -> 110): label 1.0
    # bar 3: no next bar -- label must be null, never fabricated
    assert labels[0] == 1.0
    assert labels[1] == 0.0
    assert labels[2] == 1.0
    assert labels[3] is None


def test_features_have_no_lookahead_planted_future_spike_is_unreachable() -> None:
    """A dip planted only in the LAST bar must not affect any FEATURE
    value at any earlier bar -- same no-lookahead convention every other
    family's signal function is tested against. (label is exempt: it is
    training-only and legitimately looks one bar forward by
    construction, but is never itself a feature.)"""
    baseline_prices = [100.0] * 30
    spiked_prices = [100.0] * 29 + [1.0]
    baseline_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(baseline_prices)]
    spiked_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(spiked_prices)]
    baseline_frame = build_feature_frame(pl.DataFrame(baseline_rows))
    spiked_frame = build_feature_frame(pl.DataFrame(spiked_rows))
    for column in FEATURE_COLUMNS:
        baseline_values = baseline_frame[column].to_list()[:-1]
        spiked_values = spiked_frame[column].to_list()[:-1]
        assert baseline_values == spiked_values, f"{column} leaked the future spike"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.backtest.ml_features'`

- [ ] **Step 3: Implement `prometheus/backtest/ml_features.py`**

```python
"""Feature engineering for the RANDOM_FOREST strategy family
(prometheus/backtest/ml_signal.py). Six lag-safe features plus one
training-only label column -- pure polars, no look-ahead beyond what
every other family's own "raw condition computed with today's own
close" convention already allows (backtest/engine.py's _sma_signal,
_bollinger_signal, etc. all compute their raw condition from the
CURRENT bar's own close, then shift(1) the final result once -- the
walk-forward loop in ml_signal.py applies that same final shift(1) to
this module's raw predictions, not to the features themselves).

Feature periods (14-bar RSI, 12/26/9 MACD, 10-bar rolling vol, 1-bar and
5-bar returns) are fixed constants, not StrategySpec fields -- these are
the model's fixed "sensors", not the strategy's own tunable hypothesis
(which lives in rf_train_window/rf_retrain_interval/rf_predict_threshold
instead, see strategy/spec.py). Keeping them fixed keeps the family's
identity space bounded, same reasoning generate.py's own docstrings give
for keeping each family's grid small and enumerated.
"""
from __future__ import annotations

import polars as pl

_RSI_LOOKBACK = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_VOL_LOOKBACK = 10

FEATURE_COLUMNS = ("f_ret1", "f_ret5", "f_vol10", "f_rsi", "f_macd_hist", "f_vol_chg")


def build_feature_frame(bars: pl.DataFrame) -> pl.DataFrame:
    """Returns `bars` with FEATURE_COLUMNS and a `label` column appended.
    `label` is 1.0 if the NEXT bar's close is higher than this bar's own
    close, else 0.0 -- null on the frame's own final row (no next bar
    exists), which the caller must drop before ever training on it.
    `label` is training-only: it is never itself a feature, and the
    walk-forward loop in ml_signal.py never looks at a row's own label
    when predicting that row's own position."""
    delta = pl.col("close").diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    rsi_alpha = 1.0 / _RSI_LOOKBACK

    return (
        bars.with_columns(
            pl.col("close").pct_change(1).alias("f_ret1"),
            pl.col("close").pct_change(5).alias("f_ret5"),
            (pl.col("close").rolling_std(_VOL_LOOKBACK) / pl.col("close")).alias("f_vol10"),
            pl.col("volume").pct_change(1).alias("f_vol_chg"),
            gain.alias("_gain"),
            loss.alias("_loss"),
            pl.col("close").ewm_mean(span=_MACD_FAST, adjust=False).alias("_ema_fast"),
            pl.col("close").ewm_mean(span=_MACD_SLOW, adjust=False).alias("_ema_slow"),
            (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Float64).alias("label"),
        )
        .with_columns(
            pl.col("_gain").ewm_mean(alpha=rsi_alpha, adjust=False).alias("_avg_gain"),
            pl.col("_loss").ewm_mean(alpha=rsi_alpha, adjust=False).alias("_avg_loss"),
            (pl.col("_ema_fast") - pl.col("_ema_slow")).alias("_macd"),
        )
        .with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss"))).alias("f_rsi"),
            pl.col("_macd").ewm_mean(span=_MACD_SIGNAL, adjust=False).alias("_signal_line"),
        )
        .with_columns((pl.col("_macd") - pl.col("_signal_line")).alias("f_macd_hist"))
        .drop(
            "_gain", "_loss", "_avg_gain", "_avg_loss",
            "_ema_fast", "_ema_slow", "_macd", "_signal_line",
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_features.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: mypy strict**

Run: `mypy prometheus/backtest/ml_features.py --strict`
Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add prometheus/backtest/ml_features.py tests/test_ml_features.py
git commit -m "feat(backtest): RANDOM_FOREST feature engineering"
```

---

### Task 3: Walk-forward signal (`prometheus/backtest/ml_signal.py`) + engine dispatch

**Files:**
- Create: `prometheus/backtest/ml_signal.py`
- Modify: `prometheus/backtest/engine.py`
- Test: `tests/test_ml_signal.py`

**Interfaces:**
- Consumes: `FEATURE_COLUMNS`, `build_feature_frame` from Task 2's
  `prometheus.backtest.ml_features`; `FAMILY_RANDOM_FOREST`,
  `StrategySpec.rf_train_window`/`rf_retrain_interval`/`rf_predict_threshold`
  from Task 1's `prometheus.strategy.spec`.
- Produces: `random_forest_signal(bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float) -> pl.DataFrame`
  (same return contract as every other `_family_signal` function:
  original columns plus a `position` column). `backtest/engine.py`'s
  `signal_for()`/`_min_bars_for()` dispatch to it for
  `FAMILY_RANDOM_FOREST` — Task 5/6 rely on `signal_for`/`run_backtest`
  already working end-to-end for this family.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_signal.py`:

```python
"""prometheus/backtest/ml_signal.py's random_forest_signal -- the
RANDOM_FOREST family's walk-forward-retrained signal. Real synthetic
price paths, same _bar_row pattern tests/test_null_strategies.py
already establishes."""
from __future__ import annotations

import polars as pl

from prometheus.backtest.engine import run_backtest, signal_for
from prometheus.backtest.ml_signal import random_forest_signal
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec
from tests.test_null_strategies import _bar_row

_SYMBOL = "BTC/USDT"


def _rf_spec(train_window: int = 40, retrain_interval: int = 10, threshold: float = 0.5) -> StrategySpec:
    return StrategySpec(
        family="RANDOM_FOREST", symbol=_SYMBOL, timeframe="1d",
        rf_train_window=train_window, rf_retrain_interval=retrain_interval,
        rf_predict_threshold=threshold, expected_horizon=1,
    )


def _sawtooth_bars(n: int) -> pl.DataFrame:
    """A perfectly alternating up/down series -- f_ret1's own sign is a
    trivially perfect (if trivial) predictor of the next bar's
    direction, giving the model something real to learn without needing
    hundreds of rows."""
    prices = []
    price = 100.0
    for i in range(n):
        price = price + 1.0 if i % 2 == 0 else price - 1.0
        prices.append(price)
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    return pl.DataFrame(rows)


def test_flat_before_first_checkpoint_never_trades() -> None:
    bars = _sawtooth_bars(30)  # shorter than train_window -- no checkpoint reached
    spec = _rf_spec(train_window=40, retrain_interval=10)
    signaled = signal_for(bars, spec)
    assert all(p == 0.0 for p in signaled["position"].to_list())


def test_produces_real_trades_once_trained() -> None:
    bars = _sawtooth_bars(90)
    spec = _rf_spec(train_window=40, retrain_interval=10)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover > 0.0


def test_no_lookahead_planted_future_spike_is_unreachable() -> None:
    """A dip planted only in the LAST bar must not affect any position
    held before that bar -- same convention every other family's signal
    is tested against, now exercised through the walk-forward loop."""
    n = 90
    baseline_prices = []
    price = 100.0
    for i in range(n):
        price = price + 1.0 if i % 2 == 0 else price - 1.0
        baseline_prices.append(price)
    spiked_prices = list(baseline_prices)
    spiked_prices[-1] = 1.0  # extreme dip only on the final bar

    baseline_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(baseline_prices)]
    spiked_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(spiked_prices)]
    baseline_signaled = signal_for(pl.DataFrame(baseline_rows), _rf_spec(train_window=40, retrain_interval=10))
    spiked_signaled = signal_for(pl.DataFrame(spiked_rows), _rf_spec(train_window=40, retrain_interval=10))
    positions_before_plant = spiked_signaled["position"].to_list()[:-1]
    baseline_positions_before_plant = baseline_signaled["position"].to_list()[:-1]
    assert positions_before_plant == baseline_positions_before_plant


def test_engine_dispatches_to_random_forest_signal() -> None:
    bars = _sawtooth_bars(90)
    spec = _rf_spec(train_window=40, retrain_interval=10)
    direct = random_forest_signal(bars, 40, 10, 0.5)["position"].to_list()
    via_engine = signal_for(bars, spec)["position"].to_list()
    assert direct == via_engine


def test_direction_never_predicted_falls_back_to_flat() -> None:
    """A strictly monotonic decline never gives the model a real up
    example to learn from -- model.classes_ never contains 1.0 for any
    checkpoint, and the loop must not crash on that, staying flat
    instead."""
    prices = [100.0 - i for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    signaled = random_forest_signal(bars, 30, 10, 0.5)
    assert all(p == 0.0 for p in signaled["position"].to_list())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_signal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.backtest.ml_signal'`

- [ ] **Step 3: Implement `prometheus/backtest/ml_signal.py`**

```python
"""RANDOM_FOREST family's signal: the one function in this codebase
that is NOT a pure vectorized polars expression -- see
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md for
the full design and the no-look-ahead argument. A random-forest fit is
a real, sequential, greedy algorithm; it cannot be expressed as a
column expression the way every other family's signal can.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestClassifier

from prometheus.backtest.ml_features import FEATURE_COLUMNS, build_feature_frame

_N_ESTIMATORS = 100
_MAX_DEPTH = 4
_MIN_SAMPLES_LEAF = 10
_RANDOM_STATE = 0
_MIN_TRAINING_ROWS = 2 * _MIN_SAMPLES_LEAF


def random_forest_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    """Walk-forward: refit every `retrain_interval` bars on the trailing
    `train_window` bars, predict forward until the next refit. `raw[i]`
    is this bar's own predicted direction (computed from bar i's own
    features, same "uses today's close" convention every other family's
    raw condition uses); the final `position` column applies the SAME
    shift(1) discipline every other family ends with, so today's
    prediction becomes tomorrow's held position, never today's own.

    Flat (position 0.0) for every bar before the first checkpoint, and
    for any checkpoint whose training window has too few labeled rows
    or never saw a real "up" example -- honest "not enough signal here",
    same posture as every other family's rolling-window warm-up nulls
    defaulting to 0.0 via fill_null. n_jobs=1/random_state=0 make every
    fit exactly reproducible (CLAUDE.md's deterministic-core rule)."""
    frame = build_feature_frame(bars)
    n = frame.height
    features = frame.select(FEATURE_COLUMNS).to_numpy()
    labels = frame["label"].to_numpy()

    raw = [0.0] * n
    for checkpoint in range(train_window, n, retrain_interval):
        train_start = checkpoint - train_window
        train_features = features[train_start:checkpoint]
        train_labels = labels[train_start:checkpoint]
        valid = ~np.isnan(train_labels)
        train_features = train_features[valid]
        train_labels = train_labels[valid]
        if train_features.shape[0] < _MIN_TRAINING_ROWS:
            continue

        model = RandomForestClassifier(
            n_estimators=_N_ESTIMATORS,
            max_depth=_MAX_DEPTH,
            min_samples_leaf=_MIN_SAMPLES_LEAF,
            random_state=_RANDOM_STATE,
            n_jobs=1,
        )
        model.fit(train_features, train_labels)
        if 1.0 not in model.classes_:
            continue  # never saw a real "up" example -- stays flat

        predict_end = min(checkpoint + retrain_interval, n)
        predict_features = features[checkpoint:predict_end]
        if predict_features.shape[0] == 0:
            continue
        up_index = list(model.classes_).index(1.0)
        probabilities = model.predict_proba(predict_features)
        for offset, prob_row in enumerate(probabilities):
            raw[checkpoint + offset] = 1.0 if prob_row[up_index] >= predict_threshold else 0.0

    raw_series = pl.Series("_raw_prediction", raw)
    return frame.with_columns(raw_series.shift(1).fill_null(0.0).alias("position"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_signal.py -v`
Expected: FAIL on `test_engine_dispatches_to_random_forest_signal` and
`test_flat_before_first_checkpoint_never_trades`/`test_produces_real_trades_once_trained`
(engine dispatch not wired yet) — the other 3 should already pass.

- [ ] **Step 5: Wire dispatch into `prometheus/backtest/engine.py`**

Modify the import block:

```python
from prometheus.strategy.spec import (
    FAMILY_BOLLINGER,
    FAMILY_MACD,
    FAMILY_MOMENTUM,
    FAMILY_RANDOM_FOREST,
    FAMILY_RSI,
    FAMILY_VOL_BREAKOUT,
    StrategySpec,
)
```

Add right after the existing imports:

```python
from prometheus.backtest.ml_signal import random_forest_signal
```

In `signal_for()`, add right before the final `raise ValueError`:

```python
    if spec.family == FAMILY_RANDOM_FOREST:
        assert (
            spec.rf_train_window is not None
            and spec.rf_retrain_interval is not None
            and spec.rf_predict_threshold is not None
        )
        return random_forest_signal(
            bars, spec.rf_train_window, spec.rf_retrain_interval, spec.rf_predict_threshold
        )
```

In `_min_bars_for()`, add right before the final `raise ValueError`:

```python
    if spec.family == FAMILY_RANDOM_FOREST:
        assert spec.rf_train_window is not None
        return spec.rf_train_window + 30
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_ml_signal.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 7: Run the full non-DB backend suite**

Run: `pytest tests/ -q -m "not db"`
Expected: PASS, no new failures

- [ ] **Step 8: mypy strict**

Run: `mypy prometheus/backtest/ml_signal.py prometheus/backtest/engine.py --strict`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 9: Commit**

```bash
git add prometheus/backtest/ml_signal.py prometheus/backtest/engine.py tests/test_ml_signal.py
git commit -m "feat(backtest): RANDOM_FOREST walk-forward signal + engine dispatch"
```

---

### Task 4: Generator (`prometheus/research/ml/generate.py`)

**Files:**
- Create: `prometheus/research/ml/__init__.py` (empty)
- Create: `prometheus/research/ml/generate.py`
- Test: `tests/test_ml_generate.py`

**Interfaces:**
- Consumes: `FAMILY_RANDOM_FOREST`, `StrategySpec` from Task 1.
- Produces: `generate_random_forest_grid(symbol: str, timeframe: str) -> list[StrategySpec]`
  — Task 5's ablation and Task 6's worker wiring both call this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_generate.py`:

```python
from __future__ import annotations

from prometheus.research.generate import generate_baseline_grid
from prometheus.research.ml.generate import generate_random_forest_grid
from prometheus.strategy.spec import FAMILY_RANDOM_FOREST


def test_generate_random_forest_grid_produces_real_specs() -> None:
    specs = generate_random_forest_grid("BTC/USDT", "1d")
    assert len(specs) == 8
    assert all(spec.family == FAMILY_RANDOM_FOREST for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)
    assert all(spec.rf_retrain_interval <= spec.rf_train_window for spec in specs)  # type: ignore[operator]


def test_every_spec_uses_the_requested_symbol_and_timeframe() -> None:
    specs = generate_random_forest_grid("ETH/USDT", "4h")
    assert all(spec.symbol == "ETH/USDT" and spec.timeframe == "4h" for spec in specs)


def test_is_deterministic() -> None:
    first = generate_random_forest_grid("BTC/USDT", "1d")
    second = generate_random_forest_grid("BTC/USDT", "1d")
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_generate_random_forest_grid_not_in_baseline_grid() -> None:
    baseline_families = {spec.family for spec in generate_baseline_grid("BTC/USDT", "1d")}
    assert FAMILY_RANDOM_FOREST not in baseline_families
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.research.ml'`

- [ ] **Step 3: Implement the package and generator**

Create `prometheus/research/ml/__init__.py` (empty file — a plain
package marker, no content).

Create `prometheus/research/ml/generate.py`:

```python
"""RANDOM_FOREST's own generator -- deliberately NOT folded into
research/generate.py's generate_baseline_grid: RANDOM_FOREST is a new
generation component to be measured against that baseline
(experiments/ablation.register_ml_component), not a sixth member of
it. See docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md.
"""
from __future__ import annotations

from prometheus.strategy.spec import FAMILY_RANDOM_FOREST, StrategySpec

# 2x2x2 = 8 specs per symbol -- roughly the same order of magnitude as
# BOLLINGER's own 3x3=9, not an open-ended search.
_TRAIN_WINDOWS = (120, 250)  # ~6mo / ~1yr of daily bars
_RETRAIN_INTERVALS = (20, 40)  # ~1mo / ~2mo
_PREDICT_THRESHOLDS = (0.5, 0.55)


def generate_random_forest_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for train_window in _TRAIN_WINDOWS:
        for retrain_interval in _RETRAIN_INTERVALS:
            for threshold in _PREDICT_THRESHOLDS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_RANDOM_FOREST,
                        symbol=symbol,
                        timeframe=timeframe,
                        rf_train_window=train_window,
                        rf_retrain_interval=retrain_interval,
                        rf_predict_threshold=threshold,
                        # The model's actual, honest claim: predicts one
                        # bar ahead, regardless of train_window/retrain
                        # cadence.
                        expected_horizon=1,
                    )
                )
    return specs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_generate.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: mypy strict**

Run: `mypy prometheus/research/ml/generate.py --strict`
Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add prometheus/research/ml/__init__.py prometheus/research/ml/generate.py tests/test_ml_generate.py
git commit -m "feat(research): RANDOM_FOREST grid generator"
```

---

### Task 5: Ablation (`experiments/ablation.register_ml_component`)

**Files:**
- Modify: `prometheus/experiments/ablation.py`
- Test: `tests/test_ablation_ml_component.py`

**Interfaces:**
- Consumes: `generate_random_forest_grid` (Task 4),
  `generate_baseline_grid` (already imported in `ablation.py` for
  `register_evolution_component`), `run_backtest`/`apply_cost`/
  `CostModel`/`load_point_in_time`/`derive_seed`/`record_trial`/
  `_recompute_registry` (all already used by
  `register_evolution_component` in this same file).
- Produces: `register_ml_component(session, *, symbols, timeframe, start, end, version, cost_model=apply_cost) -> BatchResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ablation_ml_component.py`:

```python
"""tests/test_ablation_ml_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.ablation import register_ml_component

pytestmark = pytest.mark.db


async def test_register_ml_component_produces_a_real_verdict(db_session: AsyncSession) -> None:
    result = await register_ml_component(
        db_session,
        symbols=["BTC/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.component == "random_forest"
    assert result.verdict in {"UNPROVEN", "VALUABLE", "NEUTRAL", "HARMFUL"}


async def test_register_ml_component_with_no_bars_is_unproven(db_session: AsyncSession) -> None:
    result = await register_ml_component(
        db_session,
        symbols=["NOSUCH/PAIR"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.verdict == "UNPROVEN"
    assert result.n_experiments == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ablation_ml_component.py -v`
Expected: FAIL with `ImportError: cannot import name 'register_ml_component'`

- [ ] **Step 3: Add the import and function to `prometheus/experiments/ablation.py`**

Add to the imports (alongside the existing `research.generate`/
`research.templates` imports near the top of the file):

```python
from prometheus.research.ml.generate import generate_random_forest_grid
```

Add the function, right after `register_evolution_component` (before
the `_SELECT_LLM_SPECS_FOR_SYMBOL`/`register_llm_component` block):

```python
async def register_ml_component(
    session: AsyncSession,
    *,
    symbols: list[str],
    timeframe: str,
    start: datetime,
    end: datetime,
    version: str,
    cost_model: CostModel = apply_cost,
) -> BatchResult:
    """Does the RANDOM_FOREST walk-forward model
    (research/ml/generate.py) find anything the deterministic baseline
    grid (research/generate.generate_baseline_grid) doesn't, on real
    out-of-sample data. Same shape as register_evolution_component/
    register_llm_component: per symbol, score every baseline-grid spec
    and every RF-grid spec with the real backtest engine, record one
    paired trial (enabled = best RF score, disabled = best grid score)
    via record_trial, then reuse _recompute_registry for the real
    verdict -- reported honestly, including a NEUTRAL or HARMFUL one."""
    component = "random_forest"
    n_trials = 0
    n_failed = 0

    def _score(pit: PointInTimeFrame, spec: StrategySpec) -> float | None:
        try:
            return run_backtest(pit, spec, end, cost_model=cost_model).total_return_pct
        except ValueError:
            return None

    for symbol in symbols:
        pit, _data_version_hash = await load_point_in_time(
            session, [symbol], timeframe, start, end
        )
        grid_scores = [
            score
            for spec in generate_baseline_grid(symbol, timeframe)
            if (score := _score(pit, spec)) is not None
        ]
        rf_scored = [
            (spec, score)
            for spec in generate_random_forest_grid(symbol, timeframe)
            if (score := _score(pit, spec)) is not None
        ]
        if not grid_scores or not rf_scored:
            n_failed += 1
            continue
        best_grid_score = max(grid_scores)
        best_rf_spec, best_rf_score = max(rf_scored, key=lambda pair: pair[1])

        await record_trial(
            session,
            component=component,
            version=version,
            symbol=symbol,
            config_hash=best_rf_spec.config_hash(),
            seed=derive_seed(component, version, symbol),
            enabled_return_pct=best_rf_score,
            disabled_return_pct=best_grid_score,
        )
        n_trials += 1

    result = await _recompute_registry(
        session,
        component,
        version,
        ["RANDOM_FOREST"],
        n_trials_this_batch=n_trials,
        n_failed_this_batch=n_failed,
    )
    await session.commit()
    return result
```

(`PointInTimeFrame`, `StrategySpec`, `CostModel`, `apply_cost`,
`run_backtest`, `load_point_in_time`, `derive_seed`, `record_trial`,
`_recompute_registry`, `BatchResult`, `AsyncSession`, `datetime` are all
already imported in this file for `register_evolution_component` — do
not re-import anything already present.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ablation_ml_component.py -v`
Expected: PASS if `TEST_DATABASE_URL` is set, SKIPPED otherwise (same
posture as every other `pytest.mark.db` test in this suite)

- [ ] **Step 5: Run the full non-DB backend suite**

Run: `pytest tests/ -q -m "not db"`
Expected: PASS, no new failures

- [ ] **Step 6: mypy strict**

Run: `mypy prometheus/experiments/ablation.py --strict`
Expected: `Success: no issues found in 1 source file`

- [ ] **Step 7: Commit**

```bash
git add prometheus/experiments/ablation.py tests/test_ablation_ml_component.py
git commit -m "feat(ablation): register_ml_component for RANDOM_FOREST"
```

---

### Task 6: Fix `enqueue_grid`/`validate_grid` family-scoping + wire RF into `worker.py`

**Files:**
- Modify: `prometheus/experiments/runner.py`
- Modify: `prometheus/worker.py`
- Test: `tests/test_queue_semantics.py`
- Test: `tests/test_runner_family_scoping.py` (new)

**Interfaces:**
- Consumes: `generate_random_forest_grid` (Task 4); `generate_baseline_grid`
  (already exists in `research/generate.py`, already imported by
  `research/templates.py`/`experiments/ablation.py` — not yet imported
  in `experiments/runner.py`, add it).
- Produces: `enqueue_specs(symbol, timeframe, specs, days, *, priority, expected_information_value, estimated_cost, max_attempts) -> list[str]`,
  `enqueue_baseline_grid(symbol, timeframe, days, *, priority, expected_information_value, estimated_cost, max_attempts) -> list[str]`,
  `validate_specs(session, symbol, timeframe, specs, days) -> list[str]`,
  `validate_baseline_grid(session, symbol, timeframe, days) -> list[str]`.
  `enqueue_grid`/`validate_grid` keep their exact existing signatures and
  behavior (thin wrappers now).

- [ ] **Step 1: Write the failing regression tests**

Create `tests/test_runner_family_scoping.py`:

```python
"""Regression test for the bug documented in
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md:
enqueue_grid/validate_grid were hardcoded to a single family in
production (worker.py's _run_research() always passed family="MOMENTUM"),
so no other strategy family could ever be enqueued or reach 'VALIDATED'
status. enqueue_baseline_grid/validate_baseline_grid must source their
specs from generate_baseline_grid (every classic-template family), not
the MOMENTUM-only generate_grid.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from prometheus.experiments.runner import enqueue_baseline_grid, validate_baseline_grid


async def test_enqueue_baseline_grid_calls_generate_baseline_grid() -> None:
    with (
        patch(
            "prometheus.experiments.runner.generate_baseline_grid", return_value=[]
        ) as mock_generate,
        patch(
            "prometheus.experiments.runner.enqueue_specs", new=AsyncMock(return_value=[])
        ) as mock_enqueue_specs,
    ):
        await enqueue_baseline_grid(
            "BTC/USDT", "1d", 800,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )
    mock_generate.assert_called_once_with("BTC/USDT", "1d")
    mock_enqueue_specs.assert_called_once()


async def test_validate_baseline_grid_calls_generate_baseline_grid() -> None:
    with (
        patch(
            "prometheus.experiments.runner.generate_baseline_grid", return_value=[]
        ) as mock_generate,
        patch(
            "prometheus.experiments.runner.validate_specs", new=AsyncMock(return_value=[])
        ) as mock_validate_specs,
    ):
        await validate_baseline_grid(AsyncMock(), "BTC/USDT", "1d", 800)
    mock_generate.assert_called_once_with("BTC/USDT", "1d")
    mock_validate_specs.assert_called_once()


@pytest.mark.db
async def test_enqueue_specs_enqueues_a_non_momentum_spec() -> None:
    from prometheus.experiments.runner import enqueue_specs
    from prometheus.strategy.spec import StrategySpec

    spec = StrategySpec(
        family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
        lookback_window=20, band_multiplier=2.0, expected_horizon=20,
    )
    job_ids = await enqueue_specs(
        "BTC/USDT", "1d", [spec], 800,
        priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
    )
    assert len(job_ids) == 1
```

(This file's `db`-marked test needs `TEST_DATABASE_URL` set the same way
every other `pytest.mark.db` test in this suite does — it calls
`enqueue_specs`, which opens its own session via `get_session()`
internally, same as `enqueue_grid` already does today.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner_family_scoping.py -v`
Expected: FAIL with `ImportError: cannot import name 'enqueue_baseline_grid'`

- [ ] **Step 3: Refactor `enqueue_grid` in `prometheus/experiments/runner.py`**

Add `generate_baseline_grid` to the existing import line:

```python
from prometheus.research.generate import generate_baseline_grid, generate_grid
```

Replace the entire existing `enqueue_grid` function (currently at
`prometheus/experiments/runner.py:535-574`) with:

```python
async def enqueue_specs(
    symbol: str,
    timeframe: str,
    specs: list[StrategySpec],
    days: int,
    *,
    priority: int,
    expected_information_value: float,
    estimated_cost: float,
    max_attempts: int,
) -> list[str]:
    """Enqueues one job per given StrategySpec. idempotency_key =
    sha256(kind, spec.config_hash(), days) -- re-running this for an
    unchanged spec list re-enqueues nothing (queue.enqueue's ON CONFLICT
    DO NOTHING), rather than duplicating work already queued or already
    run. The real body enqueue_grid/enqueue_baseline_grid both wrap."""
    job_ids = []
    async with get_session() as session:
        for spec in specs:
            idempotency_key = hashlib.sha256(
                f"{_RUN_BACKTEST_KIND}|{spec.config_hash()}|{days}".encode()
            ).hexdigest()
            job_ids.append(
                await enqueue(
                    session,
                    kind=_RUN_BACKTEST_KIND,
                    payload={"spec": spec.model_dump(), "days": days},
                    idempotency_key=idempotency_key,
                    priority=priority,
                    expected_information_value=expected_information_value,
                    estimated_cost=estimated_cost,
                    max_attempts=max_attempts,
                    agent_role="engineer",
                    current_stage="forge",
                    next_stage="arena",
                )
            )
        await session.commit()
    return job_ids


async def enqueue_grid(
    symbol: str, timeframe: str, family: str, days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Enqueues one job per StrategySpec in `family`'s own deterministic
    grid. Unchanged signature/behavior -- now a thin wrapper over
    enqueue_specs so every existing caller keeps working exactly as
    before."""
    return await enqueue_specs(
        symbol, timeframe, generate_grid(symbol, timeframe, family), days,
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )


async def enqueue_baseline_grid(
    symbol: str, timeframe: str, days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Every classic-template family's grid
    (research.generate.generate_baseline_grid), not just MOMENTUM -- the
    fix for the bug documented in
    docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md:
    worker.py's _run_research() called enqueue_grid with a hardcoded
    family, so BOLLINGER/VOL_BREAKOUT/RSI/MACD strategies were never
    enqueued through this path at all."""
    return await enqueue_specs(
        symbol, timeframe, generate_baseline_grid(symbol, timeframe), days,
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )
```

- [ ] **Step 4: Refactor `validate_grid` in `prometheus/experiments/runner.py`**

Find the existing `validate_grid` function signature and its first two
body lines:

```python
async def validate_grid(
    session: AsyncSession, symbol: str, timeframe: str, family: str, days: int
) -> list[str]:
```

...

```python
    Returns the list of experiment_ids that received a fresh verdict.
    """
    specs = generate_grid(symbol, timeframe, family)
    end = datetime.now(UTC)
```

Change the signature and delete the `specs = generate_grid(...)` line,
renaming the function to `validate_specs` and taking `specs` as a
parameter instead of `family`:

```python
async def validate_specs(
    session: AsyncSession, symbol: str, timeframe: str, specs: list[StrategySpec], days: int
) -> list[str]:
```

...

```python
    Returns the list of experiment_ids that received a fresh verdict.
    """
    end = datetime.now(UTC)
```

Leave every other line of the function body (from `end = datetime.now(UTC)`
through the final `return experiment_ids`) exactly as it is today — this
is a rename plus a parameter-source change, not a logic change.

Immediately after the (now-renamed) function's closing `return experiment_ids`
line and before `async def _validate_one_spec`, add:

```python
async def validate_grid(
    session: AsyncSession, symbol: str, timeframe: str, family: str, days: int
) -> list[str]:
    """Re-evaluates `family`'s own deterministic grid against real PBO/
    Deflated Sharpe/decay/regime evidence. Unchanged signature/behavior
    -- now a thin wrapper over validate_specs; see validate_specs' own
    docstring for the full re-scoring behavior."""
    return await validate_specs(
        session, symbol, timeframe, generate_grid(symbol, timeframe, family), days
    )


async def validate_baseline_grid(
    session: AsyncSession, symbol: str, timeframe: str, days: int
) -> list[str]:
    """Every classic-template family, not just MOMENTUM -- the
    Oracle-side fix paired with enqueue_baseline_grid above.
    validate_grid's hardcoded family meant no non-MOMENTUM strategy
    could ever reach 'VALIDATED' status
    (population.verdict_to_status's only PROMOTE->VALIDATED path), and
    therefore never CHAMPION, and therefore never paper-traded."""
    return await validate_specs(
        session, symbol, timeframe, generate_baseline_grid(symbol, timeframe), days
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_runner_family_scoping.py -v`
Expected: PASS (`test_enqueue_specs_enqueues_a_non_momentum_spec` PASSES
if `TEST_DATABASE_URL` is set, SKIPS otherwise; the other 2 always PASS)

- [ ] **Step 6: Rewire `prometheus/worker.py`**

Change the import block:

```python
from prometheus.experiments.runner import (
    drain_queue,
    enqueue_baseline_grid,
    enqueue_specs,
    latest_experiment_id_for_spec,
    validate_baseline_grid,
    validate_specs,
)
```

Add a new import:

```python
from prometheus.research.ml.generate import generate_random_forest_grid
```

Remove the now-unused `_FAMILY = "MOMENTUM"` constant (line 127).

Replace `_run_research()`'s current top of function (the `for symbol in
symbols:` enqueue loop through `ran = await drain_queue()`, and the
`validated` loop right after it) with:

```python
async def _run_research() -> list[str]:
    symbols = load_universe_symbols()
    for symbol in symbols:
        await enqueue_baseline_grid(
            symbol, _TIMEFRAME, _GRID_LOOKBACK_DAYS,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )
        await enqueue_specs(
            symbol, _TIMEFRAME, generate_random_forest_grid(symbol, _TIMEFRAME),
            _GRID_LOOKBACK_DAYS,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )

    ran = await drain_queue()

    # The Oracle (PROMPTS.md PROMPT 5): re-scores every symbol's grid
    # against real PBO/DSR/decay/regime evidence and writes
    # validation_results. Every classic-template family AND
    # RANDOM_FOREST, not just MOMENTUM -- see
    # docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md.
    validated: list[str] = []
    async with get_session() as session:
        for symbol in symbols:
            validated.extend(
                await validate_baseline_grid(session, symbol, _TIMEFRAME, _GRID_LOOKBACK_DAYS)
            )
            validated.extend(
                await validate_specs(
                    session, symbol, _TIMEFRAME,
                    generate_random_forest_grid(symbol, _TIMEFRAME), _GRID_LOOKBACK_DAYS,
                )
            )
```

Leave everything from the `# PROMPT 7: one bounded evolution step...`
comment onward (the `async with get_session() as session: evolved_job_ids = ...`
block through the function's final `return ran + validated`) exactly as
it is today.

- [ ] **Step 7: Run the full non-DB backend suite**

Run: `pytest tests/ -q -m "not db"`
Expected: PASS, no new failures — pay particular attention to any test
that imports `prometheus.worker` (a removed `_FAMILY` reference or a
stale `enqueue_grid`/`validate_grid` import would surface as an
`ImportError`/`AttributeError` here).

- [ ] **Step 8: mypy strict**

Run: `mypy prometheus/experiments/runner.py prometheus/worker.py --strict`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 9: Commit**

```bash
git add prometheus/experiments/runner.py prometheus/worker.py tests/test_runner_family_scoping.py
git commit -m "fix(worker): enqueue/validate every strategy family, not just MOMENTUM"
```

---

## Final Verification

After all 6 tasks:

```bash
pytest tests/ -q -m "not db"
mypy prometheus/ --strict
```

Both must be clean. Then deploy (both `Project_Prometheus` and
`prometheus-worker` Railway services need the new code — the worker runs
`_run_research()`, the API service resolves `family`/`asset_class` for
the dashboard) following this session's established pattern: set
`GIT_SHA` on both services, `railway up --service <name> --detach` on
both, poll for `RUNNING`, curl-verify `/strategies/`.

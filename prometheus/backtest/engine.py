"""Deterministic, point-in-time-correct backtest for one StrategySpec
against one symbol.

No Sharpe, no PBO, no Deflated Sharpe here -- that is the Oracle's job
(validation/, PROMPT 5) and consumes THIS module's output (the equity
curve, and signal_for()'s raw position series) rather than computing
those stats inline; CLAUDE.md's "do not reimplement PBO/DSR from scratch"
is a reason to keep them out of the hot backtest loop, not a reason they
can never exist. This produces total return, max drawdown, and turnover.

No look-ahead, two layers deep: `PointInTimeFrame.as_of(cutoff)` already
excludes any bar not yet knowable by `cutoff` (Law 1's own mechanism,
unchanged). On top of that, the SMA crossover signal for bar i is computed
from bars strictly BEFORE i (`shift(1)`) -- bar i's own close never
influences bar i's own position. Both are exercised by
tests/test_backtest_no_lookahead.py.

vs_benchmark (PROMPT 3) is computed INSIDE run_backtest, not left for a
caller to attach afterward -- Law 8's "every result is compared against
buy-and-hold" is then a true invariant of BacktestResult's shape, not
something that happens to be true because runner.py currently remembers
to call compute_benchmark_curve too. A caller that already computed the
benchmark (runner.py does, to also record it for the world view) can pass
it in via `benchmark_result` to avoid computing it twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from prometheus.backtest.benchmark import (
    BenchmarkResult,
    VsBenchmark,
    compute_benchmark_curve,
    compute_vs_benchmark,
)
from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.backtest.ml_signal import random_forest_signal
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import (
    FAMILY_BOLLINGER,
    FAMILY_MACD,
    FAMILY_MOMENTUM,
    FAMILY_RANDOM_FOREST,
    FAMILY_RSI,
    FAMILY_VOL_BREAKOUT,
    StrategySpec,
)

STARTING_CAPITAL = 1000.0


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: tuple[tuple[str, float], ...]  # (available_at.isoformat(), equity)
    total_return_pct: float
    max_drawdown_pct: float
    turnover: float
    # gross_return_pct: the same curve with apply_cost() never subtracted.
    # total_costs: the currency sum apply_cost() actually charged. Together
    # they are what experiments.failure's TRANSACTION_COST_FAILURE checks
    # -- gross positive, net negative -- which total_return_pct alone
    # cannot distinguish from a strategy that was never profitable.
    gross_return_pct: float
    total_costs: float
    vs_benchmark: VsBenchmark


def _sma_signal(bars: pl.DataFrame, fast: int, slow: int) -> pl.DataFrame:
    """1.0 = long, 0.0 = flat. `shift(1)`: the position held DURING bar i
    is decided from bars up to and including i-1, never i itself."""
    return bars.with_columns(
        pl.col("close").rolling_mean(fast).alias("_fast"),
        pl.col("close").rolling_mean(slow).alias("_slow"),
    ).with_columns(
        (pl.col("_fast") > pl.col("_slow"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def _bollinger_signal(bars: pl.DataFrame, lookback: int, band_multiplier: float) -> pl.DataFrame:
    """Classic Bollinger mean-reversion (John Bollinger's own
    construction): long whenever close is below the lower band (mean -
    band_multiplier*std), flat otherwise -- stateless, same shape
    _sma_signal already is (the condition itself IS the position, not a
    separate enter/hold/exit state machine). Same `shift(1)` discipline:
    the raw condition is computed with the current bar's own close
    (matching _sma_signal exactly), then the WHOLE condition is shifted
    by one bar before it ever becomes an execution position."""
    return bars.with_columns(
        pl.col("close").rolling_mean(lookback).alias("_mid"),
        pl.col("close").rolling_std(lookback).alias("_std"),
    ).with_columns(
        (pl.col("_mid") - band_multiplier * pl.col("_std")).alias("_lower")
    ).with_columns(
        (pl.col("close") < pl.col("_lower"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def _vol_breakout_signal(
    bars: pl.DataFrame, breakout_window: int, exit_window: int
) -> pl.DataFrame:
    """Donchian-channel breakout, the Turtle Trading convention: enter
    long on a close ABOVE the breakout_window-bar rolling high, exit on
    a close BELOW the shorter exit_window-bar rolling low, otherwise
    PERSIST the previous position (a breakout, unlike crossover/mean-
    reversion, is a state you stay in, not a condition re-evaluated
    fresh every bar). Expressed vectorized via forward_fill() over a
    column that's 1.0/0.0 only on an actual entry/exit bar and null
    otherwise, not an imperative per-bar loop.

    The entry/exit LEVELS are computed with `.shift(1)` BEFORE the
    rolling max/min -- i.e. from the breakout_window/exit_window bars
    strictly BEFORE today, excluding today's own high/low. This is not
    an extra look-ahead guard on top of an otherwise-fine formula, it is
    what "breakout" means: a rolling max that includes today's own high
    can never be exceeded by today's own close (today's high is, by
    construction, part of the maximum being compared against), so a
    same-bar-inclusive version can mathematically never detect a fresh
    high and, on flat/constant price data, compares close to itself
    every bar and fires a spurious signal on every bar past the warm-up
    -- a real bug caught by two failing tests
    (tests/test_strategy_families.py), not something anticipated in
    advance. On TOP of that level-exclusion, the final resulting
    position series still gets the same overall `.shift(1)` discipline
    _sma_signal/_bollinger_signal use: today's close decides whether a
    breakout/breakdown HAPPENED today, but that decision is only ever
    acted on as tomorrow's position, never today's own."""
    return (
        bars.with_columns(
            pl.col("high").shift(1).rolling_max(breakout_window).alias("_entry_level"),
            pl.col("low").shift(1).rolling_min(exit_window).alias("_exit_level"),
        )
        .with_columns(
            pl.when(pl.col("close") > pl.col("_entry_level"))
            .then(1.0)
            .when(pl.col("close") < pl.col("_exit_level"))
            .then(0.0)
            .otherwise(None)
            .alias("_raw_signal")
        )
        .with_columns(
            pl.col("_raw_signal")
            .forward_fill()
            .fill_null(0.0)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def _rsi_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Wilder's own RSI: average gain/loss smoothed with Wilder's
    alpha=1/lookback recursive EMA (the standard practical
    implementation -- pandas/ta-lib's own convention for "RSI", not a
    plain SMA-of-gains approximation). Long whenever RSI drops below
    the oversold threshold, flat otherwise -- a fresh condition
    re-evaluated every bar, same stateless shape as _bollinger_signal,
    not a stateful entry/exit like _vol_breakout_signal. Same
    `shift(1)` discipline: the raw condition uses today's own close,
    then the whole condition is shifted one bar before it becomes an
    execution position.

    A flat, never-moving price series makes avg_gain and avg_loss both
    0.0, so RSI is 0/0 == NaN in polars -- `NaN < oversold` is false,
    giving position 0.0 for every bar, the same "never trades on flat
    prices" behavior every other family's null case exercises."""
    delta = pl.col("close").diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    alpha = 1.0 / lookback
    return (
        bars.with_columns(gain.alias("_gain"), loss.alias("_loss"))
        .with_columns(
            pl.col("_gain").ewm_mean(alpha=alpha, adjust=False).alias("_avg_gain"),
            pl.col("_loss").ewm_mean(alpha=alpha, adjust=False).alias("_avg_loss"),
        )
        .with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss"))).alias("_rsi")
        )
        .with_columns(
            (pl.col("_rsi") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def _macd_signal(bars: pl.DataFrame, fast: int, slow: int, signal: int) -> pl.DataFrame:
    """Gerald Appel's own construction: MACD line = EMA(fast) -
    EMA(slow), signal line = EMA(MACD line, signal). Long whenever the
    MACD line is above its own signal line, flat otherwise -- a fresh
    condition re-evaluated every bar, same stateless shape as
    _sma_signal (this is the EMA analogue of that same crossover idea).
    `adjust=False` on every ewm_mean matches the standard recursive EMA
    definition trading platforms use, not polars' default weighted
    average, which does not equal it early in a series. Same
    `shift(1)` discipline as every other family here."""
    return (
        bars.with_columns(
            pl.col("close").ewm_mean(span=fast, adjust=False).alias("_ema_fast"),
            pl.col("close").ewm_mean(span=slow, adjust=False).alias("_ema_slow"),
        )
        .with_columns((pl.col("_ema_fast") - pl.col("_ema_slow")).alias("_macd"))
        .with_columns(pl.col("_macd").ewm_mean(span=signal, adjust=False).alias("_signal_line"))
        .with_columns(
            (pl.col("_macd") > pl.col("_signal_line"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def signal_for(bars: pl.DataFrame, spec: StrategySpec) -> pl.DataFrame:
    """Public seam validation/metrics.py's information-coefficient
    calculation needs: IC is a property of the SIGNAL (does it predict
    forward returns), not of an executed, cost-bearing backtest, so it
    reads the `position` column directly rather than differencing
    BacktestResult's equity curve. Dispatches on spec.family."""
    if spec.family == FAMILY_MOMENTUM:
        assert spec.fast_window is not None and spec.slow_window is not None
        return _sma_signal(bars, spec.fast_window, spec.slow_window)
    if spec.family == FAMILY_BOLLINGER:
        assert spec.lookback_window is not None and spec.band_multiplier is not None
        return _bollinger_signal(bars, spec.lookback_window, spec.band_multiplier)
    if spec.family == FAMILY_VOL_BREAKOUT:
        assert spec.breakout_window is not None and spec.exit_window is not None
        return _vol_breakout_signal(bars, spec.breakout_window, spec.exit_window)
    if spec.family == FAMILY_RSI:
        assert spec.rsi_lookback is not None and spec.rsi_oversold is not None
        return _rsi_signal(bars, spec.rsi_lookback, spec.rsi_oversold)
    if spec.family == FAMILY_MACD:
        assert (
            spec.macd_fast is not None
            and spec.macd_slow is not None
            and spec.macd_signal is not None
        )
        return _macd_signal(bars, spec.macd_fast, spec.macd_slow, spec.macd_signal)
    if spec.family == FAMILY_RANDOM_FOREST:
        assert (
            spec.rf_train_window is not None
            and spec.rf_retrain_interval is not None
            and spec.rf_predict_threshold is not None
        )
        return random_forest_signal(
            bars, spec.rf_train_window, spec.rf_retrain_interval, spec.rf_predict_threshold
        )
    raise ValueError(f"no signal generator for family {spec.family!r}")


def _min_bars_for(spec: StrategySpec) -> int:
    """The warm-up a spec's own rolling window needs before its signal is
    meaningful, generalized across families -- the same `+2` headroom
    run_backtest already used for MOMENTUM's slow_window (one extra bar
    for the rolling computation's own first non-null value, one more for
    the position `.diff()` in run_backtest's accounting loop)."""
    if spec.family == FAMILY_MOMENTUM:
        assert spec.slow_window is not None
        return spec.slow_window + 2
    if spec.family == FAMILY_BOLLINGER:
        assert spec.lookback_window is not None
        return spec.lookback_window + 2
    if spec.family == FAMILY_VOL_BREAKOUT:
        assert spec.breakout_window is not None
        return spec.breakout_window + 2
    if spec.family == FAMILY_RSI:
        assert spec.rsi_lookback is not None
        return spec.rsi_lookback + 2
    if spec.family == FAMILY_MACD:
        assert spec.macd_slow is not None and spec.macd_signal is not None
        return spec.macd_slow + spec.macd_signal + 2
    if spec.family == FAMILY_RANDOM_FOREST:
        assert spec.rf_train_window is not None
        return spec.rf_train_window + 30
    raise ValueError(f"no minimum-bars rule for family {spec.family!r}")


@dataclass(frozen=True)
class _RawBacktest:
    """The accounting loop's own output, before vs_benchmark is attached
    -- run_backtest and run_backtest_from_positions both produce one of
    these and then attach vs_benchmark identically, so that attachment
    can't drift between the two callers."""

    equity_curve: tuple[tuple[str, float], ...]
    total_return_pct: float
    max_drawdown_pct: float
    turnover: float
    gross_return_pct: float
    total_costs: float


def _run_accounting(
    bars: pl.DataFrame, positions: list[float], cost_model: CostModel
) -> _RawBacktest:
    """The actual bar-by-bar equity accounting -- position * bar return,
    cost charged on position CHANGE only, gross vs net tracked in
    parallel. Shared by run_backtest (signal-driven positions) and
    run_backtest_from_positions (caller-supplied positions, e.g.
    experiments/ablation.py's perturbed arms and the null-strategy test
    suite) so there is exactly one copy of this math, not three."""
    signaled = bars.with_columns(pl.Series("position", positions)).with_columns(
        pl.col("close").pct_change().fill_null(0.0).alias("_bar_return"),
        pl.col("position").diff().fill_null(pl.col("position")).abs().alias("_position_change"),
    )

    equity = STARTING_CAPITAL
    gross_equity = STARTING_CAPITAL
    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    turnover = 0.0
    total_costs = 0.0
    curve: list[tuple[str, float]] = []

    for row in signaled.iter_rows(named=True):
        position_change = row["_position_change"] or 0.0
        if position_change:
            cost = cost_model(equity * position_change)
            equity -= cost
            total_costs += cost
            turnover += position_change
        equity *= 1 + row["position"] * row["_bar_return"]
        gross_equity *= 1 + row["position"] * row["_bar_return"]
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        curve.append((row["available_at"].isoformat(), equity))

    equity_curve = tuple(curve)
    return _RawBacktest(
        equity_curve=equity_curve,
        total_return_pct=(equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100,
        max_drawdown_pct=max_drawdown * 100,
        turnover=turnover,
        gross_return_pct=(gross_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100,
        total_costs=total_costs,
    )


def run_backtest_from_positions(
    pit: PointInTimeFrame,
    symbol: str,
    positions: list[float],
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    """Same accounting and vs_benchmark treatment as run_backtest, but
    for a caller-supplied position series instead of one derived from
    signal_for() -- experiments/ablation.py's enabled/disabled arms are
    both position series, not both real StrategySpecs with a signal
    generator. `positions` must have exactly one entry per row of
    `pit.as_of(as_of_cutoff)` filtered to `symbol`, in that same sorted
    order -- the caller's responsibility, same as signal_for()'s own
    output shape.
    """
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == symbol).sort("available_at")
    if bars.height != len(positions):
        raise ValueError(
            f"positions length {len(positions)} does not match {bars.height} bars for {symbol}"
        )
    raw = _run_accounting(bars, positions, cost_model)
    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, [symbol], as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(raw.equity_curve, raw.max_drawdown_pct, benchmark_result)
    return BacktestResult(
        equity_curve=raw.equity_curve,
        total_return_pct=raw.total_return_pct,
        max_drawdown_pct=raw.max_drawdown_pct,
        turnover=raw.turnover,
        gross_return_pct=raw.gross_return_pct,
        total_costs=raw.total_costs,
        vs_benchmark=vs_benchmark,
    )


def run_backtest(
    pit: PointInTimeFrame,
    spec: StrategySpec,
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == spec.symbol).sort("available_at")
    min_bars = _min_bars_for(spec)
    if bars.height < min_bars:
        raise ValueError(
            f"not enough bars for {spec.symbol} as of {as_of_cutoff}: "
            f"need >= {min_bars}, have {bars.height}"
        )

    signaled = signal_for(bars, spec)
    raw = _run_accounting(bars, signaled["position"].to_list(), cost_model)

    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, [spec.symbol], as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(raw.equity_curve, raw.max_drawdown_pct, benchmark_result)

    return BacktestResult(
        equity_curve=raw.equity_curve,
        total_return_pct=raw.total_return_pct,
        max_drawdown_pct=raw.max_drawdown_pct,
        turnover=raw.turnover,
        gross_return_pct=raw.gross_return_pct,
        total_costs=raw.total_costs,
        vs_benchmark=vs_benchmark,
    )

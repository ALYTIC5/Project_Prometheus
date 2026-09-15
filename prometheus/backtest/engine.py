"""Deterministic, point-in-time-correct backtest for one StrategySpec
against one symbol.

No Sharpe, no PBO, no Deflated Sharpe here -- that is the Oracle's job
(Prompt 5) and needs cpz-quant, which is not installed (CLAUDE.md: do not
reimplement PBO/DSR from scratch). This produces total return, max
drawdown, and turnover only.

No look-ahead, two layers deep: `PointInTimeFrame.as_of(cutoff)` already
excludes any bar not yet knowable by `cutoff` (Law 1's own mechanism,
unchanged). On top of that, the SMA crossover signal for bar i is computed
from bars strictly BEFORE i (`shift(1)`) -- bar i's own close never
influences bar i's own position. Both are exercised by
tests/test_backtest_no_lookahead.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from prometheus.backtest.costs import apply_cost
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

STARTING_CAPITAL = 1000.0


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: tuple[tuple[str, float], ...]  # (available_at.isoformat(), equity)
    total_return_pct: float
    max_drawdown_pct: float
    turnover: float


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


def run_backtest(
    pit: PointInTimeFrame, spec: StrategySpec, as_of_cutoff: datetime
) -> BacktestResult:
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == spec.symbol).sort("available_at")
    min_bars = spec.slow_window + 2
    if bars.height < min_bars:
        raise ValueError(
            f"not enough bars for {spec.symbol} as of {as_of_cutoff}: "
            f"need >= {min_bars}, have {bars.height}"
        )

    signaled = _sma_signal(bars, spec.fast_window, spec.slow_window).with_columns(
        pl.col("close").pct_change().fill_null(0.0).alias("_bar_return"),
        pl.col("position").diff().fill_null(pl.col("position")).abs().alias("_position_change"),
    )

    equity = STARTING_CAPITAL
    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    turnover = 0.0
    curve: list[tuple[str, float]] = []

    for row in signaled.iter_rows(named=True):
        position_change = row["_position_change"] or 0.0
        if position_change:
            equity -= apply_cost(equity * position_change)
            turnover += position_change
        equity *= 1 + row["position"] * row["_bar_return"]
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        curve.append((row["available_at"].isoformat(), equity))

    return BacktestResult(
        equity_curve=tuple(curve),
        total_return_pct=(equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100,
        max_drawdown_pct=max_drawdown * 100,
        turnover=turnover,
    )

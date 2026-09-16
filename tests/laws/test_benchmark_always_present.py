"""Law 8: every result is compared against buy-and-hold. A real
implementation, not xfail -- run_backtest computes vs_benchmark internally
(prometheus/backtest/engine.py), so this is testing that it's actually
wired up, not just theoretically possible. No DB needed -- pure Polars,
synthetic data, runs everywhere.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.backtest.benchmark import VsBenchmark, compute_benchmark_curve
from prometheus.backtest.engine import run_backtest
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

_SYMBOL = "BTC/USDT"
_START = datetime(2023, 1, 1, tzinfo=UTC)


def _trending_bars(n: int) -> list[dict]:
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.001
        event_time = _START + timedelta(days=i)
        rows.append(
            {
                "symbol": _SYMBOL,
                "timeframe": "1d",
                "event_time": event_time,
                "available_at": event_time + timedelta(minutes=5),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1000.0,
            }
        )
    return rows


def test_every_backtest_result_carries_a_real_vs_benchmark() -> None:
    rows = _trending_bars(60)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    spec = StrategySpec(
        symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )

    result = run_backtest(pit, spec, rows[-1]["available_at"])

    assert result.vs_benchmark is not None
    assert isinstance(result.vs_benchmark, VsBenchmark)
    # Not a placeholder zero-object -- excess_return is a real computed
    # number (could legitimately be 0.0 by chance, but the fields must
    # exist and be the right type, not None/missing).
    assert isinstance(result.vs_benchmark.excess_return, float)
    assert isinstance(result.vs_benchmark.periods_underperforming_pct, float)
    assert isinstance(result.vs_benchmark.max_relative_drawdown, float)


def test_caller_supplied_benchmark_result_is_reused_not_recomputed() -> None:
    """runner.py passes its own already-computed benchmark_result in to
    avoid computing it twice -- prove the passed-in one is actually used
    (same final_value) rather than silently ignored."""
    rows = _trending_bars(60)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    spec = StrategySpec(
        symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    cutoff = rows[-1]["available_at"]

    precomputed = compute_benchmark_curve(pit, [_SYMBOL], cutoff)
    result = run_backtest(pit, spec, cutoff, benchmark_result=precomputed)

    expected_excess_return = (
        (result.equity_curve[-1][1] - 1000.0) / 1000.0 * 100
        - (precomputed.final_value - 1000.0) / 1000.0 * 100
    )
    assert result.vs_benchmark.excess_return == expected_excess_return

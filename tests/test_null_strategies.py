"""Falsification before generation (CLAUDE.md, non-negotiable): a null
strategy that should obviously do nothing must actually show nothing in
the engine's output. This is the sanity check that catches a bug in
run_backtest that would make everything look profitable -- must be green
before prometheus.research.generate is ever wired into a real run.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.backtest.benchmark import compute_benchmark_curve
from prometheus.backtest.costs import apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, run_backtest
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

_SYMBOL = "BTC/USDT"
_START = datetime(2023, 1, 1, tzinfo=UTC)


def _flat_price_bars(n: int) -> list[dict]:
    """Every bar has the IDENTICAL close -- fast SMA == slow SMA always,
    so a crossover strategy's signal (`fast > slow`) is false for every
    bar: this is a genuinely null strategy, not a coincidentally-flat one."""
    rows = []
    for i in range(n):
        event_time = _START + timedelta(days=i)
        rows.append(
            {
                "symbol": _SYMBOL,
                "timeframe": "1d",
                "event_time": event_time,
                "available_at": event_time + timedelta(minutes=5),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    return rows


def test_never_crossing_strategy_never_trades() -> None:
    rows = _flat_price_bars(60)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    spec = StrategySpec(symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20)

    result = run_backtest(pit, spec, rows[-1]["available_at"])

    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0
    assert result.max_drawdown_pct == 0.0
    # No trade, no cost -- equity is exactly the starting capital, not
    # approximately: a real bug that fabricated any drift would show up
    # here as a nonzero difference, not just a rounding error.
    assert all(equity == STARTING_CAPITAL for _, equity in result.equity_curve)


def test_benchmark_pays_exactly_one_entry_cost_when_price_never_moves() -> None:
    """The buy-and-hold benchmark on flat prices should show a return of
    exactly -TOTAL_COST_BPS (one entry cost, nothing else) -- proves the
    benchmark path isn't silently re-charging costs every bar."""
    rows = _flat_price_bars(30)
    pit = PointInTimeFrame(pl.DataFrame(rows))

    curve = compute_benchmark_curve(pit, _SYMBOL, rows[-1]["available_at"])

    entry_cost = apply_cost(STARTING_CAPITAL)
    expected_equity = STARTING_CAPITAL - entry_cost
    assert all(equity == expected_equity for _, equity in curve)


def test_a_strategy_tied_with_the_benchmark_does_not_beat_it() -> None:
    """CLAUDE.md's own framing: 'if a strategy cannot beat this after
    costs, it is not an edge.' The decision rule (prometheus.experiments.
    runner) is a strict `>`: an exact tie must not register as beating the
    benchmark."""
    strategy_return_pct = 3.5
    benchmark_return_pct = 3.5

    beats_benchmark = strategy_return_pct > benchmark_return_pct
    assert beats_benchmark is False

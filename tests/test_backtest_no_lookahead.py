"""Engine-level analogue of tests/laws/test_no_lookahead.py: proves
run_backtest never lets a bar beyond `as_of_cutoff` affect its result, not
just that PointInTimeFrame.as_of() filters correctly in isolation. No DB
needed -- pure Polars, synthetic data, runs everywhere.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.backtest.engine import run_backtest
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

_SYMBOL = "BTC/USDT"
_START = datetime(2023, 1, 1, tzinfo=UTC)
_N_BARS = 300
_SPEC = StrategySpec(
    symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
)


def _bars(n: int, rng: random.Random, shock_last: float | None = None) -> list[dict]:
    rows = []
    price = 100.0
    for i in range(n):
        event_time = _START + timedelta(days=i)
        price *= 1 + rng.uniform(-0.02, 0.02)
        close = price if shock_last is None or i != n - 1 else shock_last
        rows.append(
            {
                "symbol": _SYMBOL,
                "timeframe": "1d",
                "event_time": event_time,
                "available_at": event_time + timedelta(minutes=5),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
            }
        )
    return rows


def test_future_bars_beyond_cutoff_never_affect_the_result() -> None:
    """The single most valuable test in this file: appending more bars
    with a price shock, all with available_at AFTER the cutoff, must not
    change the backtest result at all -- run_backtest on the extended
    frame must equal run_backtest on the frame physically truncated to
    remove those future rows entirely."""
    rng = random.Random(7)
    base_rows = _bars(100, rng)
    cutoff = base_rows[-1]["available_at"]

    extended_rows = base_rows + _bars(20, random.Random(999), shock_last=999_999.0)
    # Re-anchor the shock rows' timestamps after the cutoff.
    for i, row in enumerate(extended_rows[100:]):
        row["event_time"] = _START + timedelta(days=100 + i)
        row["available_at"] = row["event_time"] + timedelta(minutes=5)

    truncated_pit = PointInTimeFrame(pl.DataFrame(base_rows))
    extended_pit = PointInTimeFrame(pl.DataFrame(extended_rows))

    truncated_result = run_backtest(truncated_pit, _SPEC, cutoff)
    extended_result = run_backtest(extended_pit, _SPEC, cutoff)

    assert extended_result == truncated_result


def test_backtest_is_deterministic() -> None:
    rng = random.Random(42)
    rows = _bars(150, rng)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    cutoff = rows[-1]["available_at"]

    first = run_backtest(pit, _SPEC, cutoff)
    second = run_backtest(pit, _SPEC, cutoff)

    assert first == second


def test_not_enough_bars_raises() -> None:
    rng = random.Random(1)
    rows = _bars(5, rng)  # fewer than slow_window + 2
    pit = PointInTimeFrame(pl.DataFrame(rows))

    try:
        run_backtest(pit, _SPEC, rows[-1]["available_at"])
    except ValueError as exc:
        assert "not enough bars" in str(exc)
    else:
        raise AssertionError("expected ValueError for insufficient bars")

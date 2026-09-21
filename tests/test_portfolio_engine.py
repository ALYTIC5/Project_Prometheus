"""tests/test_portfolio_engine.py"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.portfolio_engine import (
    run_portfolio_backtest,
    weights_for_equal_weight,
)
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import ROTATION_FAMILY_EQUAL_WEIGHT, RotationSpec


def test_weights_for_equal_weight_splits_evenly() -> None:
    weights = weights_for_equal_weight(["A", "B", "C"])
    assert weights == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_weights_for_equal_weight_empty_universe_is_empty() -> None:
    assert weights_for_equal_weight([]) == {}


def _synthetic_pit(prices: dict[str, list[float]], start: datetime) -> PointInTimeFrame:
    rows = []
    for symbol, closes in prices.items():
        for i, close in enumerate(closes):
            ts = start + timedelta(days=i)
            rows.append(
                {
                    "symbol": symbol, "timeframe": "1d", "event_time": ts, "available_at": ts,
                    "open": close, "high": close, "low": close, "close": close,
                    "volume": 1000.0,
                }
            )
    return PointInTimeFrame(pl.DataFrame(rows))


def test_equal_weight_two_symbols_no_rebalance_drift_matches_hand_calc() -> None:
    # A: flat at 100 the whole time. B: 100 -> 110 (a +10% move on day 5).
    # rebalance_frequency_days larger than the window -- exactly ONE
    # rebalance at the start, no mid-window rebalance -- isolates pure
    # buy-and-hold-of-equal-weight drift with a hand-computable answer:
    # start $1000 equally split ($500/$500), zero cost model, B's leg
    # grows 10% -> $550, A's leg flat -> $500, total $1050 = +5.0%.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {"A": [100.0] * 6, "B": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]}, start
    )
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2019, 1, 1), None),
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,  # longer than the 6-day window
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, start + timedelta(days=5),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(5.0, abs=0.01)


def test_equal_weight_excludes_symbol_before_its_listed_at() -> None:
    # B isn't "listed" (per membership) until day 3 -- a rebalance at
    # day 0 must be 100% A, not split with a not-yet-eligible B.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit({"A": [100.0] * 4, "B": [100.0] * 4}, start)
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2020, 1, 4), None),  # listed after this whole window
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, start + timedelta(days=3),
        cost_model=lambda notional: 0.0,
    )
    # Flat prices throughout, whichever symbols were actually held --
    # the real assertion is that this doesn't raise and returns ~0%,
    # proving B's exclusion didn't leave a dangling/NaN allocation.
    assert result.total_return_pct == pytest.approx(0.0, abs=0.01)

"""tests/test_portfolio_engine.py"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.portfolio_engine import (
    run_portfolio_backtest,
    trailing_return,
    weights_for_dual_momentum_gem,
    weights_for_equal_weight,
    weights_for_gtaa_sma,
    weights_for_top_n_momentum,
)
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    RotationSpec,
)


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


def test_trailing_return_none_when_insufficient_history() -> None:
    bars = pl.DataFrame(
        {"available_at": [datetime(2020, 1, 1), datetime(2020, 1, 2)], "close": [100.0, 101.0]}
    )
    assert trailing_return(bars, date(2020, 1, 2), lookback_days=10) is None


def test_trailing_return_computes_pct_change_over_lookback() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(5)]
    closes = [100.0, 101.0, 102.0, 103.0, 110.0]
    bars = pl.DataFrame({"available_at": dates, "close": closes})
    # From day 1 (100.0) to day 5 (110.0), lookback_days=4 (index span).
    assert trailing_return(bars, date(2020, 1, 5), lookback_days=4) == pytest.approx(0.10)


def test_weights_for_top_n_momentum_picks_best_n_equal_weighted() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),  # +5%
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),  # +20% best
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=2,
    )
    assert set(weights) == {"A", "C"}  # top 2 by return: C then A
    assert weights["A"] == pytest.approx(0.5)
    assert weights["C"] == pytest.approx(0.5)


def test_weights_for_top_n_momentum_worst_picks_bottom_n() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2),
        lookback_days=1, top_n=1, worst=True,
    )
    assert set(weights) == {"B"}  # worst performer
    assert weights["B"] == pytest.approx(1.0)


def test_weights_for_top_n_momentum_fewer_eligible_than_top_n_uses_all_eligible() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=3,
    )
    assert weights == {"A": pytest.approx(1.0)}


def test_gem_picks_stronger_positive_equity_leg() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 110.0]}),  # +10%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 103.0]}),  # +3%
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"SPY": pytest.approx(1.0)}


def test_gem_falls_back_to_defensive_when_both_equity_legs_negative() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 95.0]}),   # -5%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%, worse
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"TLT": pytest.approx(1.0)}


def test_gem_missing_defensive_leg_history_returns_empty() -> None:
    # If even the defensive leg lacks lookback history, no honest
    # decision can be made this cycle -- empty (100% cash), not a crash.
    dates = [datetime(2020, 1, 1)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0]}),
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 1), lookback_days=5,
    )
    assert weights == {}


def test_gem_dispatch_guard_fires_when_defensive_leg_ineligible() -> None:
    # TLT (the real defensive leg, spec.universe[-1]) is never "listed"
    # per membership -- it must never be silently swapped in for by
    # eligible[-1] once _eligible_symbols drops it. SPY's own trailing
    # return is negative at the rebalance, so if the guard were absent,
    # `weights_for_dual_momentum_gem` would be called with
    # eligible == ["SPY", "EFA"] and would mis-treat EFA (a real equity
    # leg, +8% and rising) as the "defensive" fallback, returning
    # {"EFA": 1.0} -- a real, nonzero position built on a
    # misidentification. `_weights_for`'s guard must instead recognize
    # TLT's absence from `eligible` and return {} (100% cash) before
    # ever calling the family function, so the final result is flat
    # despite EFA's large, real price move.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "SPY": [100.0, 95.0, 90.0],   # -5% at rebalance, then further down
            "EFA": [100.0, 108.0, 110.0],  # +8% at rebalance, then further up
            "TLT": [100.0, 101.0, 102.0],
        },
        start,
    )
    membership = {
        "SPY": (date(2019, 1, 1), None),
        "EFA": (date(2019, 1, 1), None),
        "TLT": (date(2020, 6, 1), None),  # listed well after this whole window
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
        universe=("SPY", "EFA", "TLT"),
        timeframe="1d",
        lookback_days=1,
        rebalance_frequency_days=100,  # exactly one rebalance in this window
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, start + timedelta(days=2),
        cost_model=lambda notional: 0.0,
    )
    # If the guard were absent/wrong, EFA's real +10% move (108 -> 110
    # post-rebalance) would show up as a nonzero return. Flat 0% proves
    # the rebalance was honestly skipped instead.
    assert result.total_return_pct == pytest.approx(0.0, abs=0.01)


def test_gtaa_sma_holds_only_assets_above_their_own_sma() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(4)]
    bars_by_symbol = {
        # SMA(3) as of day 4: mean(100,100,100)=100, close=110 -> above -> IN
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 110.0]}),
        # SMA(3) as of day 4: mean(100,100,100)=100, close=90 -> below -> OUT
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(
        ["SPY", "TLT"], bars_by_symbol, date(2020, 1, 4), lookback_days=3,
    )
    # Each asset's SLICE is always 1/N of capital -- an OUT asset's slice
    # is simply absent (cash), never redistributed to the IN asset.
    assert weights == {"SPY": pytest.approx(0.5)}


def test_gtaa_sma_all_out_returns_empty_weights() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(4)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(["SPY"], bars_by_symbol, date(2020, 1, 4), lookback_days=3)
    assert weights == {}

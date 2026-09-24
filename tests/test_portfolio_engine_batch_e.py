"""tests/test_portfolio_engine_batch_e.py -- weight-function correctness
for the 7 Batch E (cross-sectional rotation) families added to
backtest/portfolio_engine.py: DAA, PAA, ACCELERATING_DUAL_MOMENTUM,
RISK_PARITY, MIN_VARIANCE, FIFTY_TWO_WEEK_HIGH, RESIDUAL_MOMENTUM.

Same "production timestamp shape" discipline test_portfolio_engine.py's
own module docstring establishes: every bar carries the real
`available_at = event_time + 5 minutes` ingestion lag, not bare
midnight, so a cutoff bug invisible against synthetic midnight
timestamps can't hide here either.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.portfolio_engine import (
    weights_for_accelerating_dual_momentum,
    weights_for_daa,
    weights_for_fifty_two_week_high,
    weights_for_min_variance,
    weights_for_paa,
    weights_for_residual_momentum,
    weights_for_risk_parity,
)

_INGESTION_LAG = timedelta(minutes=5)


def _lagged_days(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(days=i) + _INGESTION_LAG for i in range(count)]


def _trend_bars(n: int, start: float, step: float) -> pl.DataFrame:
    closes = [start + step * i for i in range(n)]
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    return pl.DataFrame({"available_at": dates, "close": closes})


def _as_of(n: int) -> date:
    return (datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=n - 1)).date()


def test_daa_holds_defensive_leg_when_both_canary_assets_negative() -> None:
    n = 260
    bars_by_symbol = {
        "CANARY1": _trend_bars(n, 100.0, -0.3),
        "CANARY2": _trend_bars(n, 100.0, -0.3),
        "OFF1": _trend_bars(n, 100.0, 0.5),
        "DEF": _trend_bars(n, 100.0, 0.1),
    }
    universe = ("CANARY1", "CANARY2", "OFF1", "DEF")
    weights = weights_for_daa(
        list(universe), bars_by_symbol, _as_of(n), universe, top_n=1,
    )
    assert weights == {"DEF": pytest.approx(1.0)}


def test_daa_splits_offensive_leg_when_canary_positive() -> None:
    n = 260
    bars_by_symbol = {
        "CANARY1": _trend_bars(n, 100.0, 0.3),
        "CANARY2": _trend_bars(n, 100.0, 0.3),
        "OFF1": _trend_bars(n, 100.0, 0.5),
        "DEF": _trend_bars(n, 100.0, 0.1),
    }
    universe = ("CANARY1", "CANARY2", "OFF1", "DEF")
    weights = weights_for_daa(
        list(universe), bars_by_symbol, _as_of(n), universe, top_n=1,
    )
    assert weights == {"OFF1": pytest.approx(1.0)}


def test_daa_missing_canary_history_returns_empty() -> None:
    n = 10
    bars_by_symbol = {
        "CANARY1": _trend_bars(n, 100.0, 0.3),
        "CANARY2": _trend_bars(n, 100.0, 0.3),
        "OFF1": _trend_bars(n, 100.0, 0.5),
        "DEF": _trend_bars(n, 100.0, 0.1),
    }
    universe = ("CANARY1", "CANARY2", "OFF1", "DEF")
    weights = weights_for_daa(
        list(universe), bars_by_symbol, _as_of(n), universe, top_n=1,
    )
    assert weights == {}


def test_paa_goes_fully_defensive_when_all_offensive_below_sma() -> None:
    n = 220
    bars_by_symbol = {
        "OFF1": _trend_bars(n, 200.0, -0.3),
        "OFF2": _trend_bars(n, 200.0, -0.2),
        "DEF": _trend_bars(n, 100.0, 0.1),
    }
    universe = ("OFF1", "OFF2", "DEF")
    weights = weights_for_paa(
        list(universe), bars_by_symbol, _as_of(n), universe,
        lookback_days=200, top_n=1, protection_factor=1.0,
    )
    assert weights == {"DEF": pytest.approx(1.0)}


def test_paa_goes_fully_equity_when_all_offensive_above_sma() -> None:
    n = 220
    bars_by_symbol = {
        "OFF1": _trend_bars(n, 100.0, 0.5),
        "OFF2": _trend_bars(n, 100.0, 0.4),
        "DEF": _trend_bars(n, 100.0, 0.1),
    }
    universe = ("OFF1", "OFF2", "DEF")
    weights = weights_for_paa(
        list(universe), bars_by_symbol, _as_of(n), universe,
        lookback_days=200, top_n=2, protection_factor=1.0,
    )
    assert set(weights) == {"OFF1", "OFF2"}
    assert weights["OFF1"] == pytest.approx(0.5)
    assert weights["OFF2"] == pytest.approx(0.5)


def test_accelerating_dual_momentum_picks_stronger_positive_equity_leg() -> None:
    n = 130
    bars_by_symbol = {
        "QQQ": _trend_bars(n, 100.0, 0.5),
        "EFA": _trend_bars(n, 100.0, 0.1),
        "IEF": _trend_bars(n, 100.0, 0.05),
    }
    weights = weights_for_accelerating_dual_momentum(
        ["QQQ", "EFA", "IEF"], bars_by_symbol, _as_of(n),
    )
    assert weights == {"QQQ": pytest.approx(1.0)}


def test_accelerating_dual_momentum_falls_back_to_defensive() -> None:
    n = 130
    bars_by_symbol = {
        "QQQ": _trend_bars(n, 200.0, -0.5),
        "EFA": _trend_bars(n, 200.0, -0.3),
        "IEF": _trend_bars(n, 100.0, 0.05),
    }
    weights = weights_for_accelerating_dual_momentum(
        ["QQQ", "EFA", "IEF"], bars_by_symbol, _as_of(n),
    )
    assert weights == {"IEF": pytest.approx(1.0)}


def test_risk_parity_favors_lower_volatility_asset() -> None:
    n = 80
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    low_vol = [100.0 + 0.1 * (i % 2) for i in range(n)]
    high_vol = [100.0 + 5.0 * (i % 2) for i in range(n)]
    bars_by_symbol = {
        "LOW": pl.DataFrame({"available_at": dates, "close": low_vol}),
        "HIGH": pl.DataFrame({"available_at": dates, "close": high_vol}),
    }
    weights = weights_for_risk_parity(["LOW", "HIGH"], bars_by_symbol, _as_of(n), lookback_days=60)
    assert weights["LOW"] > weights["HIGH"]
    assert weights["LOW"] + weights["HIGH"] == pytest.approx(1.0)


def test_risk_parity_excludes_insufficient_history() -> None:
    n = 5
    bars_by_symbol = {"A": _trend_bars(n, 100.0, 1.0)}
    weights = weights_for_risk_parity(["A"], bars_by_symbol, _as_of(n), lookback_days=60)
    assert weights == {}


def test_min_variance_handles_near_singular_covariance_without_crashing() -> None:
    # Two near-perfectly-correlated series (B always moves 5x A's own
    # step) push the sample covariance matrix toward singular. Floating
    # point rounding means numpy.linalg.inv often still succeeds (an
    # exactly-zero determinant is rare in float64), producing an
    # extreme but still-valid weight split rather than tripping the
    # documented LinAlgError fallback -- this test only asserts the
    # function never crashes and always returns valid weights, since
    # which of the two paths numpy takes here is a floating-point
    # implementation detail, not this function's own contract.
    n = 80
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    a = [100.0 + 0.1 * (i % 2) for i in range(n)]
    b = [100.0 + 0.5 * (i % 2) for i in range(n)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": a}),
        "B": pl.DataFrame({"available_at": dates, "close": b}),
    }
    mv_weights = weights_for_min_variance(["A", "B"], bars_by_symbol, _as_of(n), lookback_days=60)
    assert mv_weights
    assert all(w >= 0.0 for w in mv_weights.values())
    assert sum(mv_weights.values()) == pytest.approx(1.0)


def test_min_variance_falls_back_to_risk_parity_with_fewer_than_two_symbols() -> None:
    n = 80
    bars_by_symbol = {"A": _trend_bars(n, 100.0, 1.0)}
    mv_weights = weights_for_min_variance(["A"], bars_by_symbol, _as_of(n), lookback_days=60)
    rp_weights = weights_for_risk_parity(["A"], bars_by_symbol, _as_of(n), lookback_days=60)
    assert mv_weights == rp_weights


def test_min_variance_produces_valid_weights_on_independent_series() -> None:
    n = 100
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    a = [100.0 + (1 if i % 2 == 0 else -1) for i in range(n)]
    b = [100.0 + (2 if i % 3 == 0 else -1) for i in range(n)]
    c = [100.0 + (1 if i % 5 == 0 else -0.5) for i in range(n)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": a}),
        "B": pl.DataFrame({"available_at": dates, "close": b}),
        "C": pl.DataFrame({"available_at": dates, "close": c}),
    }
    weights = weights_for_min_variance(["A", "B", "C"], bars_by_symbol, _as_of(n), lookback_days=60)
    assert weights
    assert all(w >= 0.0 for w in weights.values())
    assert sum(weights.values()) == pytest.approx(1.0)


def test_fifty_two_week_high_picks_asset_closest_to_its_own_high() -> None:
    n = 260
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    at_high = [100.0 + i for i in range(n)]  # today IS the 252-bar high
    off_high = [100.0 + i for i in range(n - 30)] + [100.0 + (n - 30) - i for i in range(30)]
    bars_by_symbol = {
        "AT_HIGH": pl.DataFrame({"available_at": dates, "close": at_high}),
        "OFF_HIGH": pl.DataFrame({"available_at": dates, "close": off_high}),
    }
    weights = weights_for_fifty_two_week_high(
        ["AT_HIGH", "OFF_HIGH"], bars_by_symbol, _as_of(n), lookback_days=252, top_n=1,
    )
    assert weights == {"AT_HIGH": pytest.approx(1.0)}


def test_residual_momentum_ranks_by_idiosyncratic_excess_not_raw_return() -> None:
    n = 60
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    bench_returns = [0.01, -0.004, 0.006, -0.002] * (n // 4)
    bench_closes = [100.0]
    for r in bench_returns[: n - 1]:
        bench_closes.append(bench_closes[-1] * (1 + r))

    def _with_excess(excess: float) -> list[float]:
        closes = [100.0]
        for r in bench_returns[: n - 1]:
            closes.append(closes[-1] * (1 + r + excess))
        return closes

    bars_by_symbol = {
        "BENCH": pl.DataFrame({"available_at": dates, "close": bench_closes}),
        "TRACKS": pl.DataFrame({"available_at": dates, "close": list(bench_closes)}),
        "OUTPERFORMS": pl.DataFrame({"available_at": dates, "close": _with_excess(0.01)}),
        "UNDERPERFORMS": pl.DataFrame({"available_at": dates, "close": _with_excess(-0.01)}),
    }
    universe = ("BENCH", "TRACKS", "OUTPERFORMS", "UNDERPERFORMS")
    weights = weights_for_residual_momentum(
        list(universe), bars_by_symbol, _as_of(n), universe, lookback_days=40, top_n=1,
    )
    assert weights == {"OUTPERFORMS": pytest.approx(1.0)}


def test_residual_momentum_never_holds_the_benchmark_itself() -> None:
    n = 60
    dates = _lagged_days(datetime(2020, 1, 1, tzinfo=UTC), n)
    bench_returns = [0.01, -0.004, 0.006, -0.002] * (n // 4)
    bench_closes = [100.0]
    for r in bench_returns[: n - 1]:
        bench_closes.append(bench_closes[-1] * (1 + r))
    bars_by_symbol = {
        "BENCH": pl.DataFrame({"available_at": dates, "close": bench_closes}),
        "POOL": pl.DataFrame({"available_at": dates, "close": bench_closes}),
    }
    universe = ("BENCH", "POOL")
    weights = weights_for_residual_momentum(
        list(universe), bars_by_symbol, _as_of(n), universe, lookback_days=40, top_n=5,
    )
    assert "BENCH" not in weights

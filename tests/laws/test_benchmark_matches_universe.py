"""LAW 8: every backtest is compared against a buy-and-hold of THE
STRATEGY'S OWN UNIVERSE over THE STRATEGY'S OWN WINDOW, same cost model.

Parametrised across every registered family -- all single-asset families
(the real baseline-grid specs plus the four ML families) and every
cross-sectional rotation family. The data always contains other symbols
with different price paths, so a benchmark built from the wrong symbol, a
global default, or the full pre-warm-up history is caught numerically, not
just by label.

Added 2026-09-24 after the benchmark audit: runner.py precomputed one
benchmark over the full loaded history and reused it for every spec,
charging strategies buy-and-hold over warm-up bars they could never trade.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.benchmark import BenchmarkMismatch, compute_benchmark_curve
from prometheus.backtest.costs import apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, run_backtest, warmup_start_index
from prometheus.backtest.portfolio_engine import run_portfolio_backtest
from prometheus.data.schema import PointInTimeFrame
from prometheus.research.ml.generate import (
    generate_gradient_boosting_grid,
    generate_logistic_regression_grid,
    generate_random_forest_grid,
    generate_svm_grid,
)
from prometheus.research.rotation_generate import ROTATION_GRID_GENERATORS
from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.rotation_spec import RotationSpec
from prometheus.strategy.spec import StrategySpec

_START = datetime(2021, 1, 1, tzinfo=UTC)
_N_BARS = 700
_TARGET = "BTC/USDT"
_DECOY = "ETH/USDT"


def _price(symbol_seed: int, i: int) -> float:
    # Deterministic, non-degenerate, symbol-specific paths: different drift
    # and cycle per symbol, so every symbol's buy-and-hold differs.
    drift = 1.0 + 0.0004 * (1 + symbol_seed % 5) * (-1 if symbol_seed % 2 else 1)
    return 100.0 * drift**i * (1.0 + 0.05 * math.sin(i / (7.0 + symbol_seed)))


def _pit(symbols: list[str]) -> PointInTimeFrame:
    rows = []
    for seed, symbol in enumerate(symbols):
        for i in range(_N_BARS):
            close = _price(seed, i)
            event_time = _START + timedelta(days=i)
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": "1d",
                    "event_time": event_time,
                    "available_at": event_time + timedelta(minutes=5),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1000.0 + (i * 37 + seed * 11) % 400,
                }
            )
    return PointInTimeFrame(pl.DataFrame(rows))


def _cutoff() -> datetime:
    return _START + timedelta(days=_N_BARS - 1, hours=23)


def _single_asset_specs() -> dict[str, StrategySpec]:
    specs = {family: grid[0] for family, grid in seed_specs_by_family().items()}
    for generate in (
        generate_random_forest_grid,
        generate_gradient_boosting_grid,
        generate_logistic_regression_grid,
        generate_svm_grid,
    ):
        spec = generate(_TARGET, "1d")[0]
        specs[spec.family] = spec
    return {family: spec.with_updates(symbol=_TARGET) for family, spec in specs.items()}


_SINGLE = _single_asset_specs()
_ROTATION: dict[str, RotationSpec] = {
    grid()[0].family: grid()[0] for grid in ROTATION_GRID_GENERATORS
}


@pytest.mark.parametrize("family", sorted(_SINGLE))
def test_single_asset_benchmark_is_own_symbol_over_own_window(family: str) -> None:
    spec = _SINGLE[family]
    pit = _pit([_DECOY, _TARGET, "SOL/USDT"])
    result = run_backtest(pit, spec, _cutoff())

    assert result.benchmark.universe == (_TARGET,)

    strategy_start = datetime.fromisoformat(result.equity_curve[0][0]).date()
    strategy_end = datetime.fromisoformat(result.equity_curve[-1][0]).date()
    assert (result.benchmark.window_start, result.benchmark.window_end) == (
        strategy_start,
        strategy_end,
    )

    # Independently recomputed buy-and-hold of the target symbol, entered
    # at the strategy's first tradable bar -- proves it's THIS symbol and
    # THIS window, not a label that merely says so.
    closes = [_price(1, i) for i in range(_N_BARS)]
    entry = closes[warmup_start_index(spec)]
    expected_final = (STARTING_CAPITAL - apply_cost(STARTING_CAPITAL)) * closes[-1] / entry
    assert result.benchmark.final_value == pytest.approx(expected_final, rel=1e-12)


@pytest.mark.parametrize("family", sorted(_ROTATION))
def test_rotation_benchmark_is_own_universe_over_own_window(family: str) -> None:
    spec = _ROTATION[family]
    universe = list(spec.universe)
    pit = _pit([*universe, "DECOY/USDT"])
    membership: dict[str, tuple[date, date | None]] = {
        symbol: (date(2000, 1, 1), None) for symbol in universe
    }
    result = run_portfolio_backtest(pit, spec, membership, _cutoff())

    assert tuple(sorted(result.benchmark.universe)) == tuple(sorted(universe))
    strategy_start = datetime.fromisoformat(result.equity_curve[0][0]).date()
    strategy_end = datetime.fromisoformat(result.equity_curve[-1][0]).date()
    assert (result.benchmark.window_start, result.benchmark.window_end) == (
        strategy_start,
        strategy_end,
    )


def test_wrong_symbol_benchmark_is_a_hard_error() -> None:
    spec = _SINGLE["MOMENTUM"]
    pit = _pit([_DECOY, _TARGET])
    wrong = run_backtest(pit, spec.with_updates(symbol=_DECOY), _cutoff()).benchmark
    with pytest.raises(BenchmarkMismatch):
        run_backtest(pit, spec, _cutoff(), benchmark_result=wrong)


def test_full_history_benchmark_for_a_warmed_up_strategy_is_a_hard_error() -> None:
    """The exact pre-2026-09-24 bug: one benchmark over the full loaded
    history reused for a spec whose window starts after its warm-up."""
    spec = _SINGLE["MOMENTUM"]
    pit = _pit([_TARGET])
    full_history = compute_benchmark_curve(
        pit, [_TARGET], window_start=None, window_end=_cutoff(), cost_model=apply_cost
    )
    with pytest.raises(BenchmarkMismatch):
        run_backtest(pit, spec, _cutoff(), benchmark_result=full_history)

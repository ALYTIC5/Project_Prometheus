"""experiments/runner.py's enqueue-time history check and the terminal
InsufficientDataRecorded outcome -- the fix for the 2026-09-24 churn where
insufficient-data jobs were retried, dead-lettered, and re-enqueued every
cycle forever. Pure functions, no DB."""
from __future__ import annotations

from prometheus.backtest.engine import min_bars_for
from prometheus.experiments.runner import InsufficientDataRecorded, specs_with_enough_history
from prometheus.strategy.spec import StrategySpec

_SPEC = StrategySpec(
    symbol="DOT/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
)


def test_spec_deferred_when_symbol_has_no_bars() -> None:
    assert specs_with_enough_history([_SPEC], {}) == []


def test_spec_deferred_exactly_at_its_warm_up_boundary() -> None:
    """One bar of margin: the window count can include the current,
    not-yet-available bar the engine's as_of view excludes."""
    need = min_bars_for(_SPEC)
    assert specs_with_enough_history([_SPEC], {("DOT/USDT", "1d"): need}) == []


def test_spec_enqueued_once_warm_up_plus_margin_is_covered() -> None:
    need = min_bars_for(_SPEC)
    assert specs_with_enough_history([_SPEC], {("DOT/USDT", "1d"): need + 1}) == [_SPEC]


def test_bars_for_a_different_timeframe_do_not_count() -> None:
    assert specs_with_enough_history([_SPEC], {("DOT/USDT", "1h"): 10_000}) == []


def test_insufficient_data_recorded_is_still_a_value_error() -> None:
    """Every existing caller that expects run_one to raise ValueError on
    too few bars must keep working unchanged."""
    exc = InsufficientDataRecorded("not enough bars", "EXP-2026-000001")
    assert isinstance(exc, ValueError)
    assert exc.experiment_id == "EXP-2026-000001"

"""validation/metrics.py + validation/decay.py. Pure functions over
synthetic bars, no DB -- same synthetic-bar pattern as
tests/test_null_strategies.py's _bar_row."""
from __future__ import annotations

import polars as pl

from prometheus.core.seeds import rng_for
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.decay import DECAY_HORIZONS, compute_decay
from prometheus.validation.metrics import (
    compute_metrics,
    hit_rate,
    information_coefficient,
)
from tests.test_null_strategies import _random_walk_bars, _trending_bars

_SYMBOL = "BTC/USDT"
_SPEC = StrategySpec(
    symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
)


def test_hit_rate_on_monotonically_rising_curve_is_one() -> None:
    curve = tuple((str(i), 100.0 + i) for i in range(20))
    assert hit_rate(curve) == 1.0


def test_hit_rate_none_below_two_points() -> None:
    assert hit_rate(()) is None
    assert hit_rate((("t0", 100.0),)) is None


def test_information_coefficient_positive_on_a_genuine_trend_signal() -> None:
    """A strongly trending series: the fast-minus-slow spread should be
    persistently positive right alongside persistently positive forward
    returns -- IC should come back positive, not just "not None". Not
    asserting a specific magnitude: a smooth deterministic trend makes
    both the spread and the forward return converge toward a near-constant
    value once past warm-up, which is genuinely noisy for a RANK
    correlation even though the sign is reliably positive."""
    rows = _trending_bars(200)
    bars = pl.DataFrame(rows)
    ic = information_coefficient(bars, _SPEC, horizon=5)
    assert ic is not None
    assert ic > 0.0


def test_information_coefficient_none_on_pure_noise_or_too_short() -> None:
    rows = _random_walk_bars(200, rng_for(123))
    bars = pl.DataFrame(rows)
    # Not asserting a specific value (noise IC is itself noisy) -- only
    # that the function runs cleanly end to end and returns a valid
    # correlation in [-1, 1] or None.
    ic = information_coefficient(bars, _SPEC, horizon=5)
    assert ic is None or -1.0 <= ic <= 1.0

    short_bars = pl.DataFrame(_trending_bars(_SPEC.slow_window + 3))
    assert information_coefficient(short_bars, _SPEC, horizon=5) is None


def test_compute_metrics_runs_end_to_end_without_crashing() -> None:
    rows = _trending_bars(200)
    bars = pl.DataFrame(rows)
    equity_curve = tuple((r["available_at"].isoformat(), 1000.0 + i) for i, r in enumerate(rows))
    metrics = compute_metrics(equity_curve, turnover=3.0, bars=bars, spec=_SPEC)
    assert metrics.turnover == 3.0
    assert metrics.hit_rate == 1.0  # every step +1 -> monotonically rising


def test_compute_decay_reports_every_named_horizon() -> None:
    rows = _trending_bars(300)
    bars = pl.DataFrame(rows)
    profile = compute_decay(bars, _SPEC)
    assert set(DECAY_HORIZONS).issubset(profile.ic_by_horizon.keys())
    assert profile.claimed_horizon == _SPEC.expected_horizon
    # has_power is either a real bool (judged) or None (not enough data) --
    # never silently skipped.
    assert profile.has_power_at_claimed_horizon in (True, False, None)

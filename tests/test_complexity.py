from __future__ import annotations

from prometheus.research.complexity import complexity_penalty, parameter_count
from prometheus.strategy.spec import StrategySpec

_MOMENTUM = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=10, slow_window=20, expected_horizon=20,
)
_BOLLINGER = StrategySpec(
    family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
    lookback_window=20, band_multiplier=2.0, expected_horizon=20,
)


def test_parameter_count_matches_spec_parameters() -> None:
    assert parameter_count(_MOMENTUM) == len(_MOMENTUM.parameters) == 2
    assert parameter_count(_BOLLINGER) == len(_BOLLINGER.parameters) == 2


def test_complexity_penalty_is_monotonic_in_parameter_count() -> None:
    assert complexity_penalty(_MOMENTUM) == float(parameter_count(_MOMENTUM))


def test_complexity_penalty_equal_for_equal_param_counts() -> None:
    assert complexity_penalty(_MOMENTUM) == complexity_penalty(_BOLLINGER)

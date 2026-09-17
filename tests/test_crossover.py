"""research/crossover.py -- same-family recombination. Pure, no DB."""
from __future__ import annotations

from prometheus.core.seeds import rng_for
from prometheus.research.crossover import crossover
from prometheus.strategy.spec import StrategySpec

_MOMENTUM_A = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=10, slow_window=20, expected_horizon=20,
)
_MOMENTUM_B = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=8, slow_window=40, expected_horizon=20,
)
_BOLLINGER_A = StrategySpec(
    family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
    lookback_window=20, band_multiplier=2.0, expected_horizon=20,
)
_DIFFERENT_SYMBOL = StrategySpec(
    family="MOMENTUM", symbol="ETH/USDT", timeframe="1d",
    fast_window=10, slow_window=20, expected_horizon=20,
)


def test_crossover_returns_none_across_families() -> None:
    assert crossover(_MOMENTUM_A, 1.0, _BOLLINGER_A, 1.0, rng_for(1)) is None


def test_crossover_returns_none_across_symbols() -> None:
    assert crossover(_MOMENTUM_A, 1.0, _DIFFERENT_SYMBOL, 1.0, rng_for(1)) is None


def test_crossover_produces_a_valid_same_family_child() -> None:
    result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 0.5, rng_for(1))
    assert result is not None
    assert result.child.family == "MOMENTUM"
    assert result.child.slow_window > result.child.fast_window
    assert result.child.source == "crossover"


def test_crossover_fitter_parent_becomes_parent_id() -> None:
    result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 0.5, rng_for(1))
    assert result is not None
    assert result.child.parent_id == _MOMENTUM_A.config_hash()
    assert result.change_set["secondary_parent_id"] == _MOMENTUM_B.config_hash()


def test_crossover_fitter_parent_prefers_b_on_tie_break_favoring_a() -> None:
    """Ties favor A -- documented in crossover()'s own docstring."""
    result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 1.0, rng_for(1))
    assert result is not None
    assert result.change_set["secondary_parent_id"] == _MOMENTUM_B.config_hash()


def test_crossover_field_sources_cover_every_family_field() -> None:
    result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 0.5, rng_for(2))
    assert result is not None
    assert set(result.change_set["field_sources"].keys()) == {"fast_window", "slow_window"}
    for source in result.change_set["field_sources"].values():
        assert source in ("a", "b", "avg")


def test_crossover_child_values_come_from_parents_or_their_average() -> None:
    for seed in range(50):
        result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 0.5, rng_for(seed))
        if result is None:
            continue
        for field in ("fast_window", "slow_window"):
            a_val, b_val = getattr(_MOMENTUM_A, field), getattr(_MOMENTUM_B, field)
            child_val = getattr(result.child, field)
            avg = round((a_val + b_val) / 2)
            assert child_val in (a_val, b_val, avg)


def test_crossover_never_violates_the_family_validator() -> None:
    for seed in range(200):
        result = crossover(_MOMENTUM_A, 1.0, _MOMENTUM_B, 0.5, rng_for(seed))
        if result is not None:
            assert result.child.slow_window > result.child.fast_window

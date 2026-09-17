"""research/mutations.py -- PARAMETER_TUNE and SWAP_FAMILY. Pure
functions, no DB."""
from __future__ import annotations

import pytest

from prometheus.core.seeds import rng_for
from prometheus.research.mutations import parameter_tune, swap_family
from prometheus.strategy.spec import StrategySpec

_MOMENTUM = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=10, slow_window=20, expected_horizon=20,
)
_BOLLINGER = StrategySpec(
    family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
    lookback_window=20, band_multiplier=2.0, expected_horizon=20,
)
_VOL_BREAKOUT = StrategySpec(
    family="VOL_BREAKOUT", symbol="BTC/USDT", timeframe="1d",
    breakout_window=20, exit_window=10, expected_horizon=20,
)
_TEMPLATES = {"MOMENTUM": [_MOMENTUM], "BOLLINGER": [_BOLLINGER], "VOL_BREAKOUT": [_VOL_BREAKOUT]}


def test_with_updates_rejects_an_invalid_update() -> None:
    """The real bug StrategySpec.with_updates exists to prevent:
    model_copy silently skips validation (confirmed by testing it
    directly) -- going through the real constructor must re-run the
    family validator."""
    with pytest.raises(Exception):  # noqa: B017
        _MOMENTUM.with_updates(slow_window=5)  # < fast_window=10


def test_with_updates_accepts_a_valid_update() -> None:
    child = _MOMENTUM.with_updates(slow_window=30)
    assert child.slow_window == 30
    assert child.fast_window == _MOMENTUM.fast_window


def test_parameter_tune_produces_a_different_valid_spec() -> None:
    mutation = parameter_tune(_MOMENTUM, rng_for(1))
    assert mutation is not None
    assert mutation.child.family == _MOMENTUM.family
    assert mutation.child.parent_id == _MOMENTUM.config_hash()
    assert mutation.child.source == "mutation"
    changed_field = mutation.change_set["field"]
    assert getattr(mutation.child, changed_field) != getattr(_MOMENTUM, changed_field)


def test_parameter_tune_never_violates_the_family_validator() -> None:
    """Run many seeds -- every single mutation returned (not None) must
    be a genuinely valid StrategySpec, since construction went through
    _revalidated_copy, not model_copy."""
    for seed in range(200):
        mutation = parameter_tune(_MOMENTUM, rng_for(seed))
        if mutation is not None:
            assert mutation.child.slow_window > mutation.child.fast_window


def test_parameter_tune_predicted_direction_matches_window_change_direction() -> None:
    for seed in range(200):
        mutation = parameter_tune(_MOMENTUM, rng_for(seed))
        if mutation is None or "predicted_direction" not in mutation.change_set:
            continue
        old, new = mutation.change_set["old_value"], mutation.change_set["new_value"]
        if new > old:
            assert mutation.change_set["predicted_direction"] == "DECREASE"
        else:
            assert mutation.change_set["predicted_direction"] == "INCREASE"
        assert mutation.change_set["predicted_metric"] == "MAX_DRAWDOWN_PCT"


def test_parameter_tune_bollinger_field_also_works() -> None:
    mutation = parameter_tune(_BOLLINGER, rng_for(3))
    assert mutation is not None
    assert mutation.child.family == "BOLLINGER"
    assert mutation.child.lookback_window is not None and mutation.child.band_multiplier is not None


def test_swap_family_changes_family_and_carries_symbol_timeframe() -> None:
    mutation = swap_family(_MOMENTUM, rng_for(1), seed_specs_by_family=_TEMPLATES)
    assert mutation is not None
    assert mutation.child.family != _MOMENTUM.family
    assert mutation.child.symbol == _MOMENTUM.symbol
    assert mutation.child.timeframe == _MOMENTUM.timeframe
    assert mutation.child.parent_id == _MOMENTUM.config_hash()
    assert "predicted_direction" not in mutation.change_set


def test_swap_family_returns_none_with_no_other_family_templates() -> None:
    mutation = swap_family(_MOMENTUM, rng_for(1), seed_specs_by_family={"MOMENTUM": [_MOMENTUM]})
    assert mutation is None


def test_swap_family_never_picks_the_same_family() -> None:
    for seed in range(50):
        mutation = swap_family(_MOMENTUM, rng_for(seed), seed_specs_by_family=_TEMPLATES)
        assert mutation is not None
        assert mutation.child.family != "MOMENTUM"

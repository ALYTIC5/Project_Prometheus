from __future__ import annotations

import pytest
from pydantic import ValidationError

from prometheus.strategy.spec import StrategySpec


def test_valid_spec_constructs() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.family == "MOMENTUM"
    assert spec.fast_window == 5
    assert spec.parent_id is None
    assert spec.description == ""
    assert spec.source == "deterministic_grid"


def test_expected_horizon_is_required() -> None:
    """CLAUDE.md's own rule: don't invent thresholds silently -- a
    generator must state its own horizon claim, not receive a silent
    default."""
    with pytest.raises(ValidationError):
        StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)  # type: ignore[call-arg]


def test_slow_window_must_exceed_fast_window() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT",
            timeframe="1d",
            fast_window=20,
            slow_window=20,
            expected_horizon=20,
        )
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT", timeframe="1d", fast_window=20, slow_window=5, expected_horizon=20
        )


def test_spec_is_frozen() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    with pytest.raises(ValidationError):
        spec.fast_window = 10  # type: ignore[misc]


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT",
            timeframe="1d",
            fast_window=5,
            slow_window=20,
            expected_horizon=20,
            made_up_field=1,
        )


def test_parameters_mirrors_the_typed_fields() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.parameters == {"fast_window": 5.0, "slow_window": 20.0}


def test_config_hash_is_deterministic() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.config_hash() == spec.config_hash()


def test_config_hash_is_sensitive_to_every_field() -> None:
    base = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    changed = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=21, expected_horizon=20
    )
    assert base.config_hash() != changed.config_hash()


def test_config_hash_ignores_metadata_and_provenance_fields() -> None:
    """config_hash identifies BEHAVIOR, not metadata: two specs with the
    same executable parameters but different lineage/description/source/
    horizon claim are the same strategy for dedup purposes -- "this
    fingerprint prevents rediscovering the same strategy forever" would
    break the moment two mutations from different parents landing on the
    same parameters were treated as distinct."""
    base = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    same_params_different_metadata = StrategySpec(
        symbol="BTC/USDT",
        timeframe="1d",
        fast_window=5,
        slow_window=20,
        expected_horizon=50,
        parent_id="SOME-OTHER-SPEC",
        description="a different mutation entirely",
        source="mutation",
    )
    assert base.config_hash() == same_params_different_metadata.config_hash()


def test_config_hash_is_sha256_hex() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    digest = spec.config_hash()
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


def test_with_updates_applies_a_valid_change() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    child = spec.with_updates(slow_window=40)
    assert child.slow_window == 40
    assert child.fast_window == spec.fast_window
    assert spec.slow_window == 20  # the original is untouched (frozen)


def test_with_updates_re_validates_unlike_model_copy() -> None:
    """PROMPT 7's mutation/crossover code depends on this: plain
    model_copy(update=...) is documented Pydantic v2 behavior that skips
    validation entirely -- confirmed by testing it directly, not assumed.
    with_updates() must go through the real constructor instead."""
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=10, slow_window=20, expected_horizon=20
    )
    # model_copy itself really does allow this (documents the bug it
    # would otherwise be easy to reintroduce).
    invalid_via_model_copy = spec.model_copy(update={"slow_window": 5})
    assert invalid_via_model_copy.slow_window == 5  # silently invalid

    with pytest.raises(ValidationError):
        spec.with_updates(slow_window=5)

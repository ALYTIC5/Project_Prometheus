from __future__ import annotations

import pytest
from pydantic import ValidationError

from prometheus.strategy.spec import StrategySpec


def test_valid_spec_constructs() -> None:
    spec = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)
    assert spec.family == "MOMENTUM"
    assert spec.fast_window == 5


def test_slow_window_must_exceed_fast_window() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=20, slow_window=20)
    with pytest.raises(ValidationError):
        StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=20, slow_window=5)


def test_spec_is_frozen() -> None:
    spec = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)
    with pytest.raises(ValidationError):
        spec.fast_window = 10  # type: ignore[misc]


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, made_up_field=1
        )


def test_config_hash_is_deterministic() -> None:
    spec = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)
    assert spec.config_hash() == spec.config_hash()


def test_config_hash_is_sensitive_to_every_field() -> None:
    base = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)
    changed = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=21)
    assert base.config_hash() != changed.config_hash()


def test_config_hash_is_sha256_hex() -> None:
    spec = StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)
    digest = spec.config_hash()
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex

"""tests/test_rotation_spec.py"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
    ROTATION_FAMILY_DAA,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
    ROTATION_FAMILY_MIN_VARIANCE,
    ROTATION_FAMILY_PAA,
    ROTATION_FAMILY_RESIDUAL_MOMENTUM,
    ROTATION_FAMILY_RISK_PARITY,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

_SECTORS = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)


def test_equal_weight_spec_requires_no_lookback_or_top_n() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=_SECTORS,
        timeframe="1d",
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.lookback_days is None
    assert spec.top_n is None


def test_sector_momentum_requires_lookback_and_top_n() -> None:
    with pytest.raises(ValidationError, match="requires"):
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MOMENTUM,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_sector_momentum_rejects_foreign_fields() -> None:
    with pytest.raises(ValidationError, match="must not set"):
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTORS,
            timeframe="1d",
            lookback_days=63,  # EQUAL_WEIGHT never ranks -- foreign field
            top_n=3,
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_config_hash_is_stable_and_universe_order_independent() -> None:
    spec_a = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLK", "XLF", "XLE"),
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    spec_b = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLF", "XLE", "XLK"),  # same members, different order
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec_a.config_hash() == spec_b.config_hash()


def test_config_hash_changes_with_top_n() -> None:
    base = dict(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=_SECTORS,
        timeframe="1d",
        lookback_days=126,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    spec_top3 = RotationSpec(**base, top_n=3)
    spec_top5 = RotationSpec(**base, top_n=5)
    assert spec_top3.config_hash() != spec_top5.config_hash()


def test_frozen_and_extra_forbidden() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=_SECTORS,
        timeframe="1d",
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    with pytest.raises(ValidationError):
        spec.rebalance_frequency_days = 42  # frozen
    with pytest.raises(ValidationError):
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
            symbol="SPY",  # not a RotationSpec field -- extra="forbid"
        )


def test_daa_spec_requires_top_n_only() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_DAA,
        universe=("EEM", "IEF", "SPY", "QQQ", "IEF"),
        timeframe="1d",
        top_n=2,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.top_n == 2
    assert spec.lookback_days is None


def test_paa_spec_requires_lookback_top_n_and_protection_factor() -> None:
    with pytest.raises(ValidationError, match="requires"):
        RotationSpec(
            family=ROTATION_FAMILY_PAA,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_paa_non_positive_protection_factor_rejected() -> None:
    with pytest.raises(ValidationError):
        RotationSpec(
            family=ROTATION_FAMILY_PAA,
            universe=_SECTORS,
            timeframe="1d",
            lookback_days=210,
            top_n=3,
            protection_factor=0.0,
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_accelerating_dual_momentum_requires_no_params() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
        universe=("QQQ", "EFA", "IEF"),
        timeframe="1d",
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.lookback_days is None
    assert spec.top_n is None


def test_risk_parity_requires_lookback_only() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_RISK_PARITY,
        universe=_SECTORS,
        timeframe="1d",
        lookback_days=63,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.lookback_days == 63
    assert spec.top_n is None


def test_min_variance_requires_lookback_only() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_MIN_VARIANCE,
        universe=_SECTORS,
        timeframe="1d",
        lookback_days=63,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.lookback_days == 63


def test_fifty_two_week_high_requires_lookback_and_top_n() -> None:
    with pytest.raises(ValidationError, match="requires"):
        RotationSpec(
            family=ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_residual_momentum_requires_lookback_and_top_n() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_RESIDUAL_MOMENTUM,
        universe=("SPY", *_SECTORS),
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.universe[0] == "SPY"

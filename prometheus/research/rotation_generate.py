"""Grid generators for the 6 cross-sectional rotation families --
fixed, cited parameter values, pre-registered in docs/strategies/ before
this module existed. See docs/superpowers/specs/2026-09-21-cross-
sectional-rotation-design.md for the citation behind every value here.
"""
from __future__ import annotations

from collections.abc import Callable

from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

_SECTOR_UNIVERSE = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)
_GEM_UNIVERSE = ("SPY", "EFA", "TLT")  # last position is always the defensive leg
_GTAA_UNIVERSE = ("SPY", "EFA", "IEF", "VNQ", "GLD")

_MONTHLY = 21  # trading days -- this batch's own convention, and every
               # cited source's (Antonacci, Faber, Keller) own published cadence


def generate_equal_weight_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


def generate_sector_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MOMENTUM,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126, 252)
        for top_n in (3, 5)
    ]


def generate_relative_strength_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=3,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126, 252)
    ]


def generate_sector_mean_reversion_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (21, 63)
        for top_n in (3, 5)
    ]


def generate_dual_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
            universe=_GEM_UNIVERSE,
            timeframe="1d",
            lookback_days=252,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


def generate_gtaa_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_GTAA_SMA,
            universe=_GTAA_UNIVERSE,
            timeframe="1d",
            lookback_days=210,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


ROTATION_GRID_GENERATORS: tuple[Callable[[], list[RotationSpec]], ...] = (
    generate_equal_weight_grid,
    generate_sector_momentum_grid,
    generate_relative_strength_grid,
    generate_sector_mean_reversion_grid,
    generate_dual_momentum_grid,
    generate_gtaa_grid,
)

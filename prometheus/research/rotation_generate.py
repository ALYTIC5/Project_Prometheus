"""Grid generators for the 6 cross-sectional rotation families --
fixed, cited parameter values, pre-registered in docs/strategies/ before
this module existed. See docs/superpowers/specs/2026-09-21-cross-
sectional-rotation-design.md for the citation behind every value here.
"""
from __future__ import annotations

from collections.abc import Callable

from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
    ROTATION_FAMILY_DAA,
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_MIN_VARIANCE,
    ROTATION_FAMILY_PAA,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_RESIDUAL_MOMENTUM,
    ROTATION_FAMILY_RISK_PARITY,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

_SECTOR_UNIVERSE = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)
_GEM_UNIVERSE = ("SPY", "EFA", "TLT")  # last position is always the defensive leg
_GTAA_UNIVERSE = ("SPY", "EFA", "IEF", "VNQ", "GLD")

# DAA (Keller & Keuning 2016): (canary_1, canary_2, offensive_1..N, defensive).
# EEM (emerging-market equities) + IEF (intermediate treasuries) substitute for
# the paper's own VWO+BND canary pair -- the closest pair this project's
# ingested universe (config/universe_etf.yaml) actually has. IEF alone stands
# in for the paper's own 3-asset protective pool (SHY/IEF/UST), a documented
# simplification since this project ingests no ultra-short-duration Treasury
# ETF equivalent to SHY.
_DAA_UNIVERSE = (
    "EEM", "IEF",  # canary
    "SPY", "QQQ", "IWM", "EFA", "VNQ", "GLD", "TLT", "HYG", "LQD",  # offensive
    "IEF",  # defensive
)

# PAA (Keller & Keuning 2017): (offensive_1..N, defensive). Same offensive pool
# as DAA minus the canary/defensive assets, IEF as the single bond proxy.
_PAA_UNIVERSE = ("SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "GLD", "HYG", "IEF")

# Accelerating Dual Momentum (Ludlow & Hanly 2018): same (equity_legs...,
# defensive_leg) convention as DUAL_MOMENTUM_GEM, using QQQ (more aggressive
# growth exposure, matching the paper's own preference for a faster-momentum
# vehicle) alongside EFA, with IEF as the defensive leg.
_ACCELERATING_DUAL_MOMENTUM_UNIVERSE = ("QQQ", "EFA", "IEF")

# RISK_PARITY / MIN_VARIANCE: the same 11-sector universe SECTOR_MOMENTUM uses
# -- both are cross-sectional weighting schemes over the same broad pool.
_RISK_PARITY_UNIVERSE = _SECTOR_UNIVERSE
_MIN_VARIANCE_UNIVERSE = _GTAA_UNIVERSE  # 5 assets keeps covariance well-conditioned

# 52-week-high: the same 11-sector universe SECTOR_MOMENTUM uses.
_FIFTY_TWO_WEEK_HIGH_UNIVERSE = _SECTOR_UNIVERSE

# RESIDUAL_MOMENTUM: (benchmark_symbol, pool...) -- SPY as the market proxy,
# the 11 sector SPDRs as the ranked pool (never itself held).
_RESIDUAL_MOMENTUM_UNIVERSE = ("SPY", *_SECTOR_UNIVERSE)

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


def generate_daa_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_DAA,
            universe=_DAA_UNIVERSE,
            timeframe="1d",
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for top_n in (1, 2, 6)  # Keller & Keuning's own G1/G2/G6 breadth variants
    ]


def generate_paa_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_PAA,
            universe=_PAA_UNIVERSE,
            timeframe="1d",
            lookback_days=210,  # 10-month SMA, Faber/Keller's own shared convention
            top_n=top_n,
            protection_factor=a,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for top_n in (1, 6)
        for a in (0.5, 1.0, 2.0)  # the paper's own explicitly-varied "a" range
    ]


def generate_accelerating_dual_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
            universe=_ACCELERATING_DUAL_MOMENTUM_UNIVERSE,
            timeframe="1d",
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


def generate_risk_parity_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_RISK_PARITY,
            universe=_RISK_PARITY_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126)
    ]


def generate_min_variance_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_MIN_VARIANCE,
            universe=_MIN_VARIANCE_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126)
    ]


def generate_fifty_two_week_high_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
            universe=_FIFTY_TWO_WEEK_HIGH_UNIVERSE,
            timeframe="1d",
            lookback_days=252,  # George & Hwang's own 52-week (canonical, not swept)
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for top_n in (3, 5)
    ]


def generate_residual_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_RESIDUAL_MOMENTUM,
            universe=_RESIDUAL_MOMENTUM_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=3,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126, 252)
    ]


ROTATION_GRID_GENERATORS: tuple[Callable[[], list[RotationSpec]], ...] = (
    generate_equal_weight_grid,
    generate_sector_momentum_grid,
    generate_relative_strength_grid,
    generate_sector_mean_reversion_grid,
    generate_dual_momentum_grid,
    generate_gtaa_grid,
    generate_daa_grid,
    generate_paa_grid,
    generate_accelerating_dual_momentum_grid,
    generate_risk_parity_grid,
    generate_min_variance_grid,
    generate_fifty_two_week_high_grid,
    generate_residual_momentum_grid,
)

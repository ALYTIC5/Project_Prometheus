"""Cross-sectional rotation strategies -- multi-asset, ranking a
UNIVERSE rather than trading one symbol. Deliberately a separate model
from StrategySpec, not an extension of it: StrategySpec.symbol is
required and read directly throughout backtest/engine.py's dispatch,
core.ids' seed derivation, and config_hash's identity fields across all
17 already-shipped single-symbol families -- making it conditional would
risk regressing those for a family type that shares none of their
execution model. See docs/superpowers/specs/2026-09-21-cross-sectional-
rotation-design.md for the full design.

Six families, all cited (Jegadeesh & Titman 1993, De Bondt & Thaler
1985, Antonacci 2014, Faber 2007) or this batch's own explicit
convention (equal-weight baseline, monthly = 21-trading-day rebalance).
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, model_validator

ROTATION_FAMILY_SECTOR_MOMENTUM = "SECTOR_MOMENTUM_ROTATION"
ROTATION_FAMILY_DUAL_MOMENTUM_GEM = "DUAL_MOMENTUM_GEM"
ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3 = "RELATIVE_STRENGTH_TOP3"
ROTATION_FAMILY_SECTOR_MEAN_REVERSION = "SECTOR_MEAN_REVERSION"
ROTATION_FAMILY_GTAA_SMA = "GTAA_SMA_TIMING"
ROTATION_FAMILY_EQUAL_WEIGHT = "EQUAL_WEIGHT_BASELINE"
ROTATION_FAMILY_DAA = "DEFENSIVE_ASSET_ALLOCATION"
ROTATION_FAMILY_PAA = "PROTECTIVE_ASSET_ALLOCATION"
ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM = "ACCELERATING_DUAL_MOMENTUM"
ROTATION_FAMILY_RISK_PARITY = "RISK_PARITY_INVERSE_VOL"
ROTATION_FAMILY_MIN_VARIANCE = "MINIMUM_VARIANCE"
ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH = "FIFTY_TWO_WEEK_HIGH"
ROTATION_FAMILY_RESIDUAL_MOMENTUM = "RESIDUAL_MOMENTUM"

ROTATION_FAMILIES = (
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_DAA,
    ROTATION_FAMILY_PAA,
    ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
    ROTATION_FAMILY_RISK_PARITY,
    ROTATION_FAMILY_MIN_VARIANCE,
    ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
    ROTATION_FAMILY_RESIDUAL_MOMENTUM,
)

# Which optional fields each family actually reads -- a model_validator
# below enforces a spec never carries a field its own family doesn't use,
# same discipline StrategySpec's _FAMILY_PARAMS/_params_match_family uses.
_FAMILY_PARAMS: dict[str, tuple[str, ...]] = {
    ROTATION_FAMILY_SECTOR_MOMENTUM: ("lookback_days", "top_n"),
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM: ("lookback_days",),
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3: ("lookback_days", "top_n"),
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION: ("lookback_days", "top_n"),
    ROTATION_FAMILY_GTAA_SMA: ("lookback_days",),
    ROTATION_FAMILY_EQUAL_WEIGHT: (),
    # DAA (Keller & Keuning 2016): universe = (canary_1, canary_2,
    # offensive_1, ..., offensive_N, defensive). top_n is the "breadth"
    # B parameter; the 13612W momentum sub-lookbacks (1/3/6/12 months)
    # are fixed by the construction's own definition, not swept.
    ROTATION_FAMILY_DAA: ("top_n",),
    # PAA (Keller & Keuning 2017): universe = (offensive_1, ...,
    # offensive_N, defensive). protection_factor is the paper's own
    # explicitly-varied "a" parameter; lookback_days is the SMA window.
    ROTATION_FAMILY_PAA: ("lookback_days", "top_n", "protection_factor"),
    # Accelerating Dual Momentum (Ludlow & Hanly 2018): universe =
    # (equity_leg_1, ..., equity_leg_N, defensive_leg), same convention
    # as DUAL_MOMENTUM_GEM. The 1/3/6-month sub-lookbacks are fixed by
    # the construction's own definition, not swept.
    ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM: (),
    ROTATION_FAMILY_RISK_PARITY: ("lookback_days",),
    ROTATION_FAMILY_MIN_VARIANCE: ("lookback_days",),
    ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH: ("lookback_days", "top_n"),
    # RESIDUAL_MOMENTUM: universe = (benchmark_symbol, pool_1, ..., pool_N).
    ROTATION_FAMILY_RESIDUAL_MOMENTUM: ("lookback_days", "top_n"),
}
_ALL_PARAM_FIELDS = ("lookback_days", "top_n", "protection_factor")

# config_hash()'s identity fields -- everything that changes this spec's
# actual backtested BEHAVIOR. parent_id/description/source are
# provenance, not behavior, same exclusion StrategySpec.config_hash()
# already makes.
_IDENTITY_FIELDS = (
    "family", "universe", "timeframe", "lookback_days", "top_n",
    "protection_factor", "rebalance_frequency_days", "expected_horizon",
)


class RotationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str
    universe: tuple[str, ...]
    timeframe: str
    lookback_days: int | None = None
    top_n: int | None = None
    # PAA's own "protection factor" (a): Keller & Keuning's paper
    # explicitly varies this itself (a=0..2), so sweeping it is not an
    # invented threshold -- it's the cited source's own design axis.
    protection_factor: float | None = None
    rebalance_frequency_days: int
    expected_horizon: int

    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"

    @model_validator(mode="after")
    def _params_match_family(self) -> RotationSpec:
        if self.family not in _FAMILY_PARAMS:
            raise ValueError(f"unknown rotation family: {self.family!r}")
        if not self.universe:
            raise ValueError("universe must be non-empty")
        required = _FAMILY_PARAMS[self.family]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"family {self.family!r} requires {missing}")
        foreign = [
            f for f in _ALL_PARAM_FIELDS
            if f not in required and getattr(self, f) is not None
        ]
        if foreign:
            raise ValueError(f"family {self.family!r} must not set {foreign}")
        if self.rebalance_frequency_days <= 0:
            raise ValueError("rebalance_frequency_days must be positive")
        if self.lookback_days is not None and self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if self.top_n is not None and not (0 < self.top_n <= len(self.universe)):
            raise ValueError("top_n must be in (0, len(universe)]")
        if self.protection_factor is not None and self.protection_factor <= 0.0:
            raise ValueError("protection_factor must be positive")
        return self

    def config_hash(self) -> str:
        """Same pattern as StrategySpec.config_hash() -- a stable hash of
        canonical content. `universe` is sorted before hashing so member
        ORDER never changes identity (a grid generator building the tuple
        from a set, or a caller passing it in a different order, must not
        silently mint a second, spuriously-distinct spec for the same
        actual strategy)."""
        canonical = self.model_dump(include=set(_IDENTITY_FIELDS))
        canonical["universe"] = sorted(canonical["universe"])
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

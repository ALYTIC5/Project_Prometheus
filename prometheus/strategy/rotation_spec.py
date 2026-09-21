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

ROTATION_FAMILIES = (
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_EQUAL_WEIGHT,
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
}
_ALL_PARAM_FIELDS = ("lookback_days", "top_n")

# config_hash()'s identity fields -- everything that changes this spec's
# actual backtested BEHAVIOR. parent_id/description/source are
# provenance, not behavior, same exclusion StrategySpec.config_hash()
# already makes.
_IDENTITY_FIELDS = (
    "family", "universe", "timeframe", "lookback_days", "top_n",
    "rebalance_frequency_days", "expected_horizon",
)


class RotationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str
    universe: tuple[str, ...]
    timeframe: str
    lookback_days: int | None = None
    top_n: int | None = None
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

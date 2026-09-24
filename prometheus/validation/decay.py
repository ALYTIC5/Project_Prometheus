"""IC at multiple horizons -- PROMPTS.md's own framing: "does the strategy
have power at the horizon it CLAIMS", not just somewhere. Classification
only, never an automatic rejection; validation/decision.py decides what a
DecayProfile means for a verdict, this module only measures it.
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from prometheus.strategy.spec import StrategySpec
from prometheus.validation.metrics import (
    information_coefficient,
    information_coefficient_with_pvalue,
    signal_frame_or_none,
)

# Bars, not calendar days -- at the deterministic grid's 1d timeframe these
# happen to coincide, documented rather than silently assumed. Exact list
# PROMPTS.md names for PROMPT 5.
DECAY_HORIZONS = (1, 2, 3, 5, 10, 20, 30, 50, 100)

# Two-tailed p<0.05 -- the standard significance convention, same z=1.96
# class of "cited constant, not an invented validation threshold" the null
# suite (tests/test_null_strategies.py) already uses.
_SIGNIFICANCE_P_VALUE = 0.05


@dataclass(frozen=True)
class DecayProfile:
    ic_by_horizon: dict[int, float | None]
    claimed_horizon: int
    claimed_horizon_ic: float | None
    claimed_horizon_p_value: float | None
    # None: not enough data at the claimed horizon to judge either way --
    # distinct from False (judged, and found not significant).
    has_power_at_claimed_horizon: bool | None


_UNCOMPUTED = object()  # sentinel: "caller didn't pass one, compute it yourself"


def compute_decay(
    bars: pl.DataFrame, spec: StrategySpec, *, signaled: pl.DataFrame | None = _UNCOMPUTED  # type: ignore[assignment]
) -> DecayProfile:
    """`signaled` lets a caller that already called signal_frame_or_none
    for this spec (experiments/runner.py, sharing it with compute_metrics)
    pass the result straight through -- this function used to call
    signal_for() 10 times per spec (once per DECAY_HORIZONS entry plus
    the claimed horizon), on top of compute_metrics's own 2 calls; see
    metrics.py's signal_frame_or_none docstring for the 2026-09-24
    incident that made this matter (harmless at 4 working families,
    expensive enough at 47 to stall the research concern in production).
    Omit it (the default sentinel) to compute it once internally here,
    unchanged behavior for every existing caller/test."""
    resolved_signaled = signal_frame_or_none(bars, spec) if signaled is _UNCOMPUTED else signaled

    ic_by_horizon = {
        h: information_coefficient(bars, spec, h, signaled=resolved_signaled)
        for h in DECAY_HORIZONS
    }

    claimed = spec.expected_horizon
    claimed_result = information_coefficient_with_pvalue(
        bars, spec, claimed, signaled=resolved_signaled
    )
    if claimed not in ic_by_horizon:
        ic_by_horizon[claimed] = claimed_result[0] if claimed_result is not None else None

    if claimed_result is None:
        claimed_ic, claimed_p_value, has_power = None, None, None
    else:
        claimed_ic, claimed_p_value = claimed_result
        has_power = claimed_p_value < _SIGNIFICANCE_P_VALUE

    return DecayProfile(
        ic_by_horizon=ic_by_horizon,
        claimed_horizon=claimed,
        claimed_horizon_ic=claimed_ic,
        claimed_horizon_p_value=claimed_p_value,
        has_power_at_claimed_horizon=has_power,
    )

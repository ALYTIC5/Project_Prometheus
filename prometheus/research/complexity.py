"""Parameter-complexity scoring -- PROMPT 7. Feeds ONLY
`prioritisation.py`'s queue ordering -- does not touch `validation/
scoring.py`'s already-shipped, already-tested validation scoring. A much
smaller blast radius than reopening validation math this late.

The reasoning: more free parameters means more overfitting surface --
the literal reason CLAUDE.md's falsification-first rule exists ("the
leakage detectors, the null-strategy suite and the cost model must be
green before any strategy generator runs"). A simple, monotonic,
documented penalty, not a fitted or invented curve.
"""
from __future__ import annotations

from prometheus.strategy.spec import StrategySpec


def parameter_count(spec: StrategySpec) -> int:
    """The spec's own family-specific parameter count -- `spec.parameters`
    is already the real, family-agnostic view (strategy/spec.py); not
    duplicated here."""
    return len(spec.parameters)


def complexity_penalty(spec: StrategySpec) -> float:
    """The raw parameter count, as a float -- linear and unscaled. No
    invented per-parameter cost coefficient: CLAUDE.md forbids inventing
    numeric thresholds, and every one of PROMPT 7's families has exactly
    2 parameters today (see strategy/spec.py's `_FAMILY_PARAMS`), so
    there is no real data yet to justify any particular curve or weight.
    `prioritisation.py` is responsible for normalizing this against the
    real, derived max parameter count across `FAMILIES` -- not this
    module inventing a scale of its own."""
    return float(parameter_count(spec))

"""Queue prioritisation -- PROMPT 7. Feeds the REAL, already-existing
`jobs.expected_information_value` column: `experiments/queue.py`'s
`enqueue()` already accepts it and orders `claim()`'s `ORDER BY priority
DESC, expected_information_value DESC, ...`; every caller today just
hardcodes 0.0. This module is that column's first real producer.
"""
from __future__ import annotations

from dataclasses import dataclass

from prometheus.research.complexity import complexity_penalty
from prometheus.research.population import STRATEGY_STATES
from prometheus.strategy.spec import StrategySpec

# The one selection mode (of population.py's five) this module treats
# specially -- matches population.select_for_diversification's own name,
# not a fresh vocabulary invented here.
DIVERSIFICATION_MODE = "diversification"


@dataclass(frozen=True)
class ParentContext:
    """What's known about the parent a candidate was generated from.
    `parent_status` is None for a fresh grid-search spec (no parent);
    `mode` is one of population.py's five selection-function names, or
    None when the candidate didn't come from a selection function at
    all (e.g. the deterministic grid)."""
    parent_status: str | None
    mode: str | None


def _status_term(status: str | None) -> float:
    """1.0 for the best real lifecycle state (CHAMPION), 0.0 for the
    worst (RETIRED) -- a real value derived from population.py's own
    declared STRATEGY_STATES ordering (CHAMPION > VALIDATED > PROMISING
    > ... > RETIRED), not an invented per-status weight. No parent
    (fresh grid spec) gets the midpoint: neither favored nor penalized
    for provenance it doesn't have."""
    if status is None or status not in STRATEGY_STATES:
        return 0.5
    index = STRATEGY_STATES.index(status)
    return 1.0 - index / (len(STRATEGY_STATES) - 1)


def _mode_term(mode: str | None) -> float:
    """A candidate from population.select_for_diversification is
    explicitly filling a real, measured gap in the population's own
    parameter coverage (that function's own distance-from-centroid
    selection) -- worth a real boost. No other mode gets one:
    exploitation/revival/cross_breeding already carry their signal
    through _status_term (all three select on status), and exploration
    is uniform-random by design, so a term for it would just be noise."""
    return 1.0 if mode == DIVERSIFICATION_MODE else 0.0


def expected_information_value(spec: StrategySpec, parent: ParentContext) -> float:
    """Three real, derived terms, no invented magic constant: parent
    status quality (0..1, from the real lifecycle ordering),
    diversification-mode boost (0 or 1), and this child's own complexity
    penalty (>=0, from complexity.py, subtracted). Every PROMPT 7 family
    has the same parameter count today (see complexity.py's docstring),
    so the complexity term is currently a constant offset with no
    ordering effect between candidates -- it starts differentiating them
    the moment a family with a different parameter count exists, without
    this function changing."""
    return _status_term(parent.parent_status) + _mode_term(parent.mode) - complexity_penalty(spec)

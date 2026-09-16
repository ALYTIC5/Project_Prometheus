"""Deterministic strategy generation -- a parameter grid, not an LLM.

CLAUDE.md's own null hypothesis: LLM-generated research is assumed to
lose to static baselines until proven otherwise, and the repo layout's own
comment says "generators (deterministic first, llm later)". This is the
"deterministic first."
"""
from __future__ import annotations

from prometheus.strategy.spec import StrategySpec

_FAST_WINDOWS = (5, 10, 20)
_SLOW_WINDOWS = (20, 50, 100)


def generate_grid(symbol: str, timeframe: str, family: str = "MOMENTUM") -> list[StrategySpec]:
    """Every (fast, slow) pair with slow > fast -- a small, fully
    enumerated, reproducible grid, not a random sample."""
    specs = []
    for fast in _FAST_WINDOWS:
        for slow in _SLOW_WINDOWS:
            if slow <= fast:
                continue
            specs.append(
                StrategySpec(
                    family=family,
                    symbol=symbol,
                    timeframe=timeframe,
                    fast_window=fast,
                    slow_window=slow,
                    # The strategy's own already-chosen slow window IS its
                    # horizon claim -- an SMA crossover's signal is only
                    # meant to matter over roughly that many bars. Not an
                    # arbitrary number: it's read from the spec's own
                    # parameters, not invented separately from them.
                    expected_horizon=slow,
                )
            )
    return specs

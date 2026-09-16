"""Deterministic strategy generation -- a parameter grid, not an LLM.

CLAUDE.md's own null hypothesis: LLM-generated research is assumed to
lose to static baselines until proven otherwise, and the repo layout's own
comment says "generators (deterministic first, llm later)". This is the
"deterministic first."

`generate_baseline_grid` combines all three real families (PROMPT 6) --
this combined, multi-template set IS "the deterministic parameter grid
search over classic templates" PROMPTS.md names as the first component
experiments/ablation.py's ComponentRegistry registers; every future
component (Prompt 7's evolution, Prompt 9's LLM layer) has to beat this.
"""
from __future__ import annotations

from prometheus.strategy.spec import (
    FAMILY_BOLLINGER,
    FAMILY_MOMENTUM,
    FAMILY_VOL_BREAKOUT,
    StrategySpec,
)

_FAST_WINDOWS = (5, 10, 20)
_SLOW_WINDOWS = (20, 50, 100)

# John Bollinger's own standard default (20-bar lookback, 2 std) plus two
# nearby, still-standard variants -- not invented, a small enumerated grid
# the same way the momentum fast/slow grid is.
_BOLLINGER_LOOKBACKS = (10, 20, 30)
_BOLLINGER_MULTIPLIERS = (1.5, 2.0, 2.5)

# Turtle Trading's own two classic systems used 20/10 and 55/20
# (entry/exit) -- both included, plus one closer-spaced pair.
_BREAKOUT_ENTRY_EXIT_PAIRS = ((20, 10), (55, 20), (30, 15))


def generate_grid(symbol: str, timeframe: str, family: str = FAMILY_MOMENTUM) -> list[StrategySpec]:
    """MOMENTUM's own (fast, slow) grid -- every pair with slow > fast, a
    small fully enumerated set, not a random sample. `family` only ever
    accepts FAMILY_MOMENTUM (kept as a parameter for the existing
    experiments/runner.py call sites' signatures, not because this
    function generates anything else) -- StrategySpec's own per-family
    validator would reject a MOMENTUM-shaped (fast_window/slow_window)
    spec claiming any other family anyway, so this fails loudly rather
    than silently for anything else."""
    if family != FAMILY_MOMENTUM:
        raise ValueError(f"generate_grid only produces {FAMILY_MOMENTUM} specs, got {family!r}")
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


def generate_bollinger_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _BOLLINGER_LOOKBACKS:
        for multiplier in _BOLLINGER_MULTIPLIERS:
            specs.append(
                StrategySpec(
                    family=FAMILY_BOLLINGER,
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_window=lookback,
                    band_multiplier=multiplier,
                    # Same rule as MOMENTUM: a mean-reversion signal's own
                    # lookback IS its horizon claim.
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_vol_breakout_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for breakout_window, exit_window in _BREAKOUT_ENTRY_EXIT_PAIRS:
        specs.append(
            StrategySpec(
                family=FAMILY_VOL_BREAKOUT,
                symbol=symbol,
                timeframe=timeframe,
                breakout_window=breakout_window,
                exit_window=exit_window,
                expected_horizon=breakout_window,
            )
        )
    return specs


def generate_baseline_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    """Every classic-template family's grid, combined -- the full
    baseline every future component must beat. Carry (PROMPTS.md's
    fourth named template) is deliberately absent: it needs futures
    funding-rate/basis data this project's spot-only ccxt pipeline
    doesn't ingest (docs/DEFERRED.md)."""
    return [
        *generate_grid(symbol, timeframe),
        *generate_bollinger_grid(symbol, timeframe),
        *generate_vol_breakout_grid(symbol, timeframe),
    ]

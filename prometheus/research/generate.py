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
    FAMILY_KELTNER,
    FAMILY_MACD,
    FAMILY_MOMENTUM,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RSI,
    FAMILY_STOCHASTIC,
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

# Wilder's own default RSI lookback is 14 -- included with one shorter
# and one longer still-standard variant, plus Wilder's classic 30
# oversold level with two nearby, still-standard variants.
_RSI_LOOKBACKS = (7, 14, 21)
_RSI_OVERSOLD_LEVELS = (20.0, 25.0, 30.0)

# Gerald Appel's own default (12, 26, 9) plus two commonly cited faster
# variants (8/17/9 and 5/13/5, both standard alternate MACD
# configurations for shorter-term signals, not invented).
_MACD_PARAM_SETS = ((12, 26, 9), (8, 17, 9), (5, 13, 5))

# Lane's own Stochastic Oscillator default (14-bar lookback) plus two
# nearby variants, with the classic oversold level (20, sometimes cited
# as 25) plus one more conservative variant -- same grid shape RSI uses.
_STOCH_LOOKBACKS = (7, 14, 21)
_STOCH_OVERSOLD_LEVELS = (15.0, 20.0, 25.0)

# Wilder's own classic default (0.02 start/increment, 0.2 cap) plus a
# slower/conservative and a faster/aggressive variant -- three cited
# parameter sets, same enumerated-not-cross-product shape MACD uses.
_SAR_PARAM_SETS = ((0.02, 0.02, 0.2), (0.01, 0.01, 0.1), (0.03, 0.03, 0.3))

# A 20-period EMA/ATR with a 2.0x multiplier is the standard modern
# Keltner Channel default (Linda Bradford Raschke's ATR-based variant),
# plus nearby lookback/multiplier variants -- same grid shape BOLLINGER
# uses (they are, not coincidentally, the same channel-width family of
# indicator).
_KELTNER_LOOKBACKS = (10, 20, 30)
_KELTNER_MULTIPLIERS = (1.5, 2.0, 2.5)


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


def generate_rsi_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _RSI_LOOKBACKS:
        for oversold in _RSI_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_RSI,
                    symbol=symbol,
                    timeframe=timeframe,
                    rsi_lookback=lookback,
                    rsi_oversold=oversold,
                    # Same rule as BOLLINGER: a mean-reversion signal's
                    # own lookback IS its horizon claim.
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_macd_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for fast, slow, signal in _MACD_PARAM_SETS:
        specs.append(
            StrategySpec(
                family=FAMILY_MACD,
                symbol=symbol,
                timeframe=timeframe,
                macd_fast=fast,
                macd_slow=slow,
                macd_signal=signal,
                # Same rule as MOMENTUM: the slower EMA IS the horizon claim.
                expected_horizon=slow,
            )
        )
    return specs


def generate_stochastic_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _STOCH_LOOKBACKS:
        for oversold in _STOCH_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_STOCHASTIC,
                    symbol=symbol,
                    timeframe=timeframe,
                    stoch_lookback=lookback,
                    stoch_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_parabolic_sar_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for af_start, af_increment, af_max in _SAR_PARAM_SETS:
        specs.append(
            StrategySpec(
                family=FAMILY_PARABOLIC_SAR,
                symbol=symbol,
                timeframe=timeframe,
                sar_af_start=af_start,
                sar_af_increment=af_increment,
                sar_af_max=af_max,
                # SAR has no lookback window of its own -- its horizon
                # claim is a fixed, modest number of bars (a trend
                # reversal is meant to matter over the near term, not a
                # window this spec's own parameters happen to encode).
                expected_horizon=10,
            )
        )
    return specs


def generate_keltner_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _KELTNER_LOOKBACKS:
        for multiplier in _KELTNER_MULTIPLIERS:
            specs.append(
                StrategySpec(
                    family=FAMILY_KELTNER,
                    symbol=symbol,
                    timeframe=timeframe,
                    keltner_lookback=lookback,
                    keltner_multiplier=multiplier,
                    expected_horizon=lookback,
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
        *generate_rsi_grid(symbol, timeframe),
        *generate_macd_grid(symbol, timeframe),
        *generate_stochastic_grid(symbol, timeframe),
        *generate_parabolic_sar_grid(symbol, timeframe),
        *generate_keltner_grid(symbol, timeframe),
    ]

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
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_GAP_FADE,
    FAMILY_IBS,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_MACD,
    FAMILY_MFI,
    FAMILY_MOMENTUM,
    FAMILY_N_DAY_LOW,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RSI,
    FAMILY_SMA_DISTANCE,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_TRIX,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_VOL_BREAKOUT,
    FAMILY_WILLIAMS_R,
    FAMILY_ZSCORE,
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

# Larry Williams' own default (14-bar lookback, -80 -- 80% of the true
# range down from the highest high -- is Williams' own classic oversold
# level) plus two nearby, still-standard variants, same grid shape RSI/
# STOCHASTIC use.
_WILLIAMS_LOOKBACKS = (7, 14, 21)
_WILLIAMS_OVERSOLD_LEVELS = (-70.0, -80.0, -90.0)

# Donald Lambert's own default (20-bar lookback) plus two nearby
# variants, with Lambert's own -100 reversal zone plus two nearby
# variants -- same grid shape RSI/STOCHASTIC use.
_CCI_LOOKBACKS = (10, 20, 30)
_CCI_OVERSOLD_LEVELS = (-80.0, -100.0, -150.0)

# Bill Williams' own fixed 5/34 default is the only cited configuration
# for this specific indicator (unlike MACD, there is no well-known
# "alternate AO" convention) -- two nearby variants included anyway, for
# the same reason every other family's grid explores more than one
# point even around a single canonical default.
_AO_PARAM_SETS = ((5, 34), (3, 21), (8, 55))

# Olivier Seban's own commonly-cited default (10-bar ATR, 3.0x
# multiplier) plus two nearby variants -- same grid shape KELTNER uses
# (both are ATR-band constructions).
_SUPERTREND_LOOKBACKS = (7, 10, 14)
_SUPERTREND_MULTIPLIERS = (2.0, 3.0, 4.0)

# TRIX has no single universally-cited default the way Wilder's RSI
# does; 15 is the most commonly seen period in practitioner literature,
# included with two nearby variants -- same grid shape RSI uses.
_TRIX_LOOKBACKS = (9, 15, 21)

# Larry Connors' own published RSI(2) construction ("Short-Term Trading
# Strategies That Work", 2008): a 2-period RSI, extreme oversold
# thresholds (well below Wilder's classic 30) -- 10 and 5 are Connors'
# own two most commonly cited variants.
_RSI2_OVERSOLD_LEVELS = (10.0, 5.0)

# Same grid shape KELTNER's own breakout bands use -- KELTNER_REVERSION
# is the identical ATR-band construction, just the opposite direction.
_KELTNER_REVERSION_LOOKBACKS = (10, 20, 30)
_KELTNER_REVERSION_MULTIPLIERS = (1.5, 2.0, 2.5)

# Same lookback/band shape BOLLINGER uses; %B's own oversold threshold
# is a fraction of the band width (0.2 and 0.0 are John Bollinger's own
# commonly cited "near/at the lower band" zones).
_PCTB_LOOKBACKS = (10, 20, 30)
_PCTB_MULTIPLIERS = (1.5, 2.0, 2.5)
_PCTB_OVERSOLD_LEVELS = (0.2, 0.0)

_ZSCORE_LOOKBACKS = (10, 20, 30)
_ZSCORE_OVERSOLD_LEVELS = (-1.5, -2.0, -2.5)

# IBS has no lookback (a single-bar ratio); 0.2 and 0.1 are the
# commonly cited "near the day's low" thresholds in the IBS literature.
_IBS_OVERSOLD_LEVELS = (0.2, 0.1)

_N_DAY_LOW_LOOKBACKS = (10, 20, 50)

_CONSECUTIVE_DOWN_RUN_LENGTHS = (2, 3, 4)

# The classic use case is a 200-day SMA; 50 and 100 are included as
# nearby, shorter-horizon variants of the same distance-from-trend
# construction.
_SMA_DISTANCE_LOOKBACKS = (50, 100, 200)
_SMA_DISTANCE_OVERSOLD_LEVELS = (0.05, 0.1)

# Larry Williams' own published 7/14/28 Ultimate Oscillator convention --
# a single fixed triple, not a swept grid dimension, since the 4:2:1
# weighting is itself defined relative to this exact ratio.
_UO_WINDOWS = (7, 14, 28)
_UO_OVERSOLD_LEVELS = (30.0, 20.0)

_MFI_LOOKBACKS = (14, 21)
_MFI_OVERSOLD_LEVELS = (20.0, 30.0)

_GAP_FADE_THRESHOLDS = (0.01, 0.02, 0.03)


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


def generate_williams_r_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _WILLIAMS_LOOKBACKS:
        for oversold in _WILLIAMS_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_WILLIAMS_R,
                    symbol=symbol,
                    timeframe=timeframe,
                    williams_lookback=lookback,
                    williams_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_cci_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _CCI_LOOKBACKS:
        for oversold in _CCI_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_CCI,
                    symbol=symbol,
                    timeframe=timeframe,
                    cci_lookback=lookback,
                    cci_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_awesome_oscillator_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for fast, slow in _AO_PARAM_SETS:
        specs.append(
            StrategySpec(
                family=FAMILY_AWESOME_OSCILLATOR,
                symbol=symbol,
                timeframe=timeframe,
                ao_fast=fast,
                ao_slow=slow,
                expected_horizon=slow,
            )
        )
    return specs


def generate_supertrend_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _SUPERTREND_LOOKBACKS:
        for multiplier in _SUPERTREND_MULTIPLIERS:
            specs.append(
                StrategySpec(
                    family=FAMILY_SUPERTREND,
                    symbol=symbol,
                    timeframe=timeframe,
                    supertrend_lookback=lookback,
                    supertrend_multiplier=multiplier,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_trix_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _TRIX_LOOKBACKS:
        specs.append(
            StrategySpec(
                family=FAMILY_TRIX,
                symbol=symbol,
                timeframe=timeframe,
                trix_lookback=lookback,
                expected_horizon=lookback,
            )
        )
    return specs


def generate_rsi2_connors_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    """Larry Connors' own RSI(2) construction (STRATEGIES_100.md #21) --
    a distinct, cited parameter regime from the classic RSI grid above
    (2-period lookback, extreme <10 oversold zones vs Wilder's classic
    30), pre-registered as its own grid rather than silently folded into
    _RSI_LOOKBACKS -- widening an existing family's grid range after the
    fact is exactly the p-hacking Law 7/docs/strategies/README.md's
    pre-registration convention exists to prevent; this is a genuinely
    new, separately-cited grid, not a widening of the old one."""
    specs = []
    for oversold in _RSI2_OVERSOLD_LEVELS:
        specs.append(
            StrategySpec(
                family=FAMILY_RSI,
                symbol=symbol,
                timeframe=timeframe,
                rsi_lookback=2,
                rsi_oversold=oversold,
                expected_horizon=2,
            )
        )
    return specs


def generate_keltner_reversion_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _KELTNER_REVERSION_LOOKBACKS:
        for multiplier in _KELTNER_REVERSION_MULTIPLIERS:
            specs.append(
                StrategySpec(
                    family=FAMILY_KELTNER_REVERSION,
                    symbol=symbol,
                    timeframe=timeframe,
                    keltner_rev_lookback=lookback,
                    keltner_rev_multiplier=multiplier,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_bollinger_pctb_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _PCTB_LOOKBACKS:
        for multiplier in _PCTB_MULTIPLIERS:
            for oversold in _PCTB_OVERSOLD_LEVELS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_BOLLINGER_PCTB,
                        symbol=symbol,
                        timeframe=timeframe,
                        pctb_lookback=lookback,
                        pctb_multiplier=multiplier,
                        pctb_oversold=oversold,
                        expected_horizon=lookback,
                    )
                )
    return specs


def generate_zscore_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _ZSCORE_LOOKBACKS:
        for oversold in _ZSCORE_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_ZSCORE,
                    symbol=symbol,
                    timeframe=timeframe,
                    zscore_lookback=lookback,
                    zscore_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_ibs_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for oversold in _IBS_OVERSOLD_LEVELS:
        specs.append(
            StrategySpec(
                family=FAMILY_IBS,
                symbol=symbol,
                timeframe=timeframe,
                ibs_oversold=oversold,
                # IBS is a single-bar ratio -- its own horizon claim is
                # the shortest meaningful one, one bar ahead.
                expected_horizon=1,
            )
        )
    return specs


def generate_n_day_low_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _N_DAY_LOW_LOOKBACKS:
        specs.append(
            StrategySpec(
                family=FAMILY_N_DAY_LOW,
                symbol=symbol,
                timeframe=timeframe,
                ndaylow_lookback=lookback,
                expected_horizon=lookback,
            )
        )
    return specs


def generate_consecutive_down_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for run_length in _CONSECUTIVE_DOWN_RUN_LENGTHS:
        specs.append(
            StrategySpec(
                family=FAMILY_CONSECUTIVE_DOWN,
                symbol=symbol,
                timeframe=timeframe,
                consecutive_down_days=run_length,
                expected_horizon=run_length,
            )
        )
    return specs


def generate_sma_distance_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _SMA_DISTANCE_LOOKBACKS:
        for oversold in _SMA_DISTANCE_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_SMA_DISTANCE,
                    symbol=symbol,
                    timeframe=timeframe,
                    sma_dist_lookback=lookback,
                    sma_dist_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_ultimate_oscillator_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    short, mid, long = _UO_WINDOWS
    specs = []
    for oversold in _UO_OVERSOLD_LEVELS:
        specs.append(
            StrategySpec(
                family=FAMILY_ULTIMATE_OSCILLATOR,
                symbol=symbol,
                timeframe=timeframe,
                uo_short=short,
                uo_mid=mid,
                uo_long=long,
                uo_oversold=oversold,
                expected_horizon=mid,
            )
        )
    return specs


def generate_mfi_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for lookback in _MFI_LOOKBACKS:
        for oversold in _MFI_OVERSOLD_LEVELS:
            specs.append(
                StrategySpec(
                    family=FAMILY_MFI,
                    symbol=symbol,
                    timeframe=timeframe,
                    mfi_lookback=lookback,
                    mfi_oversold=oversold,
                    expected_horizon=lookback,
                )
            )
    return specs


def generate_gap_fade_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for threshold in _GAP_FADE_THRESHOLDS:
        specs.append(
            StrategySpec(
                family=FAMILY_GAP_FADE,
                symbol=symbol,
                timeframe=timeframe,
                gap_fade_threshold=threshold,
                # A gap-fade signal's own claim is intraday-to-next-close,
                # the shortest meaningful horizon.
                expected_horizon=1,
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
        *generate_williams_r_grid(symbol, timeframe),
        *generate_cci_grid(symbol, timeframe),
        *generate_awesome_oscillator_grid(symbol, timeframe),
        *generate_supertrend_grid(symbol, timeframe),
        *generate_trix_grid(symbol, timeframe),
        *generate_rsi2_connors_grid(symbol, timeframe),
        *generate_keltner_reversion_grid(symbol, timeframe),
        *generate_bollinger_pctb_grid(symbol, timeframe),
        *generate_zscore_grid(symbol, timeframe),
        *generate_ibs_grid(symbol, timeframe),
        *generate_n_day_low_grid(symbol, timeframe),
        *generate_consecutive_down_grid(symbol, timeframe),
        *generate_sma_distance_grid(symbol, timeframe),
        *generate_ultimate_oscillator_grid(symbol, timeframe),
        *generate_mfi_grid(symbol, timeframe),
        *generate_gap_fade_grid(symbol, timeframe),
    ]

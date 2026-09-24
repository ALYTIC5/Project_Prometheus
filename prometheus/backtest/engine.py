"""Deterministic, point-in-time-correct backtest for one StrategySpec
against one symbol.

No Sharpe, no PBO, no Deflated Sharpe here -- that is the Oracle's job
(validation/, PROMPT 5) and consumes THIS module's output (the equity
curve, and signal_for()'s raw position series) rather than computing
those stats inline; CLAUDE.md's "do not reimplement PBO/DSR from scratch"
is a reason to keep them out of the hot backtest loop, not a reason they
can never exist. This produces total return, max drawdown, and turnover.

No look-ahead, two layers deep: `PointInTimeFrame.as_of(cutoff)` already
excludes any bar not yet knowable by `cutoff` (Law 1's own mechanism,
unchanged). On top of that, the SMA crossover signal for bar i is computed
from bars strictly BEFORE i (`shift(1)`) -- bar i's own close never
influences bar i's own position. Both are exercised by
tests/test_backtest_no_lookahead.py.

vs_benchmark (PROMPT 3) is computed INSIDE run_backtest, not left for a
caller to attach afterward -- Law 8's "every result is compared against
buy-and-hold" is then a true invariant of BacktestResult's shape, not
something that happens to be true because runner.py currently remembers
to call compute_benchmark_curve too. A caller that already computed the
benchmark (runner.py does, to also record it for the world view) can pass
it in via `benchmark_result` to avoid computing it twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import polars as pl

from prometheus.backtest.benchmark import (
    BenchmarkResult,
    VsBenchmark,
    compute_benchmark_curve,
    compute_vs_benchmark,
)
from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.backtest.ml_signal import (
    gradient_boosting_signal,
    logistic_regression_signal,
    random_forest_signal,
    svm_signal,
)
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import (
    FAMILY_ADX_DI_CROSSOVER,
    FAMILY_AROON_CROSSOVER,
    FAMILY_ATR_BREAKOUT,
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CHANDELIER_EXIT,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_DEMA_CROSSOVER,
    FAMILY_EMA_CROSSOVER,
    FAMILY_GAP_FADE,
    FAMILY_GRADIENT_BOOSTING,
    FAMILY_HULL_MA_TREND,
    FAMILY_IBS,
    FAMILY_ICHIMOKU_BREAKOUT,
    FAMILY_INSIDE_BAR_BREAKOUT,
    FAMILY_KAMA_TREND,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_LINREG_SLOPE,
    FAMILY_LOGISTIC_REGRESSION,
    FAMILY_MACD,
    FAMILY_MA_RIBBON,
    FAMILY_MFI,
    FAMILY_MOMENTUM,
    FAMILY_N_DAY_LOW,
    FAMILY_NR7_BREAKOUT,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RANDOM_FOREST,
    FAMILY_RSI,
    FAMILY_SMA200_FILTER,
    FAMILY_SMA_DISTANCE,
    FAMILY_SQUEEZE_BREAKOUT,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_SVM,
    FAMILY_TRIPLE_MA_ALIGNMENT,
    FAMILY_TRIX,
    FAMILY_TSMOM,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_VOL_BREAKOUT,
    FAMILY_VOL_OF_VOL_FILTER,
    FAMILY_VOL_REGIME_SWITCH,
    FAMILY_VORTEX,
    FAMILY_WILLIAMS_R,
    FAMILY_ZSCORE,
    StrategySpec,
)

STARTING_CAPITAL = 1000.0


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: tuple[tuple[str, float], ...]  # (available_at.isoformat(), equity)
    total_return_pct: float
    max_drawdown_pct: float
    turnover: float
    # gross_return_pct: the same curve with apply_cost() never subtracted.
    # total_costs: the currency sum apply_cost() actually charged. Together
    # they are what experiments.failure's TRANSACTION_COST_FAILURE checks
    # -- gross positive, net negative -- which total_return_pct alone
    # cannot distinguish from a strategy that was never profitable.
    gross_return_pct: float
    total_costs: float
    vs_benchmark: VsBenchmark


def _sma_signal(bars: pl.DataFrame, fast: int, slow: int) -> pl.DataFrame:
    """1.0 = long, 0.0 = flat. `shift(1)`: the position held DURING bar i
    is decided from bars up to and including i-1, never i itself."""
    return bars.with_columns(
        pl.col("close").rolling_mean(fast).alias("_fast"),
        pl.col("close").rolling_mean(slow).alias("_slow"),
    ).with_columns(
        (pl.col("_fast") - pl.col("_slow")).alias("_signal_strength"),
        (pl.col("_fast") > pl.col("_slow"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _bollinger_signal(bars: pl.DataFrame, lookback: int, band_multiplier: float) -> pl.DataFrame:
    """Classic Bollinger mean-reversion (John Bollinger's own
    construction): long whenever close is below the lower band (mean -
    band_multiplier*std), flat otherwise -- stateless, same shape
    _sma_signal already is (the condition itself IS the position, not a
    separate enter/hold/exit state machine). Same `shift(1)` discipline:
    the raw condition is computed with the current bar's own close
    (matching _sma_signal exactly), then the WHOLE condition is shifted
    by one bar before it ever becomes an execution position."""
    return bars.with_columns(
        pl.col("close").rolling_mean(lookback).alias("_mid"),
        pl.col("close").rolling_std(lookback).alias("_std"),
    ).with_columns(
        (pl.col("_mid") - band_multiplier * pl.col("_std")).alias("_lower")
    ).with_columns(
        # Distance below the mean in std units, sign-flipped so "more
        # oversold" (lower close, further below the lower band) reads as a
        # HIGHER signal strength -- the same direction the mean-reversion
        # condition itself acts on. -_std guarded against 0 the same way
        # the position condition already tolerates it (comparison against
        # a NaN/inf band is simply never favorable).
        ((pl.col("_mid") - pl.col("close")) / pl.col("_std")).alias("_signal_strength"),
        (pl.col("close") < pl.col("_lower"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _vol_breakout_signal(
    bars: pl.DataFrame, breakout_window: int, exit_window: int
) -> pl.DataFrame:
    """Donchian-channel breakout, the Turtle Trading convention: enter
    long on a close ABOVE the breakout_window-bar rolling high, exit on
    a close BELOW the shorter exit_window-bar rolling low, otherwise
    PERSIST the previous position (a breakout, unlike crossover/mean-
    reversion, is a state you stay in, not a condition re-evaluated
    fresh every bar). Expressed vectorized via forward_fill() over a
    column that's 1.0/0.0 only on an actual entry/exit bar and null
    otherwise, not an imperative per-bar loop.

    The entry/exit LEVELS are computed with `.shift(1)` BEFORE the
    rolling max/min -- i.e. from the breakout_window/exit_window bars
    strictly BEFORE today, excluding today's own high/low. This is not
    an extra look-ahead guard on top of an otherwise-fine formula, it is
    what "breakout" means: a rolling max that includes today's own high
    can never be exceeded by today's own close (today's high is, by
    construction, part of the maximum being compared against), so a
    same-bar-inclusive version can mathematically never detect a fresh
    high and, on flat/constant price data, compares close to itself
    every bar and fires a spurious signal on every bar past the warm-up
    -- a real bug caught by two failing tests
    (tests/test_strategy_families.py), not something anticipated in
    advance. On TOP of that level-exclusion, the final resulting
    position series still gets the same overall `.shift(1)` discipline
    _sma_signal/_bollinger_signal use: today's close decides whether a
    breakout/breakdown HAPPENED today, but that decision is only ever
    acted on as tomorrow's position, never today's own."""
    return (
        bars.with_columns(
            pl.col("high").shift(1).rolling_max(breakout_window).alias("_entry_level"),
            pl.col("low").shift(1).rolling_min(exit_window).alias("_exit_level"),
        )
        .with_columns(
            pl.when(pl.col("close") > pl.col("_entry_level"))
            .then(1.0)
            .when(pl.col("close") < pl.col("_exit_level"))
            .then(0.0)
            .otherwise(None)
            .alias("_raw_signal")
        )
        .with_columns(
            pl.col("_raw_signal")
            .forward_fill()
            .fill_null(0.0)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def _rsi_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Wilder's own RSI: average gain/loss smoothed with Wilder's
    alpha=1/lookback recursive EMA (the standard practical
    implementation -- pandas/ta-lib's own convention for "RSI", not a
    plain SMA-of-gains approximation). Long whenever RSI drops below
    the oversold threshold, flat otherwise -- a fresh condition
    re-evaluated every bar, same stateless shape as _bollinger_signal,
    not a stateful entry/exit like _vol_breakout_signal. Same
    `shift(1)` discipline: the raw condition uses today's own close,
    then the whole condition is shifted one bar before it becomes an
    execution position.

    A flat, never-moving price series makes avg_gain and avg_loss both
    0.0, so RSI is 0/0 == NaN in polars -- `NaN < oversold` is false,
    giving position 0.0 for every bar, the same "never trades on flat
    prices" behavior every other family's null case exercises."""
    delta = pl.col("close").diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    alpha = 1.0 / lookback
    return (
        bars.with_columns(gain.alias("_gain"), loss.alias("_loss"))
        .with_columns(
            pl.col("_gain").ewm_mean(alpha=alpha, adjust=False).alias("_avg_gain"),
            pl.col("_loss").ewm_mean(alpha=alpha, adjust=False).alias("_avg_loss"),
        )
        .with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss"))).alias("_rsi")
        )
        .with_columns(
            # 50 is RSI's own published centerline (Wilder's own neutral
            # point) -- sign-flipped (50 - rsi) so LOWER RSI (more
            # oversold, closer to a long entry) reads as a HIGHER signal
            # strength, matching every other oversold-style family here.
            (50.0 - pl.col("_rsi")).alias("_signal_strength"),
            (pl.col("_rsi") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _macd_signal(bars: pl.DataFrame, fast: int, slow: int, signal: int) -> pl.DataFrame:
    """Gerald Appel's own construction: MACD line = EMA(fast) -
    EMA(slow), signal line = EMA(MACD line, signal). Long whenever the
    MACD line is above its own signal line, flat otherwise -- a fresh
    condition re-evaluated every bar, same stateless shape as
    _sma_signal (this is the EMA analogue of that same crossover idea).
    `adjust=False` on every ewm_mean matches the standard recursive EMA
    definition trading platforms use, not polars' default weighted
    average, which does not equal it early in a series. Same
    `shift(1)` discipline as every other family here."""
    return (
        bars.with_columns(
            pl.col("close").ewm_mean(span=fast, adjust=False).alias("_ema_fast"),
            pl.col("close").ewm_mean(span=slow, adjust=False).alias("_ema_slow"),
        )
        .with_columns((pl.col("_ema_fast") - pl.col("_ema_slow")).alias("_macd"))
        .with_columns(pl.col("_macd").ewm_mean(span=signal, adjust=False).alias("_signal_line"))
        .with_columns(
            # The MACD histogram (MACD line minus its own signal line) --
            # Gerald Appel's own construction, the standard continuous
            # reading of "how strongly is MACD confirming."
            (pl.col("_macd") - pl.col("_signal_line")).alias("_signal_strength"),
            (pl.col("_macd") > pl.col("_signal_line"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _stochastic_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Lane's own Stochastic Oscillator: %K = 100 * (close - lowest_low_n)
    / (highest_high_n - lowest_low_n). Long whenever %K drops below the
    oversold threshold, flat otherwise -- a fresh condition re-evaluated
    every bar, same stateless shape as _rsi_signal, just a different
    oscillator. Same shift(1) discipline: the raw condition uses today's
    own high/low/close, then the whole condition is shifted one bar
    before it becomes an execution position.

    A flat, never-moving price series makes highest_high == lowest_low,
    so %K is 0/0 == NaN in polars -- `NaN < oversold` is false for every
    bar, the same "never trades on flat prices" behavior every other
    family's null case exercises."""
    return (
        bars.with_columns(
            pl.col("high").rolling_max(lookback).alias("_highest_high"),
            pl.col("low").rolling_min(lookback).alias("_lowest_low"),
        )
        .with_columns(
            (
                100.0
                * (pl.col("close") - pl.col("_lowest_low"))
                / (pl.col("_highest_high") - pl.col("_lowest_low"))
            ).alias("_pct_k")
        )
        .with_columns(
            (50.0 - pl.col("_pct_k")).alias("_signal_strength"),
            (pl.col("_pct_k") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _parabolic_sar_signal(
    bars: pl.DataFrame, af_start: float, af_increment: float, af_max: float
) -> pl.DataFrame:
    """Wilder's own Parabolic SAR ("New Concepts in Technical Trading
    Systems", 1978): a trend-following stop-and-reverse whose stop level
    accelerates toward price as the trend extends. Genuinely sequential
    -- SAR_i depends on SAR_{i-1}, the current trend direction, and the
    running extreme point, none of which are expressible as a pure
    column expression -- so, like ml_signal.py's walk-forward loop, this
    is computed with a real Python loop over numpy arrays, not a polars
    expression chain.

    Long-only mapping: uptrend -> position 1.0, downtrend -> position
    0.0 (this backtest engine has no short leg). The raw trend for bar i
    is decided using bar i's own high/low (Wilder's own reversal check
    compares today's extreme against yesterday's SAR); the final
    shift(1) then means today's DECIDED trend becomes tomorrow's held
    position, same discipline every other family's signal ends with."""
    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    closes = bars["close"].to_numpy()
    n = len(highs)
    raw = [0.0] * n
    sar_values = [float("nan")] * n
    if n < 2:
        return bars.with_columns(
            pl.Series("position", raw),
            pl.Series("_signal_strength", [0.0] * n),
        )

    uptrend = True
    sar = float(lows[0])
    ep = float(highs[0])
    af = af_start
    raw[0] = 1.0
    sar_values[0] = sar

    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if uptrend:
            floor_low = lows[i - 2] if i >= 2 else lows[i - 1]
            sar = min(sar, float(lows[i - 1]), float(floor_low))
            if lows[i] < sar:
                uptrend = False
                sar = ep
                ep = float(lows[i])
                af = af_start
            elif highs[i] > ep:
                ep = float(highs[i])
                af = min(af + af_increment, af_max)
        else:
            ceil_high = highs[i - 2] if i >= 2 else highs[i - 1]
            sar = max(sar, float(highs[i - 1]), float(ceil_high))
            if highs[i] > sar:
                uptrend = True
                sar = ep
                ep = float(highs[i])
                af = af_start
            elif lows[i] < ep:
                ep = float(lows[i])
                af = min(af + af_increment, af_max)
        raw[i] = 1.0 if uptrend else 0.0
        sar_values[i] = sar

    raw_series = pl.Series("_raw_trend", raw)
    # close - sar: positive/growing the further price has pulled away from
    # its own stop-and-reverse level in the trend's favor -- the natural
    # continuous reading of "how strong is this SAR trend right now,"
    # signed the same direction as the uptrend=long position convention.
    strength = pl.Series("_signal_strength", (closes - np.array(sar_values)).tolist())
    return bars.with_columns(
        raw_series.shift(1).fill_null(0.0).alias("position"), strength
    )


def _keltner_signal(bars: pl.DataFrame, lookback: int, multiplier: float) -> pl.DataFrame:
    """Keltner Channel breakout: an ATR-normalized volatility band around
    an EMA midline (Chester Keltner's original construction, with Linda
    Bradford Raschke's later ATR-based band width, which is the variant
    in standard use today). Same Turtle-style entry/persist/exit shape
    _vol_breakout_signal uses: enter long on a close above the upper
    band, exit on a close back below the midline EMA, otherwise persist
    the previous position.

    True range and the midline EMA are both computed from today's own
    high/low/close (matching every other family's "raw condition uses
    today's own bar" convention); the whole resulting position series
    still gets the same overall shift(1) discipline every other family
    ends with."""
    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    return (
        bars.with_columns(
            pl.col("close").ewm_mean(span=lookback, adjust=False).alias("_mid"),
            true_range.ewm_mean(span=lookback, adjust=False).alias("_atr"),
        )
        .with_columns((pl.col("_mid") + multiplier * pl.col("_atr")).alias("_upper"))
        .with_columns(
            pl.when(pl.col("close") > pl.col("_upper"))
            .then(1.0)
            .when(pl.col("close") < pl.col("_mid"))
            .then(0.0)
            .otherwise(None)
            .alias("_raw_signal"),
            # ATR-normalized distance above the midline -- how far price has
            # broken out relative to this family's own volatility band.
            ((pl.col("close") - pl.col("_mid")) / pl.col("_atr")).alias("_signal_strength"),
        )
        .with_columns(
            pl.col("_raw_signal")
            .forward_fill()
            .fill_null(0.0)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def _williams_r_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Larry Williams' own %R: -100 * (highest_high_n - close) /
    (highest_high_n - lowest_low_n). Long whenever %R drops below the
    oversold threshold (a value in (-100, 0)), flat otherwise -- same
    stateless shape as _stochastic_signal (this is, not coincidentally,
    a rescaling of the same underlying %K construction, under its own
    distinct, separately cited name and -100..0 convention)."""
    return (
        bars.with_columns(
            pl.col("high").rolling_max(lookback).alias("_highest_high"),
            pl.col("low").rolling_min(lookback).alias("_lowest_low"),
        )
        .with_columns(
            (
                -100.0
                * (pl.col("_highest_high") - pl.col("close"))
                / (pl.col("_highest_high") - pl.col("_lowest_low"))
            ).alias("_pct_r")
        )
        .with_columns(
            # %R already sits in (-100, 0); -50 recenters it around 0 the
            # same way RSI/%K are recentered around their own midpoints.
            (-50.0 - pl.col("_pct_r")).alias("_signal_strength"),
            (pl.col("_pct_r") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _cci_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Donald Lambert's own Commodity Channel Index: (typical_price -
    SMA(typical_price, lookback)) / (0.015 * mean_absolute_deviation).
    0.015 is Lambert's own scaling constant (chosen so roughly 70-80% of
    CCI values fall within +-100 on his original commodities data) --
    cited, not invented. Long whenever CCI drops below the oversold
    threshold (Lambert's own -100 reversal zone), flat otherwise.

    Polars has no built-in rolling mean-absolute-deviation, so it is
    computed directly: rolling_map applies a real function per window
    (mean absolute deviation from that window's own mean), the same
    "no vectorized primitive exists for this, compute it directly"
    posture ml_features.py's RSI/MACD constructions already take for
    their own EMA-based math."""
    typical_price = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    return (
        bars.with_columns(typical_price.alias("_typical_price"))
        .with_columns(
            pl.col("_typical_price").rolling_mean(lookback).alias("_sma_typical"),
            pl.col("_typical_price")
            .rolling_map(lambda s: (s - s.mean()).abs().mean(), window_size=lookback)
            .alias("_mean_deviation"),
        )
        .with_columns(
            (
                (pl.col("_typical_price") - pl.col("_sma_typical"))
                / (0.015 * pl.col("_mean_deviation"))
            ).alias("_cci")
        )
        .with_columns(
            (-pl.col("_cci")).alias("_signal_strength"),
            (pl.col("_cci") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _awesome_oscillator_signal(bars: pl.DataFrame, fast: int, slow: int) -> pl.DataFrame:
    """Bill Williams' own Awesome Oscillator: SMA(median_price, fast) -
    SMA(median_price, slow), median_price = (high + low) / 2. Long on a
    zero-line crossover (AO > 0), flat otherwise -- a fresh condition
    re-evaluated every bar, the SMA-difference analogue of _macd_signal's
    EMA-difference construction (a genuinely distinct, separately cited
    indicator, not a copy of MACD under a different name)."""
    median_price = (pl.col("high") + pl.col("low")) / 2.0
    return (
        bars.with_columns(median_price.alias("_median_price"))
        .with_columns(
            pl.col("_median_price").rolling_mean(fast).alias("_ao_fast"),
            pl.col("_median_price").rolling_mean(slow).alias("_ao_slow"),
        )
        .with_columns((pl.col("_ao_fast") - pl.col("_ao_slow")).alias("_ao"))
        .with_columns(
            pl.col("_ao").alias("_signal_strength"),
            (pl.col("_ao") > 0.0)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _supertrend_signal(bars: pl.DataFrame, lookback: int, multiplier: float) -> pl.DataFrame:
    """Olivier Seban's own SuperTrend: ATR-based bands around each bar's
    own midpoint ((high+low)/2), with Wilder-style hysteresis deciding
    which band is "the" SuperTrend line and therefore the trend
    direction. Genuinely sequential -- the final upper/lower bands and
    the trend flag at bar i all depend on bar i-1's own final bands and
    trend, none of which are expressible as a pure column expression --
    so, like _parabolic_sar_signal, this is computed with a real Python
    loop over numpy arrays, not a polars expression chain.

    Long-only mapping: uptrend -> position 1.0, downtrend -> position
    0.0 (this backtest engine has no short leg). ATR is a plain
    lookback-bar rolling mean of true range (the standard "SuperTrend
    ATR", not Wilder's own smoothed ATR -- both are cited variants in
    real-world SuperTrend implementations); bar i's own trend is decided
    using bar i's own high/low/close, and the final shift(1) means
    today's decided trend becomes tomorrow's held position, same
    discipline every other family's signal ends with."""
    n = bars.height
    if n < lookback + 1:
        return bars.with_columns(
            pl.Series("position", [0.0] * n), pl.Series("_signal_strength", [0.0] * n)
        )

    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    frame = bars.with_columns(
        ((pl.col("high") + pl.col("low")) / 2.0).alias("_mid"),
        true_range.rolling_mean(lookback).alias("_atr"),
    )
    mids = frame["_mid"].to_numpy()
    atrs = frame["_atr"].to_numpy()
    closes = frame["close"].to_numpy()

    raw = [0.0] * n
    strength = [0.0] * n
    final_upper = float("nan")
    final_lower = float("nan")
    uptrend = True
    for i in range(n):
        if np.isnan(atrs[i]):
            continue  # not enough history yet for this bar's own ATR -- stays flat
        basic_upper = mids[i] + multiplier * atrs[i]
        basic_lower = mids[i] - multiplier * atrs[i]

        if np.isnan(final_upper):
            final_upper, final_lower = basic_upper, basic_lower
        else:
            final_upper = (
                basic_upper if basic_upper < final_upper or closes[i - 1] > final_upper
                else final_upper
            )
            final_lower = (
                basic_lower if basic_lower > final_lower or closes[i - 1] < final_lower
                else final_lower
            )

        if uptrend:
            if closes[i] < final_lower:
                uptrend = False
        elif closes[i] > final_upper:
            uptrend = True
        raw[i] = 1.0 if uptrend else 0.0
        # ATR-normalized distance from the currently ACTIVE line (lower
        # band while uptrend, upper band while downtrend) -- the same
        # "how far has price pulled away from its own stop" reading
        # _parabolic_sar_signal exposes, continuous and signed in the
        # position's own direction.
        active_line = final_lower if uptrend else final_upper
        strength[i] = (closes[i] - active_line) / atrs[i] if atrs[i] != 0.0 else 0.0

    raw_series = pl.Series("_raw_trend", raw)
    return frame.with_columns(
        raw_series.shift(1).fill_null(0.0).alias("position"),
        pl.Series("_signal_strength", strength),
    )


def _trix_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """The rate of change of a triple-smoothed EMA -- a real, cited
    momentum oscillator (not a rebranded MACD: MACD is a difference of
    two EMAs of different lengths, TRIX is a percentage rate of change
    of one EMA smoothed three times at the SAME length). Long on a
    zero-line crossover (TRIX > 0), flat otherwise."""
    ema1 = pl.col("close").ewm_mean(span=lookback, adjust=False)
    return (
        bars.with_columns(ema1.alias("_ema1"))
        .with_columns(pl.col("_ema1").ewm_mean(span=lookback, adjust=False).alias("_ema2"))
        .with_columns(pl.col("_ema2").ewm_mean(span=lookback, adjust=False).alias("_ema3"))
        .with_columns(
            (
                (pl.col("_ema3") - pl.col("_ema3").shift(1)) / pl.col("_ema3").shift(1) * 100.0
            ).alias("_trix")
        )
        .with_columns(
            pl.col("_trix").alias("_signal_strength"),
            (pl.col("_trix") > 0.0)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _keltner_reversion_signal(bars: pl.DataFrame, lookback: int, multiplier: float) -> pl.DataFrame:
    """The inverse of _keltner_signal's breakout logic -- same ATR-
    normalized band around an EMA midline, but long when close drops
    BELOW the lower band (mean reversion), flat once it recovers back
    above the midline. Stateless per-bar condition (not persist-until-exit
    like the breakout version), same shape _bollinger_signal/_cci_signal
    already use for their own mean-reversion families."""
    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    return (
        bars.with_columns(
            pl.col("close").ewm_mean(span=lookback, adjust=False).alias("_mid"),
            true_range.ewm_mean(span=lookback, adjust=False).alias("_atr"),
        )
        .with_columns((pl.col("_mid") - multiplier * pl.col("_atr")).alias("_lower"))
        .with_columns(
            ((pl.col("_lower") - pl.col("close")) / pl.col("_atr")).alias("_signal_strength"),
            (pl.col("close") < pl.col("_lower"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _bollinger_pctb_signal(
    bars: pl.DataFrame, lookback: int, multiplier: float, oversold: float
) -> pl.DataFrame:
    """John Bollinger's own %B: (close - lower_band) / (upper_band -
    lower_band) -- a continuous normalized position within the bands,
    distinct from _bollinger_signal's binary "closed below the lower
    band" touch. Long when %B drops below its own oversold threshold.
    %B is undefined (0/0) when upper==lower (zero rolling std, a flat
    price run); polars' NaN there compares false to `< oversold`, the
    same "never trades on flat prices" behavior every other family's
    null case exercises."""
    return (
        bars.with_columns(
            pl.col("close").rolling_mean(lookback).alias("_mid"),
            pl.col("close").rolling_std(lookback).alias("_std"),
        )
        .with_columns(
            (pl.col("_mid") - multiplier * pl.col("_std")).alias("_lower"),
            (pl.col("_mid") + multiplier * pl.col("_std")).alias("_upper"),
        )
        .with_columns(
            ((pl.col("close") - pl.col("_lower")) / (pl.col("_upper") - pl.col("_lower")))
            .alias("_pctb")
        )
        .with_columns(
            (0.5 - pl.col("_pctb")).alias("_signal_strength"),
            (pl.col("_pctb") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _zscore_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """A standard rolling z-score of price itself: (close -
    SMA(close, lookback)) / rolling_std(close, lookback). Long when the
    z-score drops below its own (negative) oversold threshold -- a
    direct "how many standard deviations below its own recent mean"
    mean-reversion signal, distinct from CCI (which z-scores the typical
    price against mean ABSOLUTE deviation, not std) or Bollinger (which
    thresholds on the band edge, not the z-score value itself)."""
    return (
        bars.with_columns(
            pl.col("close").rolling_mean(lookback).alias("_mean"),
            pl.col("close").rolling_std(lookback).alias("_std"),
        )
        .with_columns(((pl.col("close") - pl.col("_mean")) / pl.col("_std")).alias("_zscore"))
        .with_columns(
            (-pl.col("_zscore")).alias("_signal_strength"),
            (pl.col("_zscore") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _ibs_signal(bars: pl.DataFrame, oversold: float) -> pl.DataFrame:
    """Internal Bar Strength: (close - low) / (high - low) -- a cited
    single-bar mean-reversion construction (no lookback window; it is a
    per-bar ratio of where today's close landed within today's own
    range). Long when IBS drops below its own oversold threshold.
    Undefined (0/0) on a zero-range bar (high == low); treated the same
    "NaN never trades" way every other family's degenerate case is."""
    return bars.with_columns(
        ((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low"))).alias("_ibs")
    ).with_columns(
        (0.5 - pl.col("_ibs")).alias("_signal_strength"),
        (pl.col("_ibs") < oversold).cast(pl.Float64).shift(1).fill_null(0.0).alias("position"),
    )


def _n_day_low_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Long whenever today's close makes a new N-day low (close <=
    rolling_min(close, lookback), the window INCLUDING today's own close
    -- a fresh low is a fresh low the day it happens). Stateless per-bar
    condition, same shape as every other mean-reversion family here."""
    return bars.with_columns(
        pl.col("close").rolling_min(lookback).alias("_rolling_low"),
        pl.col("close").rolling_mean(lookback).alias("_rolling_mean"),
    ).with_columns(
        # How far below the window's own recent average close sits --
        # rolling_low itself is always <= close by construction (it's the
        # min OF the window close belongs to), so it can't measure
        # "how oversold"; the rolling mean can.
        ((pl.col("_rolling_mean") - pl.col("close")) / pl.col("_rolling_mean")).alias(
            "_signal_strength"
        ),
        (pl.col("close") <= pl.col("_rolling_low"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _consecutive_down_signal(bars: pl.DataFrame, run_length: int) -> pl.DataFrame:
    """Long after `run_length` consecutive down-closes in a row -- a
    run-length mean-reversion construction. The run is counted via a
    rolling sum over a boolean "closed down" series: `run_length`
    consecutive down-days sums to exactly `run_length` over that window
    only when every bar in it was itself a down-day."""
    is_down = (pl.col("close") < pl.col("close").shift(1)).cast(pl.Int64).fill_null(0)
    return bars.with_columns(is_down.alias("_down")).with_columns(
        pl.col("_down").rolling_sum(run_length).alias("_down_run")
    ).with_columns(
        pl.col("_down_run").cast(pl.Float64).alias("_signal_strength"),
        (pl.col("_down_run") >= run_length)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _sma_distance_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Distance-from-trend mean reversion: long when close is more than
    `oversold` (a fraction) BELOW its own rolling SMA(lookback) -- e.g.
    oversold=0.1 means "more than 10% below its own N-day average".
    The classic use case cites a 200-day SMA; the lookback itself is a
    swept grid parameter here, not fixed to 200, so this family covers
    any distance-from-trend horizon a grid registers."""
    return bars.with_columns(
        pl.col("close").rolling_mean(lookback).alias("_sma")
    ).with_columns(
        ((pl.col("_sma") - pl.col("close")) / pl.col("_sma")).alias("_signal_strength"),
        (((pl.col("_sma") - pl.col("close")) / pl.col("_sma")) > oversold)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _ultimate_oscillator_signal(
    bars: pl.DataFrame, short: int, mid: int, long: int, oversold: float
) -> pl.DataFrame:
    """Larry Williams' own Ultimate Oscillator (1976): buying pressure
    (close - min(low, prior_close)) over true range, summed across three
    timeframes (his own published short/mid/long convention, typically
    7/14/28) and weighted 4:2:1 short-to-long -- his own published
    weighting, not invented. Long when UO drops below its own oversold
    threshold (Williams' own <30 zone)."""
    prev_close = pl.col("close").shift(1)
    buying_pressure = pl.col("close") - pl.min_horizontal(pl.col("low"), prev_close)
    true_range = pl.max_horizontal(pl.col("high"), prev_close) - pl.min_horizontal(
        pl.col("low"), prev_close
    )
    frame = bars.with_columns(
        buying_pressure.alias("_bp"), true_range.alias("_tr")
    )
    avgs = {}
    for window in (short, mid, long):
        frame = frame.with_columns(
            (pl.col("_bp").rolling_sum(window) / pl.col("_tr").rolling_sum(window)).alias(
                f"_avg_{window}"
            )
        )
        avgs[window] = f"_avg_{window}"
    return frame.with_columns(
        (
            (4.0 * pl.col(avgs[short]) + 2.0 * pl.col(avgs[mid]) + pl.col(avgs[long])) / 7.0 * 100.0
        ).alias("_uo")
    ).with_columns(
        (50.0 - pl.col("_uo")).alias("_signal_strength"),
        (pl.col("_uo") < oversold).cast(pl.Float64).shift(1).fill_null(0.0).alias("position"),
    )


def _mfi_signal(bars: pl.DataFrame, lookback: int, oversold: float) -> pl.DataFrame:
    """Money Flow Index: a volume-weighted RSI. Typical price * volume
    is raw money flow; it's "positive" money flow on a day the typical
    price rose from the prior day, "negative" on a day it fell. MFI is
    then the same RSI-style 100 - 100/(1+ratio) scaling Wilder's RSI
    uses, applied to the ratio of positive to negative money flow sums
    instead of average gain/loss. Long when MFI drops below its own
    oversold threshold."""
    typical_price = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    raw_money_flow = typical_price * pl.col("volume")
    typical_price_rose = typical_price > typical_price.shift(1)
    positive_flow = pl.when(typical_price_rose).then(raw_money_flow).otherwise(0.0)
    negative_flow = pl.when(typical_price_rose).then(0.0).otherwise(raw_money_flow)
    return (
        bars.with_columns(
            positive_flow.alias("_pos_flow"), negative_flow.alias("_neg_flow")
        )
        .with_columns(
            pl.col("_pos_flow").rolling_sum(lookback).alias("_pos_sum"),
            pl.col("_neg_flow").rolling_sum(lookback).alias("_neg_sum"),
        )
        .with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("_pos_sum") / pl.col("_neg_sum"))).alias("_mfi")
        )
        .with_columns(
            (50.0 - pl.col("_mfi")).alias("_signal_strength"),
            (pl.col("_mfi") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _gap_fade_signal(bars: pl.DataFrame, threshold: float) -> pl.DataFrame:
    """Long when today's open gaps DOWN from yesterday's close by more
    than `threshold` (a fraction) -- fading the gap on the expectation
    of a reversion back up. Uses the bar's own open against the PRIOR
    bar's close (never today's own close), so the raw condition is
    already only using information available at today's open; the usual
    shift(1) still applies for consistency with every other family's
    execution-timing convention (position acts on tomorrow's bar)."""
    prev_close = pl.col("close").shift(1)
    gap = (pl.col("open") - prev_close) / prev_close
    return bars.with_columns(gap.alias("_gap")).with_columns(
        (-pl.col("_gap")).alias("_signal_strength"),
        (pl.col("_gap") < -threshold)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _ema_crossover_signal(bars: pl.DataFrame, fast: int, slow: int) -> pl.DataFrame:
    """The EMA analogue of _sma_signal's own SMA crossover -- exponential
    rather than simple weighting is a genuinely distinct, separately
    cited construction (more weight on recent bars, reacts faster to
    new trends), not a rebranded copy. Long when the fast EMA is above
    the slow EMA."""
    return bars.with_columns(
        pl.col("close").ewm_mean(span=fast, adjust=False).alias("_fast"),
        pl.col("close").ewm_mean(span=slow, adjust=False).alias("_slow"),
    ).with_columns(
        (pl.col("_fast") - pl.col("_slow")).alias("_signal_strength"),
        (pl.col("_fast") > pl.col("_slow"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _triple_ma_alignment_signal(
    bars: pl.DataFrame, fast: int, mid: int, slow: int
) -> pl.DataFrame:
    """Long only when three SMAs are in strictly ascending order (fast >
    mid > slow) -- a stronger trend-confirmation filter than a single
    two-line crossover, since a real trend should show consistent
    ordering across multiple horizons, not just one pair agreeing."""
    return bars.with_columns(
        pl.col("close").rolling_mean(fast).alias("_fast"),
        pl.col("close").rolling_mean(mid).alias("_mid"),
        pl.col("close").rolling_mean(slow).alias("_slow"),
    ).with_columns(
        # fast-slow spread carries the alignment's own overall direction/
        # strength; the mid tier is what the position condition uses to
        # confirm ordering, not a second independent magnitude.
        (pl.col("_fast") - pl.col("_slow")).alias("_signal_strength"),
        ((pl.col("_fast") > pl.col("_mid")) & (pl.col("_mid") > pl.col("_slow")))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _dema_crossover_signal(bars: pl.DataFrame, fast: int, slow: int) -> pl.DataFrame:
    """Patrick Mulloy's own Double EMA construction: DEMA = 2*EMA -
    EMA(EMA) -- reduces the lag a plain EMA carries by subtracting out
    the EMA-of-the-EMA's own smoothing delay. Long when the fast DEMA is
    above the slow DEMA."""
    def _dema(span: int) -> pl.Expr:
        ema1 = pl.col("close").ewm_mean(span=span, adjust=False)
        return 2.0 * ema1 - ema1.ewm_mean(span=span, adjust=False)

    return bars.with_columns(
        _dema(fast).alias("_fast"), _dema(slow).alias("_slow")
    ).with_columns(
        (pl.col("_fast") - pl.col("_slow")).alias("_signal_strength"),
        (pl.col("_fast") > pl.col("_slow"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _hull_ma_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Alan Hull's own construction: HMA = WMA(2*WMA(close, n/2) -
    WMA(close, n), round(sqrt(n))) -- a weighted-moving-average-of-
    differences construction designed to track price more closely (less
    lag) than a plain, DEMA, or TEMA smoothing. Polars has no built-in
    weighted-moving-average primitive (same "compute it directly" stance
    _cci_signal's mean-absolute-deviation already takes), so each WMA is
    computed via rolling_map with linearly increasing weights. Long
    when today's HMA exceeds the prior bar's HMA (the trend is rising)."""
    half = max(1, lookback // 2)
    sqrt_n = max(1, round(lookback**0.5))

    def _wma(expr: pl.Expr, window: int) -> pl.Expr:
        weights = list(range(1, window + 1))
        total = float(sum(weights))
        return expr.rolling_map(
            lambda s: sum(w * v for w, v in zip(weights, s)) / total, window_size=window
        )

    return (
        bars.with_columns(
            _wma(pl.col("close"), half).alias("_wma_half"),
            _wma(pl.col("close"), lookback).alias("_wma_full"),
        )
        .with_columns((2.0 * pl.col("_wma_half") - pl.col("_wma_full")).alias("_raw_hma_input"))
        .with_columns(_wma(pl.col("_raw_hma_input"), sqrt_n).alias("_hma"))
        .with_columns(
            (pl.col("_hma") - pl.col("_hma").shift(1)).alias("_signal_strength"),
            (pl.col("_hma") > pl.col("_hma").shift(1))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _kama_signal(bars: pl.DataFrame, lookback: int, fast_sc: int, slow_sc: int) -> pl.DataFrame:
    """Perry Kaufman's own Adaptive Moving Average: the smoothing
    constant adapts every bar between fast_sc- and slow_sc-period
    responsiveness, based on a trailing efficiency ratio (net directional
    move over `lookback` bars, divided by the sum of bar-to-bar
    absolute moves -- 1.0 in a pure trend, near 0 in pure chop).
    Genuinely sequential -- KAMA_i depends on KAMA_{i-1} and that bar's
    own adaptive smoothing constant, neither expressible as a pure
    column expression -- same "real Python loop over numpy arrays"
    treatment _parabolic_sar_signal already uses. Long when today's KAMA
    exceeds the prior bar's KAMA."""
    closes = bars["close"].to_numpy()
    n = len(closes)
    kama = [0.0] * n
    if n <= lookback:
        return bars.with_columns(
            pl.Series("position", [0.0] * n), pl.Series("_signal_strength", [0.0] * n)
        )

    fast_alpha = 2.0 / (fast_sc + 1.0)
    slow_alpha = 2.0 / (slow_sc + 1.0)
    kama[lookback] = float(closes[lookback])
    for i in range(lookback + 1, n):
        change = abs(closes[i] - closes[i - lookback])
        volatility = sum(abs(closes[j] - closes[j - 1]) for j in range(i - lookback + 1, i + 1))
        efficiency_ratio = change / volatility if volatility else 0.0
        smoothing_constant = (efficiency_ratio * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        kama[i] = kama[i - 1] + smoothing_constant * (closes[i] - kama[i - 1])

    kama_series = pl.Series("_kama", kama)
    return bars.with_columns(kama_series).with_columns(
        (pl.col("_kama") - pl.col("_kama").shift(1)).alias("_signal_strength"),
        (pl.col("_kama") > pl.col("_kama").shift(1))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _tsmom_signal(bars: pl.DataFrame, lookback_days: int, skip_days: int) -> pl.DataFrame:
    """Moskowitz, Ooi & Pedersen (2012)'s own time-series momentum,
    Jegadeesh & Titman's cited "12-1 month" skip-the-most-recent-month
    adjustment (avoids short-term reversal contamination of the trend
    signal): long when the trailing return from `lookback_days` bars ago
    to `skip_days` bars ago is positive. This is a genuinely different
    construction from every moving-average family here -- no MA at all,
    just the sign of a single trailing return over a specific,
    skip-adjusted window."""
    anchor_close = pl.col("close").shift(skip_days)
    lookback_close = pl.col("close").shift(lookback_days)
    trailing_return = (anchor_close - lookback_close) / lookback_close
    return bars.with_columns(trailing_return.alias("_tsmom_return")).with_columns(
        pl.col("_tsmom_return").alias("_signal_strength"),
        (pl.col("_tsmom_return") > 0.0)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _adx_di_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Wilder's own Average Directional Index system ("New Concepts in
    Technical Trading Systems", 1978): +DM/-DM are the positive/negative
    parts of consecutive high/low moves, Wilder-smoothed (same alpha=
    1/lookback recursive EMA _rsi_signal already uses for average
    gain/loss) into +DI/-DI, and ADX is the Wilder-smoothed average of
    the DI spread's own absolute percentage. Long when +DI is above -DI
    AND ADX exceeds 25 -- Wilder's own published threshold for "a real
    trend is present" (his book's own trending-market convention, not
    an invented cutoff), so this is a genuinely distinct construction
    from a bare, unfiltered DI crossover."""
    prev_high = pl.col("high").shift(1)
    prev_low = pl.col("low").shift(1)
    prev_close = pl.col("close").shift(1)
    up_move = pl.col("high") - prev_high
    down_move = prev_low - pl.col("low")
    plus_dm = pl.when((up_move > down_move) & (up_move > 0)).then(up_move).otherwise(0.0)
    minus_dm = pl.when((down_move > up_move) & (down_move > 0)).then(down_move).otherwise(0.0)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    alpha = 1.0 / lookback
    return (
        bars.with_columns(
            plus_dm.alias("_plus_dm"), minus_dm.alias("_minus_dm"), true_range.alias("_tr")
        )
        .with_columns(
            pl.col("_plus_dm").ewm_mean(alpha=alpha, adjust=False).alias("_smooth_plus_dm"),
            pl.col("_minus_dm").ewm_mean(alpha=alpha, adjust=False).alias("_smooth_minus_dm"),
            pl.col("_tr").ewm_mean(alpha=alpha, adjust=False).alias("_atr"),
        )
        .with_columns(
            (100.0 * pl.col("_smooth_plus_dm") / pl.col("_atr")).alias("_plus_di"),
            (100.0 * pl.col("_smooth_minus_dm") / pl.col("_atr")).alias("_minus_di"),
        )
        .with_columns(
            (
                100.0
                * (pl.col("_plus_di") - pl.col("_minus_di")).abs()
                / (pl.col("_plus_di") + pl.col("_minus_di"))
            ).alias("_dx")
        )
        .with_columns(pl.col("_dx").ewm_mean(alpha=alpha, adjust=False).alias("_adx"))
        .with_columns(
            (pl.col("_plus_di") - pl.col("_minus_di")).alias("_signal_strength"),
            ((pl.col("_plus_di") > pl.col("_minus_di")) & (pl.col("_adx") > 25.0))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _aroon_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Tushar Chande's own construction: Aroon-Up = 100 * (lookback -
    bars_since_highest_high) / lookback, Aroon-Down analogous for the
    lowest low. Polars has no rolling-argmax primitive, so "bars since
    the window's extreme" is computed directly via rolling_map (same
    "no vectorized primitive exists, compute it directly" stance
    _cci_signal/_hull_ma_signal already take). Long when Aroon-Up
    crosses above Aroon-Down."""
    def _bars_since_extreme(s: pl.Series, find_max: bool) -> float:
        values = s.to_list()
        idx = values.index(max(values) if find_max else min(values))
        return float(len(values) - 1 - idx)

    aroon_up = (
        (lookback - pl.col("high").rolling_map(lambda s: _bars_since_extreme(s, True), lookback))
        / lookback
        * 100.0
    )
    aroon_down = (
        (lookback - pl.col("low").rolling_map(lambda s: _bars_since_extreme(s, False), lookback))
        / lookback
        * 100.0
    )
    return bars.with_columns(aroon_up.alias("_aroon_up"), aroon_down.alias("_aroon_down")).with_columns(
        (pl.col("_aroon_up") - pl.col("_aroon_down")).alias("_signal_strength"),
        (pl.col("_aroon_up") > pl.col("_aroon_down"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _ichimoku_signal(
    bars: pl.DataFrame, conversion: int, base: int, span_b: int
) -> pl.DataFrame:
    """Goichi Hosoda's own construction, his own published 9/26/52
    default periods. Conversion/base lines are the midpoint of the
    highest-high/lowest-low over their own windows; leading span A/B are
    projected `base` periods AHEAD of the data that produced them on a
    real Ichimoku chart -- for a live signal (not a chart), that is
    equivalent to comparing TODAY's close against the span A/B values
    that were computed `base` bars ago, i.e. `.shift(base)` brings the
    historically-correct cloud value forward to today's row. This is
    still Law-1-safe: shift(base) only ever looks BACKWARD for the
    comparison value, never forward. Long when close breaks above the
    cloud (the higher of span A/B)."""
    conv_line = (
        pl.col("high").rolling_max(conversion) + pl.col("low").rolling_min(conversion)
    ) / 2.0
    base_line = (pl.col("high").rolling_max(base) + pl.col("low").rolling_min(base)) / 2.0
    span_a = ((conv_line + base_line) / 2.0).shift(base)
    span_b_line = (
        (pl.col("high").rolling_max(span_b) + pl.col("low").rolling_min(span_b)) / 2.0
    ).shift(base)
    cloud_top = pl.max_horizontal(span_a, span_b_line)
    return bars.with_columns(cloud_top.alias("_cloud_top")).with_columns(
        (pl.col("close") - pl.col("_cloud_top")).alias("_signal_strength"),
        (pl.col("close") > pl.col("_cloud_top"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _vortex_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Etienne Botes & Douglas Siepman's own construction (2010):
    +VM = abs(high - prior_low), -VM = abs(low - prior_high), each
    summed over the lookback window and divided by summed true range to
    give +VI/-VI. Long when +VI crosses above -VI."""
    prev_high = pl.col("high").shift(1)
    prev_low = pl.col("low").shift(1)
    prev_close = pl.col("close").shift(1)
    plus_vm = (pl.col("high") - prev_low).abs()
    minus_vm = (pl.col("low") - prev_high).abs()
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    return (
        bars.with_columns(
            plus_vm.alias("_plus_vm"), minus_vm.alias("_minus_vm"), true_range.alias("_tr")
        )
        .with_columns(
            pl.col("_plus_vm").rolling_sum(lookback).alias("_plus_vm_sum"),
            pl.col("_minus_vm").rolling_sum(lookback).alias("_minus_vm_sum"),
            pl.col("_tr").rolling_sum(lookback).alias("_tr_sum"),
        )
        .with_columns(
            (pl.col("_plus_vm_sum") / pl.col("_tr_sum")).alias("_plus_vi"),
            (pl.col("_minus_vm_sum") / pl.col("_tr_sum")).alias("_minus_vi"),
        )
        .with_columns(
            (pl.col("_plus_vi") - pl.col("_minus_vi")).alias("_signal_strength"),
            (pl.col("_plus_vi") > pl.col("_minus_vi"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _linreg_slope_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """The sign of a rolling ordinary-least-squares linear regression
    slope of close over the lookback window -- long when the trend
    line's own slope is positive. Polars has no rolling-regression
    primitive, so the slope is computed directly via rolling_map using
    the closed-form OLS slope (cov(x, y) / var(x), x = 0..window-1),
    the same "no vectorized primitive exists, compute it directly"
    stance CCI/Hull/Aroon already take here."""
    def _ols_slope(s: pl.Series) -> float:
        y = s.to_list()
        n = len(y)
        x_mean = (n - 1) / 2.0
        y_mean = sum(y) / n
        cov = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(y))
        var = sum((i - x_mean) ** 2 for i in range(n))
        return float(cov / var) if var else 0.0

    return bars.with_columns(
        pl.col("close").rolling_map(_ols_slope, lookback).alias("_slope")
    ).with_columns(
        pl.col("_slope").alias("_signal_strength"),
        (pl.col("_slope") > 0.0).cast(pl.Float64).shift(1).fill_null(0.0).alias("position"),
    )


def _chandelier_exit_signal(bars: pl.DataFrame, lookback: int, multiplier: float) -> pl.DataFrame:
    """Chuck LeBeau's own construction: a trailing stop set
    `multiplier` ATRs below the highest high of the lookback window.
    Long whenever close is above that stop level, flat otherwise --
    implemented here as the simple, commonly-used stateless form (the
    stop is recomputed fresh every bar from the window's own current
    high, not ratcheted/remembered across bars), stated explicitly since
    some descriptions of Chandelier Exit use a stop that only ever moves
    in the trade's favor; that stateful variant is a real, separate
    construction this function does not claim to be."""
    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    return (
        bars.with_columns(true_range.alias("_tr"))
        .with_columns(pl.col("_tr").ewm_mean(span=lookback, adjust=False).alias("_atr"))
        .with_columns(pl.col("high").rolling_max(lookback).alias("_highest_high"))
        .with_columns(
            (pl.col("_highest_high") - multiplier * pl.col("_atr")).alias("_stop")
        )
        .with_columns(
            ((pl.col("close") - pl.col("_stop")) / pl.col("_atr")).alias("_signal_strength"),
            (pl.col("close") > pl.col("_stop"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


def _sma200_filter_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """STRATEGIES_100.md #19's own framing: "simple and robust
    baseline." Long whenever close is above its own single rolling SMA,
    flat otherwise -- deliberately simpler than MOMENTUM's own two-MA
    crossover (one moving average, one condition, no second window to
    overfit)."""
    return bars.with_columns(
        pl.col("close").rolling_mean(lookback).alias("_sma")
    ).with_columns(
        ((pl.col("close") - pl.col("_sma")) / pl.col("_sma")).alias("_signal_strength"),
        (pl.col("close") > pl.col("_sma"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _ma_ribbon_signal(bars: pl.DataFrame, short: int, mid: int, long: int) -> pl.DataFrame:
    """Three SMAs (short/mid/long) forming a "ribbon". Long when the
    ribbon is both correctly ALIGNED (short > mid > long -- an uptrend)
    AND EXPANDING (today's short-to-long spread wider than the prior
    bar's) -- a trend-STRENGTH confirmation on top of
    TRIPLE_MA_ALIGNMENT's own pure trend-DIRECTION signal; alignment
    alone can persist while the ribbon itself compresses toward a
    reversal, which this family is built to exclude."""
    return (
        bars.with_columns(
            pl.col("close").rolling_mean(short).alias("_short"),
            pl.col("close").rolling_mean(mid).alias("_mid"),
            pl.col("close").rolling_mean(long).alias("_long"),
        )
        .with_columns((pl.col("_short") - pl.col("_long")).alias("_spread"))
        .with_columns(
            pl.col("_spread").alias("_signal_strength"),
            (
                (pl.col("_short") > pl.col("_mid"))
                & (pl.col("_mid") > pl.col("_long"))
                & (pl.col("_spread") > pl.col("_spread").shift(1))
            )
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position"),
        )
    )


_SQUEEZE_BB_MULTIPLIER = 2.0
_SQUEEZE_KC_MULTIPLIER = 1.5


def _squeeze_breakout_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """John Carter's own "TTM Squeeze" (*Mastering the Trade*, 2005):
    squeeze_on when Bollinger Bands (2.0 std, Carter's own canonical
    multiplier) sit entirely inside Keltner Channels (1.5x ATR, also
    Carter's own canonical multiplier) -- both bands share the same
    lookback, which is the only swept parameter, matching Carter's own
    convention of fixing the multipliers. Long the bar the squeeze
    RELEASES (was on, now off) with close breaking above the shared
    basis (the direction of the release, not just its occurrence)."""
    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    basis = pl.col("close").rolling_mean(lookback)
    bb_std = pl.col("close").rolling_std(lookback)
    atr = true_range.ewm_mean(span=lookback, adjust=False)
    return (
        bars.with_columns(
            basis.alias("_basis"),
            (basis + _SQUEEZE_BB_MULTIPLIER * bb_std).alias("_bb_upper"),
            (basis - _SQUEEZE_BB_MULTIPLIER * bb_std).alias("_bb_lower"),
            (basis + _SQUEEZE_KC_MULTIPLIER * atr).alias("_kc_upper"),
            (basis - _SQUEEZE_KC_MULTIPLIER * atr).alias("_kc_lower"),
        )
        .with_columns(
            ((pl.col("_bb_upper") < pl.col("_kc_upper")) & (pl.col("_bb_lower") > pl.col("_kc_lower")))
            .alias("_squeeze_on")
        )
        .with_columns(
            (
                pl.col("_squeeze_on").shift(1).fill_null(False)
                & ~pl.col("_squeeze_on")
                & (pl.col("close") > pl.col("_basis"))
            )
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
        )
    )


def _atr_breakout_signal(bars: pl.DataFrame, lookback: int, multiplier: float) -> pl.DataFrame:
    """Volatility-scaled breakout: long when close breaks above the
    PRIOR close plus multiplier ATRs -- distinct from VOL_BREAKOUT's own
    fixed Donchian-channel construction (a rolling N-bar high), this
    breaks out of a volatility-scaled band anchored on the prior close.
    Standard practitioner construction, no single canonical paper."""
    prev_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    atr = true_range.ewm_mean(span=lookback, adjust=False)
    return bars.with_columns(
        prev_close.alias("_prev_close"), atr.alias("_atr")
    ).with_columns(
        ((pl.col("close") - pl.col("_prev_close")) / pl.col("_atr")).alias("_signal_strength"),
        (pl.col("close") > pl.col("_prev_close") + multiplier * pl.col("_atr"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position"),
    )


def _nr7_breakout_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Toby Crabel's own NR7 construction (*Day Trading with Short Term
    Price Patterns and Opening Range Breakout*, 1990): the narrowest
    true range of the last `lookback` bars (canonically 7) signals
    imminent expansion. Long the bar AFTER an NR7 bar if close breaks
    above that NR7 bar's own high."""
    day_range = pl.col("high") - pl.col("low")
    is_nr = day_range == day_range.rolling_min(lookback)
    return bars.with_columns(
        is_nr.alias("_is_nr"), pl.col("high").alias("_range_high")
    ).with_columns(
        (
            pl.col("_is_nr").shift(1).fill_null(False)
            & (pl.col("close") > pl.col("_range_high").shift(1))
        )
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def _inside_bar_breakout_signal(bars: pl.DataFrame, buffer: float) -> pl.DataFrame:
    """Standard price-action pattern: an inside bar (today's high < prior
    high AND today's low > prior low) signals compression. Long the bar
    AFTER an inside bar if close breaks above that inside bar's own high
    by more than `buffer` (a fractional confirmation buffer to reduce
    false breakouts). No single canonical paper."""
    prev_high = pl.col("high").shift(1)
    prev_low = pl.col("low").shift(1)
    is_inside = (pl.col("high") < prev_high) & (pl.col("low") > prev_low)
    return bars.with_columns(
        is_inside.alias("_is_inside"), pl.col("high").alias("_inside_high")
    ).with_columns(
        (
            pl.col("_is_inside").shift(1).fill_null(False)
            & (pl.col("close") > pl.col("_inside_high").shift(1) * (1.0 + buffer))
        )
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def _vol_regime_switch_signal(
    bars: pl.DataFrame, vol_window: int, regime_window: int, lookback: int
) -> pl.DataFrame:
    """A practitioner regime-switching heuristic, informed by the general
    finding that trend-following tends to underperform in high-
    volatility/choppy regimes while mean-reversion tends to dominate
    then (no single canonical paper). Realized volatility (rolling std
    of returns over vol_window) is compared against its own rolling
    median over regime_window: in the LOW regime, long when the trailing
    return over `lookback` is positive (trend-following); in the HIGH
    regime, long when close is below its own SMA over `lookback`
    (mean-reversion)."""
    returns = pl.col("close").pct_change()
    realized_vol = returns.rolling_std(vol_window)
    regime_threshold = realized_vol.rolling_median(regime_window)
    low_regime = realized_vol <= regime_threshold
    trend_signal = pl.col("close") > pl.col("close").shift(lookback)
    reversion_signal = pl.col("close") < pl.col("close").rolling_mean(lookback)
    return bars.with_columns(
        low_regime.alias("_low_regime"),
        trend_signal.alias("_trend"),
        reversion_signal.alias("_reversion"),
    ).with_columns(
        (
            (pl.col("_low_regime") & pl.col("_trend"))
            | (~pl.col("_low_regime") & pl.col("_reversion"))
        )
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def _vol_of_vol_filter_signal(
    bars: pl.DataFrame, vol_window: int, vov_window: int, lookback: int
) -> pl.DataFrame:
    """Structurally similar to VOL_REGIME_SWITCH but filters on the
    volatility OF realized volatility (a rolling std of the realized-vol
    series itself over vov_window) rather than the vol LEVEL -- a
    distinct empirical bet: vol-of-vol spikes often precede whipsaws even
    when the vol level itself looks calm. Long when the trailing return
    over `lookback` is positive AND today's vol-of-vol is at or below its
    own rolling median over vov_window. No single canonical paper -- a
    practitioner filter used in systematic vol-managed strategies."""
    returns = pl.col("close").pct_change()
    realized_vol = returns.rolling_std(vol_window)
    vol_of_vol = realized_vol.rolling_std(vov_window)
    vov_median = vol_of_vol.rolling_median(vov_window)
    stable_regime = vol_of_vol <= vov_median
    trend_signal = pl.col("close") > pl.col("close").shift(lookback)
    return bars.with_columns(
        stable_regime.alias("_stable"), trend_signal.alias("_trend")
    ).with_columns(
        (pl.col("_stable") & pl.col("_trend"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
    )


def signal_for(bars: pl.DataFrame, spec: StrategySpec) -> pl.DataFrame:
    """Public seam validation/metrics.py's information-coefficient
    calculation needs: IC is a property of the SIGNAL (does it predict
    forward returns), not of an executed, cost-bearing backtest, so it
    reads the `position` column directly rather than differencing
    BacktestResult's equity curve. Dispatches on spec.family."""
    if spec.family == FAMILY_MOMENTUM:
        assert spec.fast_window is not None and spec.slow_window is not None
        return _sma_signal(bars, spec.fast_window, spec.slow_window)
    if spec.family == FAMILY_BOLLINGER:
        assert spec.lookback_window is not None and spec.band_multiplier is not None
        return _bollinger_signal(bars, spec.lookback_window, spec.band_multiplier)
    if spec.family == FAMILY_VOL_BREAKOUT:
        assert spec.breakout_window is not None and spec.exit_window is not None
        return _vol_breakout_signal(bars, spec.breakout_window, spec.exit_window)
    if spec.family == FAMILY_RSI:
        assert spec.rsi_lookback is not None and spec.rsi_oversold is not None
        return _rsi_signal(bars, spec.rsi_lookback, spec.rsi_oversold)
    if spec.family == FAMILY_MACD:
        assert (
            spec.macd_fast is not None
            and spec.macd_slow is not None
            and spec.macd_signal is not None
        )
        return _macd_signal(bars, spec.macd_fast, spec.macd_slow, spec.macd_signal)
    if spec.family == FAMILY_RANDOM_FOREST:
        assert (
            spec.rf_train_window is not None
            and spec.rf_retrain_interval is not None
            and spec.rf_predict_threshold is not None
        )
        return random_forest_signal(
            bars, spec.rf_train_window, spec.rf_retrain_interval, spec.rf_predict_threshold
        )
    if spec.family == FAMILY_GRADIENT_BOOSTING:
        assert (
            spec.gb_train_window is not None
            and spec.gb_retrain_interval is not None
            and spec.gb_predict_threshold is not None
        )
        return gradient_boosting_signal(
            bars, spec.gb_train_window, spec.gb_retrain_interval, spec.gb_predict_threshold
        )
    if spec.family == FAMILY_LOGISTIC_REGRESSION:
        assert (
            spec.lr_train_window is not None
            and spec.lr_retrain_interval is not None
            and spec.lr_predict_threshold is not None
        )
        return logistic_regression_signal(
            bars, spec.lr_train_window, spec.lr_retrain_interval, spec.lr_predict_threshold
        )
    if spec.family == FAMILY_SVM:
        assert (
            spec.svm_train_window is not None
            and spec.svm_retrain_interval is not None
            and spec.svm_predict_threshold is not None
        )
        return svm_signal(
            bars, spec.svm_train_window, spec.svm_retrain_interval, spec.svm_predict_threshold
        )
    if spec.family == FAMILY_STOCHASTIC:
        assert spec.stoch_lookback is not None and spec.stoch_oversold is not None
        return _stochastic_signal(bars, spec.stoch_lookback, spec.stoch_oversold)
    if spec.family == FAMILY_PARABOLIC_SAR:
        assert (
            spec.sar_af_start is not None
            and spec.sar_af_increment is not None
            and spec.sar_af_max is not None
        )
        return _parabolic_sar_signal(bars, spec.sar_af_start, spec.sar_af_increment, spec.sar_af_max)
    if spec.family == FAMILY_KELTNER:
        assert spec.keltner_lookback is not None and spec.keltner_multiplier is not None
        return _keltner_signal(bars, spec.keltner_lookback, spec.keltner_multiplier)
    if spec.family == FAMILY_WILLIAMS_R:
        assert spec.williams_lookback is not None and spec.williams_oversold is not None
        return _williams_r_signal(bars, spec.williams_lookback, spec.williams_oversold)
    if spec.family == FAMILY_CCI:
        assert spec.cci_lookback is not None and spec.cci_oversold is not None
        return _cci_signal(bars, spec.cci_lookback, spec.cci_oversold)
    if spec.family == FAMILY_AWESOME_OSCILLATOR:
        assert spec.ao_fast is not None and spec.ao_slow is not None
        return _awesome_oscillator_signal(bars, spec.ao_fast, spec.ao_slow)
    if spec.family == FAMILY_SUPERTREND:
        assert spec.supertrend_lookback is not None and spec.supertrend_multiplier is not None
        return _supertrend_signal(bars, spec.supertrend_lookback, spec.supertrend_multiplier)
    if spec.family == FAMILY_TRIX:
        assert spec.trix_lookback is not None
        return _trix_signal(bars, spec.trix_lookback)
    if spec.family == FAMILY_KELTNER_REVERSION:
        assert (
            spec.keltner_rev_lookback is not None and spec.keltner_rev_multiplier is not None
        )
        return _keltner_reversion_signal(
            bars, spec.keltner_rev_lookback, spec.keltner_rev_multiplier
        )
    if spec.family == FAMILY_BOLLINGER_PCTB:
        assert (
            spec.pctb_lookback is not None
            and spec.pctb_multiplier is not None
            and spec.pctb_oversold is not None
        )
        return _bollinger_pctb_signal(
            bars, spec.pctb_lookback, spec.pctb_multiplier, spec.pctb_oversold
        )
    if spec.family == FAMILY_ZSCORE:
        assert spec.zscore_lookback is not None and spec.zscore_oversold is not None
        return _zscore_signal(bars, spec.zscore_lookback, spec.zscore_oversold)
    if spec.family == FAMILY_IBS:
        assert spec.ibs_oversold is not None
        return _ibs_signal(bars, spec.ibs_oversold)
    if spec.family == FAMILY_N_DAY_LOW:
        assert spec.ndaylow_lookback is not None
        return _n_day_low_signal(bars, spec.ndaylow_lookback)
    if spec.family == FAMILY_CONSECUTIVE_DOWN:
        assert spec.consecutive_down_days is not None
        return _consecutive_down_signal(bars, spec.consecutive_down_days)
    if spec.family == FAMILY_SMA_DISTANCE:
        assert spec.sma_dist_lookback is not None and spec.sma_dist_oversold is not None
        return _sma_distance_signal(bars, spec.sma_dist_lookback, spec.sma_dist_oversold)
    if spec.family == FAMILY_ULTIMATE_OSCILLATOR:
        assert (
            spec.uo_short is not None
            and spec.uo_mid is not None
            and spec.uo_long is not None
            and spec.uo_oversold is not None
        )
        return _ultimate_oscillator_signal(
            bars, spec.uo_short, spec.uo_mid, spec.uo_long, spec.uo_oversold
        )
    if spec.family == FAMILY_MFI:
        assert spec.mfi_lookback is not None and spec.mfi_oversold is not None
        return _mfi_signal(bars, spec.mfi_lookback, spec.mfi_oversold)
    if spec.family == FAMILY_GAP_FADE:
        assert spec.gap_fade_threshold is not None
        return _gap_fade_signal(bars, spec.gap_fade_threshold)
    if spec.family == FAMILY_EMA_CROSSOVER:
        assert spec.ema_fast_window is not None and spec.ema_slow_window is not None
        return _ema_crossover_signal(bars, spec.ema_fast_window, spec.ema_slow_window)
    if spec.family == FAMILY_TRIPLE_MA_ALIGNMENT:
        assert (
            spec.tma_fast_window is not None
            and spec.tma_mid_window is not None
            and spec.tma_slow_window is not None
        )
        return _triple_ma_alignment_signal(
            bars, spec.tma_fast_window, spec.tma_mid_window, spec.tma_slow_window
        )
    if spec.family == FAMILY_DEMA_CROSSOVER:
        assert spec.dema_fast_window is not None and spec.dema_slow_window is not None
        return _dema_crossover_signal(bars, spec.dema_fast_window, spec.dema_slow_window)
    if spec.family == FAMILY_HULL_MA_TREND:
        assert spec.hull_lookback is not None
        return _hull_ma_signal(bars, spec.hull_lookback)
    if spec.family == FAMILY_KAMA_TREND:
        assert (
            spec.kama_lookback is not None
            and spec.kama_fast_sc is not None
            and spec.kama_slow_sc is not None
        )
        return _kama_signal(bars, spec.kama_lookback, spec.kama_fast_sc, spec.kama_slow_sc)
    if spec.family == FAMILY_TSMOM:
        assert spec.tsmom_lookback_days is not None and spec.tsmom_skip_days is not None
        return _tsmom_signal(bars, spec.tsmom_lookback_days, spec.tsmom_skip_days)
    if spec.family == FAMILY_ADX_DI_CROSSOVER:
        assert spec.adx_lookback is not None
        return _adx_di_signal(bars, spec.adx_lookback)
    if spec.family == FAMILY_AROON_CROSSOVER:
        assert spec.aroon_lookback is not None
        return _aroon_signal(bars, spec.aroon_lookback)
    if spec.family == FAMILY_ICHIMOKU_BREAKOUT:
        assert (
            spec.ichimoku_conversion is not None
            and spec.ichimoku_base is not None
            and spec.ichimoku_span_b is not None
        )
        return _ichimoku_signal(
            bars, spec.ichimoku_conversion, spec.ichimoku_base, spec.ichimoku_span_b
        )
    if spec.family == FAMILY_VORTEX:
        assert spec.vortex_lookback is not None
        return _vortex_signal(bars, spec.vortex_lookback)
    if spec.family == FAMILY_LINREG_SLOPE:
        assert spec.linreg_lookback is not None
        return _linreg_slope_signal(bars, spec.linreg_lookback)
    if spec.family == FAMILY_CHANDELIER_EXIT:
        assert spec.chandelier_lookback is not None and spec.chandelier_multiplier is not None
        return _chandelier_exit_signal(bars, spec.chandelier_lookback, spec.chandelier_multiplier)
    if spec.family == FAMILY_SMA200_FILTER:
        assert spec.sma_filter_lookback is not None
        return _sma200_filter_signal(bars, spec.sma_filter_lookback)
    if spec.family == FAMILY_MA_RIBBON:
        assert (
            spec.ribbon_short is not None
            and spec.ribbon_mid is not None
            and spec.ribbon_long is not None
        )
        return _ma_ribbon_signal(bars, spec.ribbon_short, spec.ribbon_mid, spec.ribbon_long)
    if spec.family == FAMILY_SQUEEZE_BREAKOUT:
        assert spec.squeeze_lookback is not None
        return _squeeze_breakout_signal(bars, spec.squeeze_lookback)
    if spec.family == FAMILY_ATR_BREAKOUT:
        assert spec.atr_breakout_lookback is not None and spec.atr_breakout_multiplier is not None
        return _atr_breakout_signal(bars, spec.atr_breakout_lookback, spec.atr_breakout_multiplier)
    if spec.family == FAMILY_NR7_BREAKOUT:
        assert spec.nr7_lookback is not None
        return _nr7_breakout_signal(bars, spec.nr7_lookback)
    if spec.family == FAMILY_INSIDE_BAR_BREAKOUT:
        assert spec.inside_bar_buffer is not None
        return _inside_bar_breakout_signal(bars, spec.inside_bar_buffer)
    if spec.family == FAMILY_VOL_REGIME_SWITCH:
        assert (
            spec.vre_vol_window is not None
            and spec.vre_regime_window is not None
            and spec.vre_lookback is not None
        )
        return _vol_regime_switch_signal(
            bars, spec.vre_vol_window, spec.vre_regime_window, spec.vre_lookback
        )
    if spec.family == FAMILY_VOL_OF_VOL_FILTER:
        assert (
            spec.vov_vol_window is not None
            and spec.vov_window is not None
            and spec.vov_lookback is not None
        )
        return _vol_of_vol_filter_signal(bars, spec.vov_vol_window, spec.vov_window, spec.vov_lookback)
    raise ValueError(f"no signal generator for family {spec.family!r}")


def _min_bars_for(spec: StrategySpec) -> int:
    """The warm-up a spec's own rolling window needs before its signal is
    meaningful, generalized across families -- the same `+2` headroom
    run_backtest already used for MOMENTUM's slow_window (one extra bar
    for the rolling computation's own first non-null value, one more for
    the position `.diff()` in run_backtest's accounting loop)."""
    if spec.family == FAMILY_MOMENTUM:
        assert spec.slow_window is not None
        return spec.slow_window + 2
    if spec.family == FAMILY_BOLLINGER:
        assert spec.lookback_window is not None
        return spec.lookback_window + 2
    if spec.family == FAMILY_VOL_BREAKOUT:
        assert spec.breakout_window is not None
        return spec.breakout_window + 2
    if spec.family == FAMILY_RSI:
        assert spec.rsi_lookback is not None
        return spec.rsi_lookback + 2
    if spec.family == FAMILY_MACD:
        assert spec.macd_slow is not None and spec.macd_signal is not None
        return spec.macd_slow + spec.macd_signal + 2
    if spec.family == FAMILY_RANDOM_FOREST:
        assert spec.rf_train_window is not None
        return spec.rf_train_window + 30
    if spec.family == FAMILY_GRADIENT_BOOSTING:
        assert spec.gb_train_window is not None
        return spec.gb_train_window + 30
    if spec.family == FAMILY_LOGISTIC_REGRESSION:
        assert spec.lr_train_window is not None
        return spec.lr_train_window + 30
    if spec.family == FAMILY_SVM:
        assert spec.svm_train_window is not None
        return spec.svm_train_window + 30
    if spec.family == FAMILY_STOCHASTIC:
        assert spec.stoch_lookback is not None
        return spec.stoch_lookback + 2
    if spec.family == FAMILY_PARABOLIC_SAR:
        return 5  # needs only its own prior 2 bars' extremes plus the shift(1)/diff headroom
    if spec.family == FAMILY_KELTNER:
        assert spec.keltner_lookback is not None
        return spec.keltner_lookback + 2
    if spec.family == FAMILY_WILLIAMS_R:
        assert spec.williams_lookback is not None
        return spec.williams_lookback + 2
    if spec.family == FAMILY_CCI:
        assert spec.cci_lookback is not None
        return spec.cci_lookback + 2
    if spec.family == FAMILY_AWESOME_OSCILLATOR:
        assert spec.ao_slow is not None
        return spec.ao_slow + 2
    if spec.family == FAMILY_SUPERTREND:
        assert spec.supertrend_lookback is not None
        return spec.supertrend_lookback + 2
    if spec.family == FAMILY_TRIX:
        assert spec.trix_lookback is not None
        return spec.trix_lookback + 2
    if spec.family == FAMILY_KELTNER_REVERSION:
        assert spec.keltner_rev_lookback is not None
        return spec.keltner_rev_lookback + 2
    if spec.family == FAMILY_BOLLINGER_PCTB:
        assert spec.pctb_lookback is not None
        return spec.pctb_lookback + 2
    if spec.family == FAMILY_ZSCORE:
        assert spec.zscore_lookback is not None
        return spec.zscore_lookback + 2
    if spec.family == FAMILY_IBS:
        return 3  # a single-bar ratio -- just the shift(1)/diff headroom
    if spec.family == FAMILY_N_DAY_LOW:
        assert spec.ndaylow_lookback is not None
        return spec.ndaylow_lookback + 2
    if spec.family == FAMILY_CONSECUTIVE_DOWN:
        assert spec.consecutive_down_days is not None
        return spec.consecutive_down_days + 2
    if spec.family == FAMILY_SMA_DISTANCE:
        assert spec.sma_dist_lookback is not None
        return spec.sma_dist_lookback + 2
    if spec.family == FAMILY_ULTIMATE_OSCILLATOR:
        assert spec.uo_long is not None
        return spec.uo_long + 2
    if spec.family == FAMILY_MFI:
        assert spec.mfi_lookback is not None
        return spec.mfi_lookback + 2
    if spec.family == FAMILY_GAP_FADE:
        return 3  # a single-bar gap condition -- just the shift(1)/diff headroom
    if spec.family == FAMILY_EMA_CROSSOVER:
        assert spec.ema_slow_window is not None
        return spec.ema_slow_window + 2
    if spec.family == FAMILY_TRIPLE_MA_ALIGNMENT:
        assert spec.tma_slow_window is not None
        return spec.tma_slow_window + 2
    if spec.family == FAMILY_DEMA_CROSSOVER:
        assert spec.dema_slow_window is not None
        return spec.dema_slow_window * 2 + 2  # EMA-of-EMA needs double the window to warm up
    if spec.family == FAMILY_HULL_MA_TREND:
        assert spec.hull_lookback is not None
        sqrt_n = max(1, round(spec.hull_lookback**0.5))
        return int(spec.hull_lookback + sqrt_n + 2)
    if spec.family == FAMILY_KAMA_TREND:
        assert spec.kama_lookback is not None
        return spec.kama_lookback + 2
    if spec.family == FAMILY_TSMOM:
        assert spec.tsmom_lookback_days is not None
        return spec.tsmom_lookback_days + 2
    if spec.family == FAMILY_ADX_DI_CROSSOVER:
        assert spec.adx_lookback is not None
        return spec.adx_lookback * 3 + 2  # Wilder smoothing needs several periods to converge
    if spec.family == FAMILY_AROON_CROSSOVER:
        assert spec.aroon_lookback is not None
        return spec.aroon_lookback + 2
    if spec.family == FAMILY_ICHIMOKU_BREAKOUT:
        assert spec.ichimoku_base is not None and spec.ichimoku_span_b is not None
        return spec.ichimoku_base + spec.ichimoku_span_b + 2
    if spec.family == FAMILY_VORTEX:
        assert spec.vortex_lookback is not None
        return spec.vortex_lookback + 2
    if spec.family == FAMILY_LINREG_SLOPE:
        assert spec.linreg_lookback is not None
        return spec.linreg_lookback + 2
    if spec.family == FAMILY_CHANDELIER_EXIT:
        assert spec.chandelier_lookback is not None
        return spec.chandelier_lookback + 2
    if spec.family == FAMILY_SMA200_FILTER:
        assert spec.sma_filter_lookback is not None
        return spec.sma_filter_lookback + 2
    if spec.family == FAMILY_MA_RIBBON:
        assert spec.ribbon_long is not None
        return spec.ribbon_long + 2
    if spec.family == FAMILY_SQUEEZE_BREAKOUT:
        assert spec.squeeze_lookback is not None
        return spec.squeeze_lookback + 2
    if spec.family == FAMILY_ATR_BREAKOUT:
        assert spec.atr_breakout_lookback is not None
        return spec.atr_breakout_lookback + 2
    if spec.family == FAMILY_NR7_BREAKOUT:
        assert spec.nr7_lookback is not None
        return spec.nr7_lookback + 3
    if spec.family == FAMILY_INSIDE_BAR_BREAKOUT:
        return 4  # a single prior bar's range -- just the double shift(1) headroom
    if spec.family == FAMILY_VOL_REGIME_SWITCH:
        assert (
            spec.vre_vol_window is not None
            and spec.vre_regime_window is not None
            and spec.vre_lookback is not None
        )
        return spec.vre_vol_window + spec.vre_regime_window + spec.vre_lookback + 2
    if spec.family == FAMILY_VOL_OF_VOL_FILTER:
        assert (
            spec.vov_vol_window is not None
            and spec.vov_window is not None
            and spec.vov_lookback is not None
        )
        return spec.vov_vol_window + 2 * spec.vov_window + spec.vov_lookback + 2
    raise ValueError(f"no minimum-bars rule for family {spec.family!r}")


@dataclass(frozen=True)
class _RawBacktest:
    """The accounting loop's own output, before vs_benchmark is attached
    -- run_backtest and run_backtest_from_positions both produce one of
    these and then attach vs_benchmark identically, so that attachment
    can't drift between the two callers."""

    equity_curve: tuple[tuple[str, float], ...]
    total_return_pct: float
    max_drawdown_pct: float
    turnover: float
    gross_return_pct: float
    total_costs: float


def _run_accounting(
    bars: pl.DataFrame, positions: list[float], cost_model: CostModel
) -> _RawBacktest:
    """The actual bar-by-bar equity accounting -- position * bar return,
    cost charged on position CHANGE only, gross vs net tracked in
    parallel. Shared by run_backtest (signal-driven positions) and
    run_backtest_from_positions (caller-supplied positions, e.g.
    experiments/ablation.py's perturbed arms and the null-strategy test
    suite) so there is exactly one copy of this math, not three."""
    signaled = bars.with_columns(pl.Series("position", positions)).with_columns(
        pl.col("close").pct_change().fill_null(0.0).alias("_bar_return"),
        pl.col("position").diff().fill_null(pl.col("position")).abs().alias("_position_change"),
    )

    equity = STARTING_CAPITAL
    gross_equity = STARTING_CAPITAL
    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    turnover = 0.0
    total_costs = 0.0
    curve: list[tuple[str, float]] = []

    for row in signaled.iter_rows(named=True):
        position_change = row["_position_change"] or 0.0
        if position_change:
            cost = cost_model(equity * position_change)
            equity -= cost
            total_costs += cost
            turnover += position_change
        equity *= 1 + row["position"] * row["_bar_return"]
        gross_equity *= 1 + row["position"] * row["_bar_return"]
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        curve.append((row["available_at"].isoformat(), equity))

    equity_curve = tuple(curve)
    return _RawBacktest(
        equity_curve=equity_curve,
        total_return_pct=(equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100,
        max_drawdown_pct=max_drawdown * 100,
        turnover=turnover,
        gross_return_pct=(gross_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100,
        total_costs=total_costs,
    )


def run_backtest_from_positions(
    pit: PointInTimeFrame,
    symbol: str,
    positions: list[float],
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    """Same accounting and vs_benchmark treatment as run_backtest, but
    for a caller-supplied position series instead of one derived from
    signal_for() -- experiments/ablation.py's enabled/disabled arms are
    both position series, not both real StrategySpecs with a signal
    generator. `positions` must have exactly one entry per row of
    `pit.as_of(as_of_cutoff)` filtered to `symbol`, in that same sorted
    order -- the caller's responsibility, same as signal_for()'s own
    output shape.
    """
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == symbol).sort("available_at")
    if bars.height != len(positions):
        raise ValueError(
            f"positions length {len(positions)} does not match {bars.height} bars for {symbol}"
        )
    raw = _run_accounting(bars, positions, cost_model)
    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, [symbol], as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(raw.equity_curve, raw.max_drawdown_pct, benchmark_result)
    return BacktestResult(
        equity_curve=raw.equity_curve,
        total_return_pct=raw.total_return_pct,
        max_drawdown_pct=raw.max_drawdown_pct,
        turnover=raw.turnover,
        gross_return_pct=raw.gross_return_pct,
        total_costs=raw.total_costs,
        vs_benchmark=vs_benchmark,
    )


def run_backtest(
    pit: PointInTimeFrame,
    spec: StrategySpec,
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == spec.symbol).sort("available_at")
    min_bars = _min_bars_for(spec)
    if bars.height < min_bars:
        raise ValueError(
            f"not enough bars for {spec.symbol} as of {as_of_cutoff}: "
            f"need >= {min_bars}, have {bars.height}"
        )

    signaled = signal_for(bars, spec)
    raw = _run_accounting(bars, signaled["position"].to_list(), cost_model)

    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, [spec.symbol], as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(raw.equity_curve, raw.max_drawdown_pct, benchmark_result)

    return BacktestResult(
        equity_curve=raw.equity_curve,
        total_return_pct=raw.total_return_pct,
        max_drawdown_pct=raw.max_drawdown_pct,
        turnover=raw.turnover,
        gross_return_pct=raw.gross_return_pct,
        total_costs=raw.total_costs,
        vs_benchmark=vs_benchmark,
    )

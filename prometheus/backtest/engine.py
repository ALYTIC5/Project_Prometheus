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
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_GAP_FADE,
    FAMILY_GRADIENT_BOOSTING,
    FAMILY_IBS,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_LOGISTIC_REGRESSION,
    FAMILY_MACD,
    FAMILY_MFI,
    FAMILY_MOMENTUM,
    FAMILY_N_DAY_LOW,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RANDOM_FOREST,
    FAMILY_RSI,
    FAMILY_SMA_DISTANCE,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_SVM,
    FAMILY_TRIX,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_VOL_BREAKOUT,
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
        (pl.col("_fast") > pl.col("_slow"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
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
        (pl.col("close") < pl.col("_lower"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
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
            (pl.col("_rsi") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_macd") > pl.col("_signal_line"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_pct_k") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
    n = len(highs)
    raw = [0.0] * n
    if n < 2:
        return bars.with_columns(pl.Series("position", raw))

    uptrend = True
    sar = float(lows[0])
    ep = float(highs[0])
    af = af_start
    raw[0] = 1.0

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

    raw_series = pl.Series("_raw_trend", raw)
    return bars.with_columns(raw_series.shift(1).fill_null(0.0).alias("position"))


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
            (pl.col("_pct_r") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_cci") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_ao") > 0.0)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
        return bars.with_columns(pl.Series("position", [0.0] * n))

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

    raw_series = pl.Series("_raw_trend", raw)
    return frame.with_columns(raw_series.shift(1).fill_null(0.0).alias("position"))


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
            (pl.col("_trix") > 0.0)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("close") < pl.col("_lower"))
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_pctb") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
            (pl.col("_zscore") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
        (pl.col("_ibs") < oversold).cast(pl.Float64).shift(1).fill_null(0.0).alias("position")
    )


def _n_day_low_signal(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Long whenever today's close makes a new N-day low (close <=
    rolling_min(close, lookback), the window INCLUDING today's own close
    -- a fresh low is a fresh low the day it happens). Stateless per-bar
    condition, same shape as every other mean-reversion family here."""
    return bars.with_columns(
        pl.col("close").rolling_min(lookback).alias("_rolling_low")
    ).with_columns(
        (pl.col("close") <= pl.col("_rolling_low"))
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
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
        (pl.col("_down_run") >= run_length)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
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
        (((pl.col("_sma") - pl.col("close")) / pl.col("_sma")) > oversold)
        .cast(pl.Float64)
        .shift(1)
        .fill_null(0.0)
        .alias("position")
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
        (pl.col("_uo") < oversold).cast(pl.Float64).shift(1).fill_null(0.0).alias("position")
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
            (pl.col("_mfi") < oversold)
            .cast(pl.Float64)
            .shift(1)
            .fill_null(0.0)
            .alias("position")
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
        (pl.col("_gap") < -threshold)
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

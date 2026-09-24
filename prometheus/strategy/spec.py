"""Thirteen concrete, fully-parameterized strategy families: SMA
crossover (momentum), Bollinger mean-reversion, Donchian-channel
volatility breakout, Wilder's RSI mean-reversion, Appel's MACD
trend-following, Lane's Stochastic Oscillator mean-reversion, Wilder's
Parabolic SAR trend-following, Keltner Channel volatility breakout,
Larry Williams' %R mean-reversion, Donald Lambert's CCI mean-reversion,
Bill Williams' Awesome Oscillator momentum, Olivier Seban's SuperTrend
trend-following, and TRIX momentum -- the "classic templates" PROMPT 6
names as the baseline every future component must beat. All thirteen
are cited, standard technical constructions, not invented formulas.
Every family after the original three was added later with the same
justification and the same touch points (backtest/engine.py's signal
dispatch, research/generate.py's grid, research/llm/hypothesis.py's
family->fields mapping) VOL_BREAKOUT first established.

Deterministic, no free text, no LLM -- CLAUDE.md's own stated null
hypothesis is that LLM-generated research loses to static baselines until
proven otherwise, so the first strategy types here are not an LLM's output.

Carry (PROMPT 6's fourth named template) is deliberately NOT built: it
needs futures funding-rate or spot-futures basis data, and this project's
ccxt pipeline is spot-OHLCV only -- no futures ingestion exists anywhere
in prometheus/data/. Building it would mean fabricating a signal from
data that doesn't exist. See docs/DEFERRED.md.

Generalized (PROMPT 3) with the fields that have real, non-decorative
content today: parent_id (spec-level lineage -- which spec this was
mutated from; distinct from experiments.parent_experiment_id, which
already tracks *experiment* lineage), description, source (provenance),
and expected_horizon (required -- real input to Prompt 5's
validation/decay.py, not decoration).

Generalized again (PROMPT 6) with per-family optional parameter fields
rather than a discriminated union of spec types -- same shape fast_window/
slow_window already had, just widened, so config_hash(), the DB column
shape, and every existing call site typed against a single StrategySpec
stay unchanged. A model_validator enforces that a spec only ever carries
the parameters its own family actually uses -- MOMENTUM's
lookback_window/band_multiplier/breakout_window/exit_window all stay
None, and so on for each family -- so "this field is set" always means
"this family reads it," never decorative always-None scaffolding.

Deliberately NOT added: strategy_id (stays a DB-assigned id from
core.ids.next_strategy_id, generated at persistence time -- inside the
frozen, hashed spec it would be circular, since the id doesn't exist
until after the spec is first persisted), universe (redundant with
symbol until an engine can actually trade more than one -- see
docs/DEFERRED.md), features/signals/entry_rules/exit_rules/
position_sizing/risk_rules (the DSL surface -- strategy/dsl.py is
deliberately deferred to Prompt 9, and empty placeholder fields with no
consumer would be exactly the decorative scaffolding CLAUDE.md's
engineering rules forbid), lineage (redundant with parent_id here and
with the real experiment-lineage tracking in experiments/lineage.py).
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, model_validator

FAMILY_MOMENTUM = "MOMENTUM"
FAMILY_BOLLINGER = "BOLLINGER"
FAMILY_VOL_BREAKOUT = "VOL_BREAKOUT"
FAMILY_RSI = "RSI"
FAMILY_MACD = "MACD"
FAMILY_RANDOM_FOREST = "RANDOM_FOREST"
FAMILY_GRADIENT_BOOSTING = "GRADIENT_BOOSTING"
FAMILY_LOGISTIC_REGRESSION = "LOGISTIC_REGRESSION"
FAMILY_SVM = "SVM"
FAMILY_STOCHASTIC = "STOCHASTIC"
FAMILY_PARABOLIC_SAR = "PARABOLIC_SAR"
FAMILY_KELTNER = "KELTNER"
FAMILY_WILLIAMS_R = "WILLIAMS_R"
FAMILY_CCI = "CCI"
FAMILY_AWESOME_OSCILLATOR = "AWESOME_OSCILLATOR"
FAMILY_SUPERTREND = "SUPERTREND"
FAMILY_TRIX = "TRIX"
FAMILY_KELTNER_REVERSION = "KELTNER_REVERSION"
FAMILY_BOLLINGER_PCTB = "BOLLINGER_PCTB"
FAMILY_ZSCORE = "ZSCORE"
FAMILY_IBS = "IBS"
FAMILY_N_DAY_LOW = "N_DAY_LOW"
FAMILY_CONSECUTIVE_DOWN = "CONSECUTIVE_DOWN"
FAMILY_SMA_DISTANCE = "SMA_DISTANCE"
FAMILY_ULTIMATE_OSCILLATOR = "ULTIMATE_OSCILLATOR"
FAMILY_MFI = "MFI"
FAMILY_GAP_FADE = "GAP_FADE"
FAMILY_EMA_CROSSOVER = "EMA_CROSSOVER"
FAMILY_TRIPLE_MA_ALIGNMENT = "TRIPLE_MA_ALIGNMENT"
FAMILY_DEMA_CROSSOVER = "DEMA_CROSSOVER"
FAMILY_HULL_MA_TREND = "HULL_MA_TREND"
FAMILY_KAMA_TREND = "KAMA_TREND"
FAMILY_TSMOM = "TSMOM"
FAMILY_ADX_DI_CROSSOVER = "ADX_DI_CROSSOVER"
FAMILY_AROON_CROSSOVER = "AROON_CROSSOVER"
FAMILY_ICHIMOKU_BREAKOUT = "ICHIMOKU_BREAKOUT"
FAMILY_VORTEX = "VORTEX"
FAMILY_LINREG_SLOPE = "LINREG_SLOPE"
FAMILY_CHANDELIER_EXIT = "CHANDELIER_EXIT"
FAMILY_SMA200_FILTER = "SMA200_FILTER"
FAMILY_MA_RIBBON = "MA_RIBBON"
FAMILY_SQUEEZE_BREAKOUT = "SQUEEZE_BREAKOUT"
FAMILY_ATR_BREAKOUT = "ATR_BREAKOUT"
FAMILY_NR7_BREAKOUT = "NR7_BREAKOUT"
FAMILY_INSIDE_BAR_BREAKOUT = "INSIDE_BAR_BREAKOUT"
FAMILY_VOL_REGIME_SWITCH = "VOL_REGIME_SWITCH"
FAMILY_VOL_OF_VOL_FILTER = "VOL_OF_VOL_FILTER"
FAMILIES = (
    FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT, FAMILY_RSI, FAMILY_MACD,
    FAMILY_STOCHASTIC, FAMILY_PARABOLIC_SAR, FAMILY_KELTNER,
    FAMILY_WILLIAMS_R, FAMILY_CCI, FAMILY_AWESOME_OSCILLATOR, FAMILY_SUPERTREND, FAMILY_TRIX,
    FAMILY_KELTNER_REVERSION, FAMILY_BOLLINGER_PCTB, FAMILY_ZSCORE, FAMILY_IBS,
    FAMILY_N_DAY_LOW, FAMILY_CONSECUTIVE_DOWN, FAMILY_SMA_DISTANCE,
    FAMILY_ULTIMATE_OSCILLATOR, FAMILY_MFI, FAMILY_GAP_FADE,
    FAMILY_EMA_CROSSOVER, FAMILY_TRIPLE_MA_ALIGNMENT, FAMILY_DEMA_CROSSOVER,
    FAMILY_HULL_MA_TREND, FAMILY_KAMA_TREND, FAMILY_TSMOM, FAMILY_ADX_DI_CROSSOVER,
    FAMILY_AROON_CROSSOVER, FAMILY_ICHIMOKU_BREAKOUT, FAMILY_VORTEX,
    FAMILY_LINREG_SLOPE, FAMILY_CHANDELIER_EXIT, FAMILY_SMA200_FILTER, FAMILY_MA_RIBBON,
    FAMILY_SQUEEZE_BREAKOUT, FAMILY_ATR_BREAKOUT, FAMILY_NR7_BREAKOUT,
    FAMILY_INSIDE_BAR_BREAKOUT, FAMILY_VOL_REGIME_SWITCH, FAMILY_VOL_OF_VOL_FILTER,
)

# The signal-strength contract (validation/metrics.py's IC/ICIR calculation):
# every family whose signal_for() output is expected to carry a continuous
# `_signal_strength` column, keyed here so metrics.py never has to guess at
# runtime. True means signal_for() MUST emit `_signal_strength` -- if it
# doesn't, that's a real bug (SignalStrengthContractViolation), not a reason
# to quietly return None. False is a declared, deliberate absence: these six
# families are breakout/regime-switch constructions built from boolean
# state-machine conditions with no cited continuous form (VOL_BREAKOUT/
# SQUEEZE_BREAKOUT/NR7_BREAKOUT/INSIDE_BAR_BREAKOUT are persist-until-exit or
# single-trigger-event patterns; VOL_REGIME_SWITCH/VOL_OF_VOL_FILTER switch
# between two boolean conditions) -- IC/ICIR are honestly None for these,
# same "absent beats fabricated" rule RotationSpec's own information_
# coefficient=None already uses (experiments/runner.py's
# validate_rotation_specs). Every FAMILIES member plus the four ML families
# (not in FAMILIES -- see research/ml/generate.py) must have an entry;
# tests/test_validation_metrics.py parametrizes over every one to keep this
# honest as new families are added.
EMITS_SIGNAL_STRENGTH: dict[str, bool] = {
    FAMILY_MOMENTUM: True,
    FAMILY_BOLLINGER: True,
    FAMILY_VOL_BREAKOUT: False,
    FAMILY_RSI: True,
    FAMILY_MACD: True,
    FAMILY_RANDOM_FOREST: True,
    FAMILY_GRADIENT_BOOSTING: True,
    FAMILY_LOGISTIC_REGRESSION: True,
    FAMILY_SVM: True,
    FAMILY_STOCHASTIC: True,
    FAMILY_PARABOLIC_SAR: True,
    FAMILY_KELTNER: True,
    FAMILY_WILLIAMS_R: True,
    FAMILY_CCI: True,
    FAMILY_AWESOME_OSCILLATOR: True,
    FAMILY_SUPERTREND: True,
    FAMILY_TRIX: True,
    FAMILY_KELTNER_REVERSION: True,
    FAMILY_BOLLINGER_PCTB: True,
    FAMILY_ZSCORE: True,
    FAMILY_IBS: True,
    FAMILY_N_DAY_LOW: True,
    FAMILY_CONSECUTIVE_DOWN: True,
    FAMILY_SMA_DISTANCE: True,
    FAMILY_ULTIMATE_OSCILLATOR: True,
    FAMILY_MFI: True,
    FAMILY_GAP_FADE: True,
    FAMILY_EMA_CROSSOVER: True,
    FAMILY_TRIPLE_MA_ALIGNMENT: True,
    FAMILY_DEMA_CROSSOVER: True,
    FAMILY_HULL_MA_TREND: True,
    FAMILY_KAMA_TREND: True,
    FAMILY_TSMOM: True,
    FAMILY_ADX_DI_CROSSOVER: True,
    FAMILY_AROON_CROSSOVER: True,
    FAMILY_ICHIMOKU_BREAKOUT: True,
    FAMILY_VORTEX: True,
    FAMILY_LINREG_SLOPE: True,
    FAMILY_CHANDELIER_EXIT: True,
    FAMILY_SMA200_FILTER: True,
    FAMILY_MA_RIBBON: True,
    FAMILY_SQUEEZE_BREAKOUT: False,
    FAMILY_ATR_BREAKOUT: True,
    FAMILY_NR7_BREAKOUT: False,
    FAMILY_INSIDE_BAR_BREAKOUT: False,
    FAMILY_VOL_REGIME_SWITCH: False,
    FAMILY_VOL_OF_VOL_FILTER: False,
}

# Each family's own parameter fields -- the set a spec of that family MUST
# have set, with every other family's fields left None. Enforced by
# _params_match_family below, not left to convention: a spec claiming two
# families' parameters at once (or none) is a real construction error, not
# something the engine should silently guess about.
#
# DRIFT WARNING: prometheus/research/llm/hypothesis.py keeps its own copy
# of this family->fields mapping in TWO places (the _SYSTEM_PROMPT's
# field listing, and the param_fields dict inside generate_hypothesis).
# Adding a family here means updating both of those in step, or the LLM
# generator silently keeps proposing only the old families.
_FAMILY_PARAMS: dict[str, tuple[str, ...]] = {
    FAMILY_MOMENTUM: ("fast_window", "slow_window"),
    FAMILY_BOLLINGER: ("lookback_window", "band_multiplier"),
    FAMILY_VOL_BREAKOUT: ("breakout_window", "exit_window"),
    FAMILY_RSI: ("rsi_lookback", "rsi_oversold"),
    FAMILY_MACD: ("macd_fast", "macd_slow", "macd_signal"),
    FAMILY_RANDOM_FOREST: ("rf_train_window", "rf_retrain_interval", "rf_predict_threshold"),
    FAMILY_GRADIENT_BOOSTING: ("gb_train_window", "gb_retrain_interval", "gb_predict_threshold"),
    FAMILY_LOGISTIC_REGRESSION: ("lr_train_window", "lr_retrain_interval", "lr_predict_threshold"),
    FAMILY_SVM: ("svm_train_window", "svm_retrain_interval", "svm_predict_threshold"),
    FAMILY_STOCHASTIC: ("stoch_lookback", "stoch_oversold"),
    FAMILY_PARABOLIC_SAR: ("sar_af_start", "sar_af_increment", "sar_af_max"),
    FAMILY_KELTNER: ("keltner_lookback", "keltner_multiplier"),
    FAMILY_WILLIAMS_R: ("williams_lookback", "williams_oversold"),
    FAMILY_CCI: ("cci_lookback", "cci_oversold"),
    FAMILY_AWESOME_OSCILLATOR: ("ao_fast", "ao_slow"),
    FAMILY_SUPERTREND: ("supertrend_lookback", "supertrend_multiplier"),
    FAMILY_TRIX: ("trix_lookback",),
    FAMILY_KELTNER_REVERSION: ("keltner_rev_lookback", "keltner_rev_multiplier"),
    FAMILY_BOLLINGER_PCTB: ("pctb_lookback", "pctb_multiplier", "pctb_oversold"),
    FAMILY_ZSCORE: ("zscore_lookback", "zscore_oversold"),
    FAMILY_IBS: ("ibs_oversold",),
    FAMILY_N_DAY_LOW: ("ndaylow_lookback",),
    FAMILY_CONSECUTIVE_DOWN: ("consecutive_down_days",),
    FAMILY_SMA_DISTANCE: ("sma_dist_lookback", "sma_dist_oversold"),
    FAMILY_ULTIMATE_OSCILLATOR: ("uo_short", "uo_mid", "uo_long", "uo_oversold"),
    FAMILY_MFI: ("mfi_lookback", "mfi_oversold"),
    FAMILY_GAP_FADE: ("gap_fade_threshold",),
    FAMILY_EMA_CROSSOVER: ("ema_fast_window", "ema_slow_window"),
    FAMILY_TRIPLE_MA_ALIGNMENT: ("tma_fast_window", "tma_mid_window", "tma_slow_window"),
    FAMILY_DEMA_CROSSOVER: ("dema_fast_window", "dema_slow_window"),
    FAMILY_HULL_MA_TREND: ("hull_lookback",),
    FAMILY_KAMA_TREND: ("kama_lookback", "kama_fast_sc", "kama_slow_sc"),
    FAMILY_TSMOM: ("tsmom_lookback_days", "tsmom_skip_days"),
    FAMILY_ADX_DI_CROSSOVER: ("adx_lookback",),
    FAMILY_AROON_CROSSOVER: ("aroon_lookback",),
    FAMILY_ICHIMOKU_BREAKOUT: ("ichimoku_conversion", "ichimoku_base", "ichimoku_span_b"),
    FAMILY_VORTEX: ("vortex_lookback",),
    FAMILY_LINREG_SLOPE: ("linreg_lookback",),
    FAMILY_CHANDELIER_EXIT: ("chandelier_lookback", "chandelier_multiplier"),
    FAMILY_SMA200_FILTER: ("sma_filter_lookback",),
    FAMILY_MA_RIBBON: ("ribbon_short", "ribbon_mid", "ribbon_long"),
    FAMILY_SQUEEZE_BREAKOUT: ("squeeze_lookback",),
    FAMILY_ATR_BREAKOUT: ("atr_breakout_lookback", "atr_breakout_multiplier"),
    FAMILY_NR7_BREAKOUT: ("nr7_lookback",),
    FAMILY_INSIDE_BAR_BREAKOUT: ("inside_bar_buffer",),
    FAMILY_VOL_REGIME_SWITCH: ("vre_vol_window", "vre_regime_window", "vre_lookback"),
    FAMILY_VOL_OF_VOL_FILTER: ("vov_vol_window", "vov_window", "vov_lookback"),
}
_ALL_PARAM_FIELDS = tuple(
    field for fields in _FAMILY_PARAMS.values() for field in fields
)

# The fields that determine backtest behavior -- what config_hash()
# identifies. Deliberately excludes parent_id/description/source/
# expected_horizon: those are metadata and provenance, not identity. Two
# mutations from different parents that land on the same executable
# parameters ARE the same strategy for dedup purposes ("this fingerprint
# prevents rediscovering the same strategy forever") -- hashing the whole
# model would break that the moment lineage or wording differs. Widened
# (PROMPT 6) to every family's param fields -- a None for a field this
# spec's family doesn't use still serializes consistently, so two MOMENTUM
# specs keep hashing identically to each other and never collide with a
# BOLLINGER spec (different family string, different field set populated).
_IDENTITY_FIELDS = ("family", "symbol", "timeframe", *_ALL_PARAM_FIELDS)


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str = FAMILY_MOMENTUM
    symbol: str
    timeframe: str

    # MOMENTUM (SMA crossover).
    fast_window: int | None = None
    slow_window: int | None = None
    # BOLLINGER (mean ± band_multiplier * std over lookback_window --
    # John Bollinger's own standard construction, not an invented one).
    lookback_window: int | None = None
    band_multiplier: float | None = None
    # VOL_BREAKOUT (Donchian channel, the Turtle Trading convention: a
    # longer entry window, a shorter exit window).
    breakout_window: int | None = None
    exit_window: int | None = None
    # RSI (Wilder's own construction): long when RSI drops below the
    # oversold threshold, flat otherwise.
    rsi_lookback: int | None = None
    rsi_oversold: float | None = None
    # MACD (Gerald Appel's own construction): long when the fast/slow EMA
    # difference crosses above its own signal-line EMA.
    macd_fast: int | None = None
    macd_slow: int | None = None
    macd_signal: int | None = None
    # RANDOM_FOREST: a walk-forward-retrained RandomForestClassifier
    # predicting next-bar direction. Deliberately NOT in FAMILIES (see
    # docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md)
    # -- a generation component measured against the baseline, not a
    # member of it.
    rf_train_window: int | None = None
    rf_retrain_interval: int | None = None
    rf_predict_threshold: float | None = None
    # GRADIENT_BOOSTING: same walk-forward shape as RANDOM_FOREST, a
    # GradientBoostingClassifier instead. Deliberately NOT in FAMILIES,
    # same reasoning as RANDOM_FOREST.
    gb_train_window: int | None = None
    gb_retrain_interval: int | None = None
    gb_predict_threshold: float | None = None
    # LOGISTIC_REGRESSION: the simplest real ML baseline, same
    # walk-forward shape. Deliberately NOT in FAMILIES.
    lr_train_window: int | None = None
    lr_retrain_interval: int | None = None
    lr_predict_threshold: float | None = None
    # SVM: an RBF-kernel support vector classifier, same walk-forward
    # shape. Deliberately NOT in FAMILIES.
    svm_train_window: int | None = None
    svm_retrain_interval: int | None = None
    svm_predict_threshold: float | None = None
    # STOCHASTIC (George Lane's own construction): %K = 100 * (close -
    # lowest_low_n) / (highest_high_n - lowest_low_n). Long when %K drops
    # below the oversold threshold, flat otherwise -- same stateless
    # shape as RSI, just a different oscillator.
    stoch_lookback: int | None = None
    stoch_oversold: float | None = None
    # PARABOLIC_SAR (Wilder's own construction, "New Concepts in
    # Technical Trading Systems", 1978): a trend-following stop-and-
    # reverse whose acceleration factor starts at af_start and increases
    # by af_increment on every new extreme point, capped at af_max.
    sar_af_start: float | None = None
    sar_af_increment: float | None = None
    sar_af_max: float | None = None
    # KELTNER (an ATR-normalized volatility breakout, the same Turtle-
    # style entry/persist/exit shape VOL_BREAKOUT uses, but with bands
    # around an EMA rather than Donchian highs/lows).
    keltner_lookback: int | None = None
    keltner_multiplier: float | None = None
    # WILLIAMS_R (Larry Williams' own construction): %R = -100 *
    # (highest_high_n - close) / (highest_high_n - lowest_low_n). Long
    # when %R drops below the oversold threshold (a value in (-100, 0)).
    williams_lookback: int | None = None
    williams_oversold: float | None = None
    # CCI (Donald Lambert's own Commodity Channel Index): (typical_price
    # - SMA(typical_price)) / (0.015 * mean_deviation). Long when CCI
    # drops below the oversold threshold (Lambert's own -100 zone).
    cci_lookback: int | None = None
    cci_oversold: float | None = None
    # AWESOME_OSCILLATOR (Bill Williams' own construction): SMA(median
    # price, ao_fast) - SMA(median price, ao_slow). Long on a zero-line
    # crossover (AO > 0).
    ao_fast: int | None = None
    ao_slow: int | None = None
    # SUPERTREND (Olivier Seban's own construction): ATR-based bands
    # around the bar's own midpoint, with Wilder-style hysteresis
    # deciding which band is "the" SuperTrend line. Genuinely sequential,
    # same treatment as PARABOLIC_SAR.
    supertrend_lookback: int | None = None
    supertrend_multiplier: float | None = None
    # TRIX: the rate of change of a triple-smoothed EMA. Long on a
    # zero-line crossover (TRIX > 0).
    trix_lookback: int | None = None
    # KELTNER_REVERSION: the inverse of KELTNER -- same ATR-normalized
    # band construction, but long when price drops BELOW the lower band
    # (mean reversion) rather than above the upper band (breakout).
    keltner_rev_lookback: int | None = None
    keltner_rev_multiplier: float | None = None
    # BOLLINGER_PCTB: John Bollinger's own %B = (close - lower_band) /
    # (upper_band - lower_band), a continuous 0-1 (typically) normalized
    # position within the bands -- distinct from BOLLINGER's own binary
    # "below the lower band" touch. Long when %B drops below its own
    # oversold threshold.
    pctb_lookback: int | None = None
    pctb_multiplier: float | None = None
    pctb_oversold: float | None = None
    # ZSCORE: (close - SMA(close, lookback)) / rolling_std(close,
    # lookback) -- a standard rolling z-score of price itself (not an
    # oscillator built from a scaled indicator). Long when the z-score
    # drops below its own oversold threshold.
    zscore_lookback: int | None = None
    zscore_oversold: float | None = None
    # IBS (Internal Bar Strength): (close - low) / (high - low), a
    # cited single-bar mean-reversion construction (no lookback --
    # it is a per-bar ratio). Long when IBS drops below its own
    # oversold threshold (a value in (0, 1)).
    ibs_oversold: float | None = None
    # N_DAY_LOW: long whenever today's close makes a new N-day low
    # (close <= rolling_min(close, lookback)) -- the classic "buy the
    # dip at a fresh low" mean-reversion construction.
    ndaylow_lookback: int | None = None
    # CONSECUTIVE_DOWN: long after `consecutive_down_days` consecutive
    # down-closes in a row -- a run-length mean-reversion construction.
    consecutive_down_days: int | None = None
    # SMA_DISTANCE: long when close is more than `sma_dist_oversold`
    # fraction BELOW its own rolling SMA(sma_dist_lookback) -- distance-
    # from-trend mean reversion (the classic use case is a 200-day SMA,
    # not fixed here since the lookback itself is swept).
    sma_dist_lookback: int | None = None
    sma_dist_oversold: float | None = None
    # ULTIMATE_OSCILLATOR (Larry Williams' own construction, 1976): a
    # weighted average of buying-pressure/true-range ratios across three
    # timeframes (uo_short/uo_mid/uo_long -- his own published 7/14/28
    # convention), weighted 4:2:1 short-to-long. Long when UO drops
    # below its own oversold threshold (Williams' own <30 zone).
    uo_short: int | None = None
    uo_mid: int | None = None
    uo_long: int | None = None
    uo_oversold: float | None = None
    # MFI (Money Flow Index): a volume-weighted RSI -- typical price *
    # volume splits into positive/negative money flow by day-over-day
    # typical-price direction, then the same RSI-style ratio-to-0-100
    # scaling Wilder's RSI uses. Long when MFI drops below its own
    # oversold threshold.
    mfi_lookback: int | None = None
    mfi_oversold: float | None = None
    # GAP_FADE: long when today's open gaps DOWN from yesterday's close
    # by more than `gap_fade_threshold` (a fraction), fading the gap on
    # the expectation of an intraday-to-next-close reversion back up.
    gap_fade_threshold: float | None = None
    # EMA_CROSSOVER: the EMA analogue of MOMENTUM's own SMA crossover --
    # long when the fast EMA is above the slow EMA. A genuinely distinct
    # construction (exponential vs simple weighting), not a copy of
    # MOMENTUM under a different name.
    ema_fast_window: int | None = None
    ema_slow_window: int | None = None
    # TRIPLE_MA_ALIGNMENT: long only when three SMAs are in strictly
    # ascending order (fast > mid > slow), a stronger trend-confirmation
    # filter than a single crossover.
    tma_fast_window: int | None = None
    tma_mid_window: int | None = None
    tma_slow_window: int | None = None
    # DEMA_CROSSOVER: Patrick Mulloy's own Double EMA construction
    # (DEMA = 2*EMA - EMA(EMA)), reduces lag versus a plain EMA. Long
    # when the fast DEMA is above the slow DEMA.
    dema_fast_window: int | None = None
    dema_slow_window: int | None = None
    # HULL_MA_TREND (Alan Hull's own construction): HMA = WMA(2*WMA(n/2)
    # - WMA(n), sqrt(n)) -- a weighted-MA-of-differences construction
    # designed to reduce lag more aggressively than DEMA/TEMA. Long when
    # today's HMA is rising versus the prior bar's HMA.
    hull_lookback: int | None = None
    # KAMA_TREND (Perry Kaufman's own Adaptive Moving Average): the
    # smoothing constant adapts between kama_fast_sc and kama_slow_sc
    # periods based on a trailing efficiency ratio (trending vs choppy
    # markets get different responsiveness). Long when today's KAMA is
    # rising versus the prior bar's KAMA.
    kama_lookback: int | None = None
    kama_fast_sc: int | None = None
    kama_slow_sc: int | None = None
    # TSMOM (Moskowitz, Ooi & Pedersen 2012's own time-series momentum,
    # the cited "12-1 month" convention -- Jegadeesh & Titman's skip-
    # the-most-recent-month adjustment to avoid short-term reversal
    # contamination): long when the trailing return over
    # tsmom_lookback_days, ending tsmom_skip_days before today, is
    # positive.
    tsmom_lookback_days: int | None = None
    tsmom_skip_days: int | None = None
    # ADX_DI_CROSSOVER (Wilder's own Average Directional Index): long
    # when +DI crosses above -DI (a real trend developing), using
    # Wilder's own smoothing construction.
    adx_lookback: int | None = None
    # AROON_CROSSOVER (Tushar Chande's own construction): measures bars
    # since the most recent high/low within the lookback window. Long
    # when Aroon-Up crosses above Aroon-Down.
    aroon_lookback: int | None = None
    # ICHIMOKU_BREAKOUT (Goichi Hosoda's own construction, his own
    # published 9/26/52 default periods): long when close breaks above
    # the cloud (the higher of span A / span B, span-B-period-ahead
    # projected values evaluated as of today's own bar so nothing here
    # depends on genuinely future data).
    ichimoku_conversion: int | None = None
    ichimoku_base: int | None = None
    ichimoku_span_b: int | None = None
    # VORTEX (Etienne Botes & Douglas Siepman's own construction): long
    # when +VI crosses above -VI.
    vortex_lookback: int | None = None
    # LINREG_SLOPE: the sign of a rolling linear regression's slope over
    # the lookback window -- long when the trend line's own slope is
    # positive.
    linreg_lookback: int | None = None
    # CHANDELIER_EXIT (Chuck LeBeau's own construction): a trailing
    # ATR-based stop from the highest high in the lookback window. Long
    # while close stays above the trailing stop, flat once it closes
    # below it (persist-until-exit, the same shape VOL_BREAKOUT/KELTNER
    # already use).
    chandelier_lookback: int | None = None
    chandelier_multiplier: float | None = None
    # SMA200_FILTER: STRATEGIES_100.md #19's own framing, "simple and
    # robust baseline" -- long whenever close is above its own single
    # rolling SMA, flat otherwise. Deliberately simpler than MOMENTUM's
    # two-MA crossover: one moving average, one condition, no second
    # window to overfit. The lookback itself is swept (not fixed to
    # 200), covering the classic 200-day case plus nearby variants.
    sma_filter_lookback: int | None = None
    # MA_RIBBON: three SMAs (short/mid/long) forming a "ribbon" -- long
    # when the ribbon is expanding (short-to-long spread widening versus
    # the prior bar), a trend-STRENGTH signal distinct from
    # TRIPLE_MA_ALIGNMENT's trend-DIRECTION signal (alignment order can
    # stay constant while the ribbon itself compresses or expands).
    ribbon_short: int | None = None
    ribbon_mid: int | None = None
    ribbon_long: int | None = None
    # SQUEEZE_BREAKOUT (John Carter's own "TTM Squeeze", *Mastering the
    # Trade*, 2005): squeeze_on when Bollinger Bands (2.0 std) sit
    # entirely inside Keltner Channels (1.5x ATR), both computed over
    # squeeze_lookback -- Carter's own canonical multipliers, fixed
    # rather than swept, since only the shared lookback varies in his
    # own convention. Long on the bar the squeeze releases (was on,
    # now off) with close above the basis (breaking up, not down).
    squeeze_lookback: int | None = None
    # ATR_BREAKOUT: long when close breaks above the prior close plus
    # atr_breakout_multiplier ATRs -- a volatility-scaled breakout
    # distinct from VOL_BREAKOUT's own fixed Donchian-channel construction
    # (that one breaks out of a fixed N-bar high, this one breaks out of
    # a volatility-scaled band around the prior close). Standard
    # practitioner construction, no single canonical paper.
    atr_breakout_lookback: int | None = None
    atr_breakout_multiplier: float | None = None
    # NR7_BREAKOUT (Toby Crabel's own construction, *Day Trading with
    # Short Term Price Patterns and Opening Range Breakout*, 1990): the
    # narrowest true range of the last nr7_lookback bars signals
    # imminent expansion -- long the bar after an NR7 bar if close
    # breaks above that bar's own high.
    nr7_lookback: int | None = None
    # INSIDE_BAR_BREAKOUT: an inside bar (today's high < prior high AND
    # today's low > prior low) signals compression -- long the bar after
    # an inside bar if close breaks above the inside bar's own high by
    # more than inside_bar_buffer (a fractional confirmation buffer,
    # common in price-action trading to reduce false breakouts).
    # Standard price-action pattern, no single canonical paper.
    inside_bar_buffer: float | None = None
    # VOL_REGIME_SWITCH: a practitioner regime-switching heuristic,
    # informed by the general finding that trend-following tends to
    # underperform in high-volatility/choppy regimes while mean-reversion
    # tends to dominate then (no single canonical paper). Realized
    # volatility (rolling std of returns over vre_vol_window) is compared
    # against its own rolling median over vre_regime_window: in the LOW
    # regime, long when trailing return over vre_lookback is positive
    # (trend-following); in the HIGH regime, long when close is below its
    # own SMA over vre_lookback (mean-reversion).
    vre_vol_window: int | None = None
    vre_regime_window: int | None = None
    vre_lookback: int | None = None
    # VOL_OF_VOL_FILTER: structurally similar to VOL_REGIME_SWITCH but
    # filters on the volatility OF realized volatility (a rolling std of
    # the realized-vol series itself over vov_window) rather than the
    # vol level -- a distinct empirical bet (vol-of-vol spikes often
    # precede whipsaws even when the vol LEVEL looks calm). Long when
    # trailing return over vov_lookback is positive AND today's
    # vol-of-vol is at or below its own rolling median over vov_window.
    # No single canonical paper -- a practitioner filter used in
    # systematic vol-managed strategies.
    vov_vol_window: int | None = None
    vov_window: int | None = None
    vov_lookback: int | None = None

    # How many bars ahead this strategy's signal is claimed to matter.
    # Required, no default: CLAUDE.md's own rule is "don't invent
    # thresholds silently" -- a generator must state its own horizon
    # claim, not receive a silently-chosen one.
    expected_horizon: int

    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"

    @model_validator(mode="after")
    def _params_match_family(self) -> StrategySpec:
        if self.family not in _FAMILY_PARAMS:
            raise ValueError(f"unknown family: {self.family!r}")
        required = _FAMILY_PARAMS[self.family]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"family {self.family!r} requires {missing}")
        foreign = [
            f
            for f in _ALL_PARAM_FIELDS
            if f not in required and getattr(self, f) is not None
        ]
        if foreign:
            raise ValueError(f"family {self.family!r} must not set {foreign}")
        if self.family == FAMILY_MOMENTUM and self.slow_window <= self.fast_window:  # type: ignore[operator]
            raise ValueError("slow_window must be greater than fast_window")
        if self.family == FAMILY_VOL_BREAKOUT and self.exit_window >= self.breakout_window:  # type: ignore[operator]
            raise ValueError("exit_window must be less than breakout_window")
        if self.family == FAMILY_MACD and self.macd_fast >= self.macd_slow:  # type: ignore[operator]
            raise ValueError("macd_fast must be less than macd_slow")
        if self.family == FAMILY_RANDOM_FOREST:
            if self.rf_train_window <= 0:  # type: ignore[operator]
                raise ValueError("rf_train_window must be positive")
            if not (0 < self.rf_retrain_interval <= self.rf_train_window):  # type: ignore[operator]
                raise ValueError("rf_retrain_interval must be in (0, rf_train_window]")
            if not (0.0 < self.rf_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("rf_predict_threshold must be in (0, 1)")
        if self.family == FAMILY_GRADIENT_BOOSTING:
            if self.gb_train_window <= 0:  # type: ignore[operator]
                raise ValueError("gb_train_window must be positive")
            if not (0 < self.gb_retrain_interval <= self.gb_train_window):  # type: ignore[operator]
                raise ValueError("gb_retrain_interval must be in (0, gb_train_window]")
            if not (0.0 < self.gb_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("gb_predict_threshold must be in (0, 1)")
        if self.family == FAMILY_LOGISTIC_REGRESSION:
            if self.lr_train_window <= 0:  # type: ignore[operator]
                raise ValueError("lr_train_window must be positive")
            if not (0 < self.lr_retrain_interval <= self.lr_train_window):  # type: ignore[operator]
                raise ValueError("lr_retrain_interval must be in (0, lr_train_window]")
            if not (0.0 < self.lr_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("lr_predict_threshold must be in (0, 1)")
        if self.family == FAMILY_SVM:
            if self.svm_train_window <= 0:  # type: ignore[operator]
                raise ValueError("svm_train_window must be positive")
            if not (0 < self.svm_retrain_interval <= self.svm_train_window):  # type: ignore[operator]
                raise ValueError("svm_retrain_interval must be in (0, svm_train_window]")
            if not (0.0 < self.svm_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("svm_predict_threshold must be in (0, 1)")
        if self.family == FAMILY_STOCHASTIC and not (0.0 < self.stoch_oversold < 100.0):  # type: ignore[operator]
            raise ValueError("stoch_oversold must be in (0, 100)")
        if self.family == FAMILY_PARABOLIC_SAR:
            if not (0.0 < self.sar_af_start <= self.sar_af_max):  # type: ignore[operator]
                raise ValueError("sar_af_start must be in (0, sar_af_max]")
            if self.sar_af_increment <= 0:  # type: ignore[operator]
                raise ValueError("sar_af_increment must be positive")
        if self.family == FAMILY_WILLIAMS_R and not (-100.0 < self.williams_oversold < 0.0):  # type: ignore[operator]
            raise ValueError("williams_oversold must be in (-100, 0)")
        if self.family == FAMILY_CCI and self.cci_oversold >= 0.0:  # type: ignore[operator]
            raise ValueError("cci_oversold must be negative")
        if self.family == FAMILY_AWESOME_OSCILLATOR and self.ao_fast >= self.ao_slow:  # type: ignore[operator]
            raise ValueError("ao_fast must be less than ao_slow")
        if self.family == FAMILY_BOLLINGER_PCTB and not (0.0 <= self.pctb_oversold < 1.0):  # type: ignore[operator]
            raise ValueError("pctb_oversold must be in [0, 1)")
        if self.family == FAMILY_ZSCORE and self.zscore_oversold >= 0.0:  # type: ignore[operator]
            raise ValueError("zscore_oversold must be negative")
        if self.family == FAMILY_IBS and not (0.0 < self.ibs_oversold < 1.0):  # type: ignore[operator]
            raise ValueError("ibs_oversold must be in (0, 1)")
        if self.family == FAMILY_CONSECUTIVE_DOWN and self.consecutive_down_days <= 0:  # type: ignore[operator]
            raise ValueError("consecutive_down_days must be positive")
        if self.family == FAMILY_SMA_DISTANCE and not (0.0 < self.sma_dist_oversold < 1.0):  # type: ignore[operator]
            raise ValueError("sma_dist_oversold must be in (0, 1)")
        if self.family == FAMILY_ULTIMATE_OSCILLATOR:
            if not (self.uo_short < self.uo_mid < self.uo_long):  # type: ignore[operator]
                raise ValueError("uo_short must be < uo_mid must be < uo_long")
            if not (0.0 < self.uo_oversold < 100.0):  # type: ignore[operator]
                raise ValueError("uo_oversold must be in (0, 100)")
        if self.family == FAMILY_MFI and not (0.0 < self.mfi_oversold < 100.0):  # type: ignore[operator]
            raise ValueError("mfi_oversold must be in (0, 100)")
        if self.family == FAMILY_GAP_FADE and self.gap_fade_threshold <= 0.0:  # type: ignore[operator]
            raise ValueError("gap_fade_threshold must be positive")
        if self.family == FAMILY_EMA_CROSSOVER and self.ema_slow_window <= self.ema_fast_window:  # type: ignore[operator]
            raise ValueError("ema_slow_window must be greater than ema_fast_window")
        if self.family == FAMILY_TRIPLE_MA_ALIGNMENT and not (
            self.tma_fast_window < self.tma_mid_window < self.tma_slow_window  # type: ignore[operator]
        ):
            raise ValueError("tma_fast_window must be < tma_mid_window must be < tma_slow_window")
        if self.family == FAMILY_DEMA_CROSSOVER and self.dema_slow_window <= self.dema_fast_window:  # type: ignore[operator]
            raise ValueError("dema_slow_window must be greater than dema_fast_window")
        if self.family == FAMILY_KAMA_TREND and self.kama_fast_sc >= self.kama_slow_sc:  # type: ignore[operator]
            raise ValueError("kama_fast_sc must be less than kama_slow_sc")
        if self.family == FAMILY_TSMOM and self.tsmom_skip_days >= self.tsmom_lookback_days:  # type: ignore[operator]
            raise ValueError("tsmom_skip_days must be less than tsmom_lookback_days")
        if self.family == FAMILY_ICHIMOKU_BREAKOUT and not (
            self.ichimoku_conversion < self.ichimoku_base < self.ichimoku_span_b  # type: ignore[operator]
        ):
            raise ValueError(
                "ichimoku_conversion must be < ichimoku_base must be < ichimoku_span_b"
            )
        if self.family == FAMILY_CHANDELIER_EXIT and self.chandelier_multiplier <= 0.0:  # type: ignore[operator]
            raise ValueError("chandelier_multiplier must be positive")
        if self.family == FAMILY_ATR_BREAKOUT and self.atr_breakout_multiplier <= 0.0:  # type: ignore[operator]
            raise ValueError("atr_breakout_multiplier must be positive")
        if self.family == FAMILY_INSIDE_BAR_BREAKOUT and self.inside_bar_buffer < 0.0:  # type: ignore[operator]
            raise ValueError("inside_bar_buffer must be non-negative")
        if self.family == FAMILY_MA_RIBBON and not (
            self.ribbon_short < self.ribbon_mid < self.ribbon_long  # type: ignore[operator]
        ):
            raise ValueError("ribbon_short must be < ribbon_mid must be < ribbon_long")
        return self

    @property
    def parameters(self) -> dict[str, float]:
        """A generic, family-agnostic view of this spec's tunable
        parameters -- the family's own populated fields, not a separately
        stored dict, so there is nothing to desync. Prompt 7's
        complexity-counting code can call this without knowing this
        family's specific field names."""
        return {
            field: float(getattr(self, field))
            for field in _FAMILY_PARAMS[self.family]
        }

    def config_hash(self) -> str:
        """Deterministic identity for this exact spec's BEHAVIOR (see
        _IDENTITY_FIELDS) -- same pattern as
        prometheus.data.versioning.compute_content_hash: a stable hash of
        canonical content, not Python's salted-per-process hash()."""
        canonical = self.model_dump(include=set(_IDENTITY_FIELDS))
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def with_updates(self, **updates: object) -> StrategySpec:
        """A validated copy -- NOT `model_copy(update=...)`, which is
        documented Pydantic v2 behavior to skip validation entirely and
        was confirmed, by actually testing it, to happily produce a spec
        with slow_window <= fast_window. Going through the real
        constructor re-runs `_params_match_family`, so PROMPT 7's
        mutation/crossover code gets a real error here instead of a
        silently-invalid spec surfacing confusion somewhere downstream."""
        return StrategySpec(**{**self.model_dump(), **updates})

"""prometheus/strategy/mechanisms.py -- WHY each strategy family is supposed
to work, as a mechanism class plus one canonical sentence.

A hypothesis states its mechanism before its backtest (Phase 3). For the
deterministic generators the mechanism is the family's own; for a paper
claim it is the claim's, and the spec implementing it must belong to the
same class (validation refuses a MECHANISM_MISMATCH: a strategy that
"works" by a different mechanism than the one claimed is an accident, not
a finding).
"""
from __future__ import annotations

TREND = "trend"
MEAN_REVERSION = "mean_reversion"
BREAKOUT = "breakout"
VOLATILITY_REGIME = "volatility_regime"
MACHINE_LEARNING = "machine_learning"
CROSS_SECTIONAL = "cross_sectional"

CANONICAL_MECHANISM: dict[str, str] = {
    TREND: "Prices under-react to information, so established trends persist.",
    MEAN_REVERSION: "Short-term overreaction and liquidity pressure revert toward fair value.",
    BREAKOUT: "Moves out of a quiet range signal new information that continues.",
    VOLATILITY_REGIME: "Returns differ by volatility regime; exposure should follow the regime.",
    MACHINE_LEARNING: "A model fit on past features finds a stable, repeating return pattern.",
    CROSS_SECTIONAL: "Relative strength or risk across assets persists over the rebalance horizon.",
}

MECHANISM_CLASS: dict[str, str] = {
    # trend following
    "MOMENTUM": TREND, "EMA_CROSSOVER": TREND, "DEMA_CROSSOVER": TREND,
    "TRIPLE_MA_ALIGNMENT": TREND, "MA_RIBBON": TREND, "HULL_MA_TREND": TREND,
    "KAMA_TREND": TREND, "TSMOM": TREND, "MACD": TREND, "TRIX": TREND,
    "ADX_DI_CROSSOVER": TREND, "AROON_CROSSOVER": TREND, "VORTEX": TREND,
    "LINREG_SLOPE": TREND, "PARABOLIC_SAR": TREND, "SUPERTREND": TREND,
    "CHANDELIER_EXIT": TREND, "SMA200_FILTER": TREND, "AWESOME_OSCILLATOR": TREND,
    # mean reversion
    "BOLLINGER": MEAN_REVERSION, "BOLLINGER_PCTB": MEAN_REVERSION, "RSI": MEAN_REVERSION,
    "STOCHASTIC": MEAN_REVERSION, "WILLIAMS_R": MEAN_REVERSION, "CCI": MEAN_REVERSION,
    "ZSCORE": MEAN_REVERSION, "IBS": MEAN_REVERSION, "N_DAY_LOW": MEAN_REVERSION,
    "CONSECUTIVE_DOWN": MEAN_REVERSION, "SMA_DISTANCE": MEAN_REVERSION,
    "ULTIMATE_OSCILLATOR": MEAN_REVERSION, "MFI": MEAN_REVERSION,
    "GAP_FADE": MEAN_REVERSION, "KELTNER_REVERSION": MEAN_REVERSION,
    # breakout
    "VOL_BREAKOUT": BREAKOUT, "KELTNER": BREAKOUT, "ICHIMOKU_BREAKOUT": BREAKOUT,
    "SQUEEZE_BREAKOUT": BREAKOUT, "ATR_BREAKOUT": BREAKOUT, "NR7_BREAKOUT": BREAKOUT,
    "INSIDE_BAR_BREAKOUT": BREAKOUT,
    # volatility regime
    "VOL_REGIME_SWITCH": VOLATILITY_REGIME, "VOL_OF_VOL_FILTER": VOLATILITY_REGIME,
    # machine learning
    "RANDOM_FOREST": MACHINE_LEARNING, "GRADIENT_BOOSTING": MACHINE_LEARNING,
    "LOGISTIC_REGRESSION": MACHINE_LEARNING, "SVM": MACHINE_LEARNING,
    # cross-sectional / rotation
    "ACCELERATING_DUAL_MOMENTUM": CROSS_SECTIONAL, "DEFENSIVE_ASSET_ALLOCATION": CROSS_SECTIONAL,
    "DUAL_MOMENTUM_GEM": CROSS_SECTIONAL, "EQUAL_WEIGHT_BASELINE": CROSS_SECTIONAL,
    "FIFTY_TWO_WEEK_HIGH": CROSS_SECTIONAL, "GTAA_SMA_TIMING": CROSS_SECTIONAL,
    "MINIMUM_VARIANCE": CROSS_SECTIONAL, "PROTECTIVE_ASSET_ALLOCATION": CROSS_SECTIONAL,
    "RELATIVE_STRENGTH_TOP3": CROSS_SECTIONAL, "RESIDUAL_MOMENTUM": CROSS_SECTIONAL,
    "RISK_PARITY_INVERSE_VOL": CROSS_SECTIONAL, "SECTOR_MEAN_REVERSION": CROSS_SECTIONAL,
    "SECTOR_MOMENTUM_ROTATION": CROSS_SECTIONAL,
}


def mechanism_class(family: str) -> str:
    try:
        return MECHANISM_CLASS[family]
    except KeyError:
        raise ValueError(f"no mechanism class declared for family {family!r}") from None


def canonical_mechanism(family: str) -> str:
    return CANONICAL_MECHANISM[mechanism_class(family)]

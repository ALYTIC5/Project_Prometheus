"""Feature engineering for the RANDOM_FOREST strategy family
(prometheus/backtest/ml_signal.py). Six lag-safe features plus one
training-only label column -- pure polars, no look-ahead beyond what
every other family's own "raw condition computed with today's own
close" convention already allows (backtest/engine.py's _sma_signal,
_bollinger_signal, etc. all compute their raw condition from the
CURRENT bar's own close, then shift(1) the final result once -- the
walk-forward loop in ml_signal.py applies that same final shift(1) to
this module's raw predictions, not to the features themselves).

Feature periods (14-bar RSI, 12/26/9 MACD, 10-bar rolling vol, 1-bar and
5-bar returns) are fixed constants, not StrategySpec fields -- these are
the model's fixed "sensors", not the strategy's own tunable hypothesis
(which lives in rf_train_window/rf_retrain_interval/rf_predict_threshold
instead, see strategy/spec.py). Keeping them fixed keeps the family's
identity space bounded, same reasoning generate.py's own docstrings give
for keeping each family's grid small and enumerated.
"""
from __future__ import annotations

import polars as pl

_RSI_LOOKBACK = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_VOL_LOOKBACK = 10

FEATURE_COLUMNS = ("f_ret1", "f_ret5", "f_vol10", "f_rsi", "f_macd_hist", "f_vol_chg")


def build_feature_frame(bars: pl.DataFrame) -> pl.DataFrame:
    """Returns `bars` with FEATURE_COLUMNS and a `label` column appended.
    `label` is 1.0 if the NEXT bar's close is higher than this bar's own
    close, else 0.0 -- null on the frame's own final row (no next bar
    exists), which the caller must drop before ever training on it.
    `label` is training-only: it is never itself a feature, and the
    walk-forward loop in ml_signal.py never looks at a row's own label
    when predicting that row's own position."""
    delta = pl.col("close").diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    rsi_alpha = 1.0 / _RSI_LOOKBACK

    return (
        bars.with_columns(
            pl.col("close").pct_change(1).alias("f_ret1"),
            pl.col("close").pct_change(5).alias("f_ret5"),
            (pl.col("close").rolling_std(_VOL_LOOKBACK) / pl.col("close")).alias("f_vol10"),
            pl.col("volume").pct_change(1).alias("f_vol_chg"),
            gain.alias("_gain"),
            loss.alias("_loss"),
            pl.col("close").ewm_mean(span=_MACD_FAST, adjust=False).alias("_ema_fast"),
            pl.col("close").ewm_mean(span=_MACD_SLOW, adjust=False).alias("_ema_slow"),
            (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Float64).alias("label"),
        )
        .with_columns(
            pl.col("_gain").ewm_mean(alpha=rsi_alpha, adjust=False).alias("_avg_gain"),
            pl.col("_loss").ewm_mean(alpha=rsi_alpha, adjust=False).alias("_avg_loss"),
            (pl.col("_ema_fast") - pl.col("_ema_slow")).alias("_macd"),
        )
        .with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss"))).alias("f_rsi"),
            pl.col("_macd").ewm_mean(span=_MACD_SIGNAL, adjust=False).alias("_signal_line"),
        )
        .with_columns((pl.col("_macd") - pl.col("_signal_line")).alias("f_macd_hist"))
        .drop(
            "_gain", "_loss", "_avg_gain", "_avg_loss",
            "_ema_fast", "_ema_slow", "_macd", "_signal_line",
        )
    )

"""Regime classification -- output is a label, never an automatic
rejection (PROMPTS.md's own words: "classify_regime -- classify into
bull/bear/high-vol/low-vol/trending/ranging/crisis. Output is
CLASSIFICATION, never automatic rejection").

Two separate things live here:

- `classify_current_regime`: a single current-state label from the 7
  values frontend/src/mapping/stateToVisual.ts already expects
  (uppercase). Cutoffs are TERCILES/deciles of the series' OWN trailing
  history, not absolute invented numbers -- the same approach cpz-quant's
  own certification/regime.py takes internally ("Volatility regimes:
  rolling realized vol -> terciles", `np.quantile(roll_vol, [1/3, 2/3])`).
  Not wired into world/projection.py's ClimateState yet -- PROMPT 5 scope
  decision, see docs/DEFERRED.md; this function is real and tested so
  that wiring is a follow-up, not a rebuild.
- `regime_breakdown`: a thin wrapper over cpz-quant's own
  regime_conditional_performance -- CLAUDE.md's "don't reimplement
  cpz-quant" applies here as much as to PBO/Sharpe. validation/decision.py
  uses `consistent_across_regimes` for the REGIME_SPECIALIST verdict.
"""
from __future__ import annotations

import polars as pl
from cpz_quant.certification.regime import RegimeBreakdown, regime_conditional_performance

# Terciles for vol/trend-strength level, a decile for the CRISIS override
# -- same rank-based partition cpz-quant's own regime module uses
# internally, not a dollar amount or Sharpe-style pass/fail bound.
_VOL_WINDOW = 21
_TREND_WINDOW = 50
_CRISIS_VOL_PERCENTILE = 0.90


def classify_current_regime(bars: pl.DataFrame) -> str:
    """`bars` sorted ascending by time, `close` column present. Returns
    one of BULL/BEAR/HIGH_VOL/LOW_VOL/TRENDING/RANGING/CRISIS/UNKNOWN --
    UNKNOWN only when there isn't enough history to classify at all."""
    if bars.height < max(_TREND_WINDOW, _VOL_WINDOW) + 10:
        return "UNKNOWN"

    frame = bars.with_columns(
        pl.col("close").pct_change().alias("_ret"),
        (pl.col("close") / pl.col("close").rolling_mean(_TREND_WINDOW) - 1).alias("_trend"),
    ).with_columns(pl.col("_ret").rolling_std(_VOL_WINDOW).alias("_vol"))
    frame = frame.drop_nulls(["_ret", "_trend", "_vol"])
    if frame.height < 10:
        return "UNKNOWN"

    vol_series = frame["_vol"]
    trend_series = frame["_trend"]
    latest_vol = vol_series[-1]
    latest_trend = trend_series[-1]

    vol_low, vol_high = vol_series.quantile(1 / 3), vol_series.quantile(2 / 3)
    trend_low, trend_high = trend_series.abs().quantile(1 / 3), trend_series.abs().quantile(2 / 3)
    crisis_cutoff = vol_series.quantile(_CRISIS_VOL_PERCENTILE)

    if latest_vol >= crisis_cutoff and latest_trend < 0:
        return "CRISIS"
    if vol_high is not None and latest_vol >= vol_high:
        return "HIGH_VOL"
    if vol_low is not None and latest_vol <= vol_low:
        return "LOW_VOL"
    if trend_high is not None and abs(latest_trend) >= trend_high:
        return "BULL" if latest_trend > 0 else "BEAR"
    if trend_low is not None and abs(latest_trend) <= trend_low:
        return "RANGING"
    return "TRENDING"


def regime_breakdown(
    equity_curve: list[float], benchmark_curve: list[float] | None = None
) -> RegimeBreakdown | None:
    """Direct pass-through to cpz-quant's regime_conditional_performance
    -- decomposes an equity curve's Sharpe by volatility tercile (and
    bull/bear trend, if a benchmark is supplied). None below its own
    minimum-length floor, same "honestly absent, not fabricated" rule as
    metrics.compute_metrics."""
    return regime_conditional_performance(equity_curve, benchmark_curve)

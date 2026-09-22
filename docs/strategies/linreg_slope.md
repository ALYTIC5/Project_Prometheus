# LINREG_SLOPE

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #14: linear regression slope trend filter. Long when
a rolling ordinary-least-squares linear regression slope of close over
the lookback window is positive.

## Source

No single universally-cited default exists for a rolling
linear-regression slope filter, unlike Wilder's RSI or Kaufman's KAMA --
honest "no citation, standard practitioner construction" posture, same
as N_DAY_LOW/CONSECUTIVE_DOWN/ZSCORE. Polars has no rolling-regression
primitive, so the slope is computed directly via `rolling_map` using the
closed-form OLS slope (cov(x, y) / var(x), x = 0..window-1), the same
"no vectorized primitive exists, compute it directly" stance CCI/Hull/
Aroon already take.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `linreg_lookback` | `20, 50, 100` | The lookbacks most commonly used for linear-regression trend channels in practitioner charting literature, same enumerated-lookback shape TRIX uses. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

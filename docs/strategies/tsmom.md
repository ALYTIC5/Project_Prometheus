# TSMOM

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #8: time-series momentum. Long when the trailing
return from `lookback_days` bars ago to `skip_days` bars ago is
positive. A genuinely different construction from every moving-average
family here -- no MA at all, just the sign of a single trailing return
over a specific, skip-adjusted window.

## Source

Moskowitz, Ooi & Pedersen, "Time Series Momentum" (*Journal of
Financial Economics*, 2012) -- the paper's own canonical construction.
The skip-the-most-recent-month adjustment (avoids short-term reversal
contamination) follows Jegadeesh & Titman's own cited "12-1 month"
convention.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `tsmom_lookback_days`, `tsmom_skip_days` | `(252,21), (126,21), (252,0)` | The paper's own 12-month lookback with a 1-month skip (252/21 trading days), a 6-month variant, and a no-skip variant for comparison. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

# HULL_MA_TREND

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #4: Hull Moving Average trend-following. Long when
today's HMA exceeds the prior bar's HMA. Alan Hull's own construction:
HMA = WMA(2*WMA(close, n/2) - WMA(close, n), round(sqrt(n))) -- a
weighted-moving-average-of-differences designed to track price more
closely (less lag) than a plain, DEMA, or TEMA smoothing.

## Source

Alan Hull (2005), publicly documented on hullalgo.com. Polars has no
built-in weighted-moving-average primitive, so each WMA is computed
directly via `rolling_map` with linearly increasing weights -- the same
"no vectorized primitive exists, compute it directly" stance CCI's
mean-absolute-deviation already takes.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `hull_lookback` | `9, 16, 20` | Alan Hull's own suggested default for daily bars (20), plus his own commonly cited shorter-horizon variants (9, 16). |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

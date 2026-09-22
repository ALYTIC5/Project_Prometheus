# DEMA_CROSSOVER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #3: Double Exponential Moving Average crossover.
Long when a fast DEMA is above a slow DEMA. DEMA = 2*EMA - EMA(EMA),
Patrick Mulloy's own construction ("Smoothing Data with Faster Moving
Averages", *Technical Analysis of Stocks & Commodities*, 1994) --
subtracts out the EMA-of-the-EMA's own lag to track price more closely
than a plain EMA.

## Source

Patrick Mulloy (1994), as above.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `dema_fast_window`, `dema_slow_window` | `(9,21), (12,26), (20,50)` | Same cited pairs EMA_CROSSOVER uses -- the crossover convention is identical, only the underlying moving-average construction differs. |

## Expected horizon

The slow window.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

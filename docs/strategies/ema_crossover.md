# EMA_CROSSOVER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #1: exponential-moving-average crossover. Long when a
fast EMA is above a slow EMA -- exponential weighting reacts faster to
new trends than MOMENTUM's plain SMA crossover, a genuinely distinct
construction (more weight on recent bars), not a rebranded copy.

## Source

Standard technical-analysis convention; no single named academic paper.
9/21, 12/26 (Gerald Appel's own MACD line periods, reused here as a bare
EMA cross), and 20/50 are all commonly cited EMA crossover pairs.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `ema_fast_window`, `ema_slow_window` | `(9,21), (12,26), (20,50)` | Three commonly cited EMA crossover pairs, enumerated (not a cross product) the same way MACD/SAR grids are. |

## Expected horizon

The slow window -- same rule MOMENTUM/MACD use: the slower moving
average IS the horizon claim.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

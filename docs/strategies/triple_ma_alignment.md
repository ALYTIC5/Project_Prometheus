# TRIPLE_MA_ALIGNMENT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #2: three-moving-average alignment. Long only when
three SMAs are in strictly ascending order (fast > mid > slow) -- a
stronger trend-confirmation filter than a single two-line crossover,
since a real trend should show consistent ordering across multiple
horizons, not just one pair agreeing.

## Source

Standard technical-analysis convention (multi-MA "ribbon" alignment);
no single named academic paper.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `tma_fast_window`, `tma_mid_window`, `tma_slow_window` | `(5,20,50), (10,20,50), (10,50,200)` | Three commonly cited triple-MA conventions: short-term, medium-term, and the classic long-term golden-cross triple. |

## Expected horizon

The slow window -- same rule MOMENTUM uses.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

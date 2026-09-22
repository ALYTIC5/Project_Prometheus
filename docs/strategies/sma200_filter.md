# SMA200_FILTER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #19: "simple and robust baseline." Long whenever
close is above its own single rolling SMA, flat otherwise --
deliberately simpler than MOMENTUM's own two-MA crossover (one moving
average, one condition, no second window to overfit).

## Source

Standard technical-analysis convention (the classic 200-day SMA trend
filter); no single named academic paper.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `sma_filter_lookback` | `50, 100, 200` | The classic 200-day SMA trend filter, plus 50/100 as nearby, shorter-horizon variants -- same lookbacks SMA_DISTANCE already uses. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

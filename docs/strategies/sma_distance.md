# SMA_DISTANCE

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #30: "Distance-from-200-SMA reversion." Price that has
stretched unusually far below its own long-run moving average tends to
revert back toward it -- the classic "buy the extreme dip vs. the
long-term trend" construction. The lookback itself is swept (not fixed
to 200) so the grid covers the classic 200-day case plus shorter
distance-from-trend horizons.

## Source

No single named academic source for the general construction; 200-day
SMA distance specifically is a widely-cited practitioner convention
(honest "no citation beyond common practice" per this project's own
pre-registration convention).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `sma_dist_lookback` | `50, 100, 200` | 200 is the classic cited use case; 50/100 are shorter-horizon variants of the same distance-from-trend construction. |
| `sma_dist_oversold` | `0.05, 0.1` | The fraction below the SMA that counts as "unusually far" -- 5%/10%, a plausible-magnitude spread given a 200-day SMA's own typical volatility. |

## Expected horizon

Set to `sma_dist_lookback`.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

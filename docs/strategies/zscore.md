# ZSCORE

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #26: "Rolling z-score of price." A direct statistical
measure of how many standard deviations price has moved from its own
recent mean tends to mean-revert -- the most literal, least-indicator-
laundered version of the mean-reversion hypothesis every oscillator
family here is an indirect proxy for.

## Source

Standard rolling z-score: (close - SMA(close, lookback)) /
rolling_std(close, lookback) -- a textbook statistical construction, no
single named inventor to cite (unlike CCI/RSI/Bollinger, which each
have one).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `zscore_lookback` | `10, 20, 30` | Same lookback grid every other mean-reversion family here uses. |
| `zscore_oversold` | `-1.5, -2.0, -2.5` | Standard statistical "unusual move" thresholds (1.5-2.5 std below the mean) -- not a single named source's convention, but the same magnitude range CCI's own -100 zone and Bollinger's own 2-std bands already imply. |

## Expected horizon

Set to `zscore_lookback`.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

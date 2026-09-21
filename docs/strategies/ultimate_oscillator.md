# ULTIMATE_OSCILLATOR

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #31. A single-timeframe oscillator (like RSI or
Stochastic) can give false signals from noise specific to that
timeframe; averaging buying-pressure-over-true-range across three
timeframes (short/mid/long) filters that noise while staying responsive
via the heavier weight on the short timeframe.

## Source

Larry Williams' own published Ultimate Oscillator (1976): buying
pressure (close - min(low, prior_close)) over true range
(max(high, prior_close) - min(low, prior_close)), summed across three
timeframes and combined 4:2:1 short:mid:long -- his own published
weighting, not invented.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `uo_short`, `uo_mid`, `uo_long` | fixed `7, 14, 28` | Williams' own published convention -- not swept, since the 4:2:1 weighting is defined relative to this exact triple, not an arbitrary set of three windows. |
| `uo_oversold` | `30.0, 20.0` | Williams' own published <30 reversal zone, plus a more extreme 20 variant. |

## Expected horizon

Set to `uo_mid` (14) -- the middle of the three timeframes this
oscillator itself weights most heavily after the short one.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

# NR7_BREAKOUT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #41: NR7 (Narrowest Range of 7). The narrowest true
range of the last `nr7_lookback` bars signals imminent expansion. Long
the bar AFTER an NR7 bar if close breaks above that bar's own high.

## Source

Toby Crabel, *Day Trading with Short Term Price Patterns and Opening
Range Breakout* (1990) -- the NR7 construction's own original
publication.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `nr7_lookback` | `5, 7, 10` | Crabel's own fixed 7-bar window (Narrowest Range of 7 by definition), plus a shorter and a longer variant of the same "narrowest range of N" construction. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

# SQUEEZE_BREAKOUT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #39: Bollinger squeeze breakout. squeeze_on when
Bollinger Bands (2.0 std) sit entirely inside Keltner Channels (1.5x
ATR), both computed over the same shared lookback. Long the bar the
squeeze RELEASES (was on, now off) with close breaking above the shared
basis.

## Source

John Carter's own "TTM Squeeze" (*Mastering the Trade*, 2005) --
Carter's own canonical multipliers (2.0 for Bollinger, 1.5 for Keltner)
are fixed rather than swept, since only the shared lookback varies in
his own convention.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `squeeze_lookback` | `10, 20, 30` | Carter's own canonical 20-bar lookback for both bands, plus a shorter and a longer variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

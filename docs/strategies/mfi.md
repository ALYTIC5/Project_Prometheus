# MFI (Money Flow Index)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #32: "Uses volume." A volume-weighted version of RSI
-- oversold readings backed by heavy selling VOLUME (not just price
direction) are a stronger capitulation signal than a price-only
oscillator, since low-volume declines are more likely noise.

## Source

Money Flow Index: typical price (high+low+close)/3 times volume is raw
money flow, split into "positive" (typical price rose day-over-day) and
"negative" (fell) money flow, then the same RSI-style
100 - 100/(1+ratio) scaling applied to the ratio of positive-to-negative
sums -- a standard, widely-cited construction (a volume-weighted RSI).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `mfi_lookback` | `14, 21` | 14 is MFI's own standard cited period (matching Wilder's own RSI default); 21 is a nearby longer variant. |
| `mfi_oversold` | `20.0, 30.0` | Standard cited MFI oversold zones (the same magnitude range RSI's own 20-30 zone uses). |

## Expected horizon

Set to `mfi_lookback`.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close/volume -- already available (this is the only new
family in this batch that reads volume).

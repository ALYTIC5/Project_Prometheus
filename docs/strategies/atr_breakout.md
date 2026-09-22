# ATR_BREAKOUT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #40: ATR breakout. Long when close breaks above the
PRIOR close plus `atr_breakout_multiplier` ATRs -- a volatility-scaled
breakout distinct from the existing VOL_BREAKOUT family's own fixed
Donchian-channel construction (a rolling N-bar high); this breaks out of
a volatility-scaled band anchored on the prior close instead.

## Source

Standard practitioner construction (ATR-scaled breakout bands); no
single canonical paper. The lookback uses Wilder's own default ATR
period (14).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `atr_breakout_lookback` | `14` | Wilder's own default ATR period. |
| `atr_breakout_multiplier` | `1.0, 1.5, 2.0` | A modest-to-aggressive breakout range. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

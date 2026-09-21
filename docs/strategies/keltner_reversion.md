# KELTNER_REVERSION

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

The inverse of the existing KELTNER (breakout) family, per
`docs/strategies/STRATEGIES_100.md` #33 ("inverse of 17"). A price
extension far below its own ATR-normalized volatility band is
statistically unusual and tends to mean-revert, the same logic every
other band/oscillator mean-reversion family in this project already
relies on (Bollinger, CCI), applied to Keltner's own EMA+ATR band
construction instead of a rolling-std band.

## Source

Chester Keltner's original channel construction, with Linda Bradford
Raschke's later ATR-based band width (the variant in standard use
today) -- the same construction `FAMILY_KELTNER` already cites, used
here in the opposite (reversion) direction instead of breakout.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `keltner_rev_lookback` | `10, 20, 30` | Same grid `FAMILY_KELTNER`'s own breakout version already uses -- both are the identical ATR-band construction. |
| `keltner_rev_multiplier` | `1.5, 2.0, 2.5` | Same grid `FAMILY_KELTNER` already uses. |

## Expected horizon

Set to `keltner_rev_lookback` -- a mean-reversion signal's own lookback
is its horizon claim, the same convention every other mean-reversion
family here uses (BOLLINGER, RSI, CCI).

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV (needs high/low/close for true range) -- already available in
this project's existing ccxt crypto ingestion and Alpaca ETF ingestion.

# BOLLINGER_PCTB

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #34: "Variant of your existing BOLLINGER." %B gives a
continuous 0-1 (typically) reading of where price sits within the bands,
rather than the existing `FAMILY_BOLLINGER`'s binary "closed below the
lower band" touch -- letting the grid sweep how far into/past the band
counts as oversold (0.0 = at the band, 0.2 = near it), a genuinely
different parameter surface than a single fixed touch.

## Source

John Bollinger's own %B construction: %B = (close - lower_band) /
(upper_band - lower_band). Same band construction (mean ± multiplier *
rolling std) `FAMILY_BOLLINGER` already cites.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `pctb_lookback` | `10, 20, 30` | Same grid `FAMILY_BOLLINGER` uses. |
| `pctb_multiplier` | `1.5, 2.0, 2.5` | Same grid `FAMILY_BOLLINGER` uses. |
| `pctb_oversold` | `0.2, 0.0` | Bollinger's own commonly cited "near/at the lower band" zones -- 0.0 is a legitimate value (price exactly at the lower band), not excluded. |

## Expected horizon

Set to `pctb_lookback`, same convention as BOLLINGER/RSI/CCI.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

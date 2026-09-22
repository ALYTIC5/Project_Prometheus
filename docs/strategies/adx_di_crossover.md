# ADX_DI_CROSSOVER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #10: ADX/DI crossover trend filter. Long when +DI is
above -DI AND ADX exceeds 25 -- Wilder's own published threshold for "a
real trend is present," so this is a genuinely distinct construction
from a bare, unfiltered DI crossover.

## Source

J. Welles Wilder, *New Concepts in Technical Trading Systems* (1978) --
the ADX/DMI system's own original publication. +DM/-DM are the
positive/negative parts of consecutive high/low moves, Wilder-smoothed
(the same alpha=1/lookback recursive EMA the existing RSI signal already
uses for average gain/loss) into +DI/-DI, with ADX the Wilder-smoothed
average of the DI spread's own absolute percentage.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `adx_lookback` | `10, 14, 20` | Wilder's own default (14), plus a shorter and a longer still-standard variant, same grid shape RSI/CCI use. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

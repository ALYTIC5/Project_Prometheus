# VORTEX

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #13: Vortex Indicator crossover. Long when +VI
crosses above -VI. +VM = abs(high - prior_low), -VM = abs(low -
prior_high), each summed over the lookback window and divided by summed
true range.

## Source

Etienne Botes & Douglas Siepman, "The Vortex Indicator" (*Technical
Analysis of Stocks & Commodities*, 2010) -- the indicator's own
original publication.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `vortex_lookback` | `10, 14, 21` | Botes & Siepman's own default (14), plus a shorter and a longer variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

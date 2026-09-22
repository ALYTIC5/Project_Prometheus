# MA_RIBBON

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #20: moving-average ribbon. Long when the ribbon is
both correctly ALIGNED (short > mid > long -- an uptrend) AND EXPANDING
(today's short-to-long spread wider than the prior bar's) -- a
trend-STRENGTH confirmation on top of TRIPLE_MA_ALIGNMENT's own pure
trend-DIRECTION signal; alignment alone can persist while the ribbon
itself compresses toward a reversal, which this family is built to
exclude.

## Source

Standard technical-analysis convention ("ribbon" trading); no single
named academic paper.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `ribbon_short`, `ribbon_mid`, `ribbon_long` | `(5,10,20), (10,20,50), (20,50,100)` | Common "moving average ribbon" triples cited in practitioner literature: short-term, medium-term, and long-term ribbons. |

## Expected horizon

The long window.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

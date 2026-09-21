# IBS (Internal Bar Strength)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #27: "Close position in day's range." A close near
the bottom of its own day's range (low IBS) tends to bounce the next
bar -- a genuinely single-bar mean-reversion signal, distinct from
every lookback-window family here since it needs no rolling history at
all.

## Source

Internal Bar Strength, a cited construction in short-horizon equity/ETF
mean-reversion literature (e.g. Bandy's own trading-systems writing):
IBS = (close - low) / (high - low).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `ibs_oversold` | `0.2, 0.1` | Commonly cited "near the day's low" thresholds in the IBS literature. |

No `lookback` field -- IBS is a per-bar ratio by its own construction,
not a rolling-window indicator.

## Expected horizon

Fixed at 1 -- IBS's own claim is next-bar, the shortest meaningful
horizon this project's families make.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

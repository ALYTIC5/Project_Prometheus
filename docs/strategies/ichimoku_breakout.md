# ICHIMOKU_BREAKOUT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #12: Ichimoku cloud breakout. Long when close breaks
above the cloud (the higher of leading span A/B). Conversion/base lines
are the midpoint of the highest-high/lowest-low over their own windows;
leading spans are projected `base` periods ahead of the data that
produced them on a real Ichimoku chart.

## Source

Goichi Hosoda, publicly documented in *Ichimoku Kinko Hyo* (Japan,
1968/1969 publication). Law-1 safety note: for a live signal (not a
chart), "projected ahead" is equivalent to comparing today's close
against the span A/B values computed `base` bars ago -- `.shift(base)`
brings the historically-correct cloud value forward to today's row.
This only ever looks BACKWARD for the comparison value, never forward.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `ichimoku_conversion`, `ichimoku_base`, `ichimoku_span_b` | `(9,26,52), (7,22,44)` | Hosoda's own original default (based on a 6-day trading week), plus the commonly cited 7/22/44 adjustment for a 5-day week -- both Hosoda-derived. |

## Expected horizon

The base window.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

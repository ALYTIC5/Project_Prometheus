# INSIDE_BAR_BREAKOUT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #42: inside-bar breakout. An inside bar (today's high
< prior high AND today's low > prior low) signals compression. Long the
bar AFTER an inside bar if close breaks above that inside bar's own
high by more than `inside_bar_buffer`.

## Source

Standard price-action pattern; no single canonical paper. The
confirmation buffer is a common practitioner tweak to reduce false
breakouts (same honest "no citation, standard practitioner
construction" posture as N_DAY_LOW/CONSECUTIVE_DOWN/ZSCORE).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `inside_bar_buffer` | `0.0, 0.001, 0.002` | No lookback parameter exists for a single-bar pattern; the confirmation buffer (exact breakout, then two small buffers) is the grid dimension instead. |

## Expected horizon

Fixed at 1 -- a single-bar pattern's own claim is the shortest
meaningful horizon this project's families make.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

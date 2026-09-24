# FIFTY_TWO_WEEK_HIGH

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #60: 52-week-high proximity. Rank assets by proximity
to their own trailing `lookback_days`-bar high (close / rolling_high,
closer to 1.0 = closer to the high), long the top `top_n`. A momentum
signal via ANCHORING to a salient reference price rather than raw
trailing return.

## Source

Thomas J. George & Chuan-Yang Hwang, "The 52-Week High and Momentum
Investing" (*Journal of Finance*, 2004) -- the paper's own stated
distinct mechanism from ordinary trailing-return momentum.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `lookback_days` | `252` | George & Hwang's own canonical 52-week window, fixed by the construction's own name. |
| `top_n` | `3, 5` | A concentrated and a broader variant, same shape SECTOR_MOMENTUM uses. |

## Universe

The same 11-sector universe SECTOR_MOMENTUM uses.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

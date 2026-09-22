# KAMA_TREND

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #5: Kaufman Adaptive Moving Average trend-following.
Long when today's KAMA exceeds the prior bar's KAMA. The smoothing
constant adapts every bar between fast- and slow-period responsiveness,
based on a trailing efficiency ratio (net directional move over the
lookback, divided by the sum of bar-to-bar absolute moves -- 1.0 in a
pure trend, near 0 in pure chop).

## Source

Perry Kaufman, *Smarter Trading* (1995), the KAMA construction's own
original publication. Genuinely sequential -- KAMA_i depends on
KAMA_{i-1} and that bar's own adaptive smoothing constant, neither
expressible as a pure column expression -- computed via a real Python
loop over numpy arrays, the same treatment `_parabolic_sar_signal`
already uses.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `kama_lookback`, `kama_fast_sc`, `kama_slow_sc` | `(10,2,30), (20,2,30), (10,2,60)` | Kaufman's own published defaults (10, 2, 30), plus a longer-lookback variant and a more conservative slow-SC variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

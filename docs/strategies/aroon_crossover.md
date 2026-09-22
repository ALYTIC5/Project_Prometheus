# AROON_CROSSOVER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #11: Aroon crossover trend filter. Long when Aroon-Up
crosses above Aroon-Down. Aroon-Up = 100 * (lookback -
bars_since_highest_high) / lookback, Aroon-Down analogous for the
lowest low.

## Source

Tushar Chande, "The New Technical Trader" (1994) -- the Aroon
indicator's own original publication. Polars has no rolling-argmax
primitive, so "bars since the window's extreme" is computed directly
via `rolling_map`, the same "no vectorized primitive exists" stance
CCI/Hull already take.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `aroon_lookback` | `14, 25, 50` | Chande's own default (25), plus a shorter and a longer variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low -- already available.

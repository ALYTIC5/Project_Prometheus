# CONSECUTIVE_DOWN

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #29: "Consecutive down-days." A run of consecutive
down-closes is a run-length-based overselling signal, distinct from
N_DAY_LOW (which triggers on absolute price level, not on the shape of
the recent path getting there).

## Source

No single named academic source -- a widely-used, generic technical
construction (same honest posture as N_DAY_LOW/ZSCORE).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `consecutive_down_days` | `2, 3, 4` | A short run-length spread -- longer runs are progressively rarer events by construction, so the grid stays in the range where enough historical occurrences exist to backtest meaningfully. |

## Expected horizon

Set to `consecutive_down_days` -- the run length itself is this
signal's own horizon claim (how many days of continuation it takes to
call the pattern, roughly how many days of reversion it expects back).

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

# GAP_FADE

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #35: "Gap-fade (open vs prior close)." A large
overnight down-gap often reflects an overreaction to news that
partially reverses during the following session -- fading the gap
(going long into it) captures that reversion. Uses only the bar's own
open against the PRIOR bar's close (never today's own close), so the
raw condition is genuinely known at today's open, not a look-ahead
dressed up as one.

## Source

No single named academic source -- a widely-used, generic technical
construction in short-horizon mean-reversion trading literature (honest
"no citation, standard practitioner construction," same posture as
N_DAY_LOW/CONSECUTIVE_DOWN/ZSCORE).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `gap_fade_threshold` | `0.01, 0.02, 0.03` | A 1%/2%/3% down-gap spread -- small enough to fire on real crypto/ETF daily gaps, large enough to exclude routine overnight noise. |

## Expected horizon

Fixed at 1 -- a gap-fade's own claim is intraday-to-next-close, the
shortest meaningful horizon this project's families make.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV open and close -- already available. This is the only new family
in this batch that reads the bar's own `open` (every other family here
reads only close/high/low/volume).

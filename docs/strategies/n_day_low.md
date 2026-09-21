# N_DAY_LOW

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #28: "N-day low reversal." A fresh N-day low often
marks short-term capitulation/overselling that mean-reverts -- the
classic "buy the dip at a new low" construction, distinct from
CONSECUTIVE_DOWN (a run-length count) since this triggers on the
PRICE LEVEL itself, not on how many days in a row it fell.

## Source

No single named academic source -- a widely-used, generic technical
construction in short-horizon mean-reversion trading literature (an
honest "no citation, standard practitioner construction" per this
project's own pre-registration convention, same posture as ZSCORE).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `ndaylow_lookback` | `10, 20, 50` | A short/medium/longer-horizon spread of "N-day" windows, matching this project's own convention of 3 grid points per swept parameter. |

## Expected horizon

Set to `ndaylow_lookback`.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

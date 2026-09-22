# VOL_OF_VOL_FILTER

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #45: vol-of-vol filter. Structurally similar to
VOL_REGIME_SWITCH but filters on the volatility OF realized volatility
(a rolling std of the realized-vol series itself over `vov_window`)
rather than the vol LEVEL -- a distinct empirical bet: vol-of-vol spikes
often precede whipsaws even when the vol level itself looks calm. Long
when the trailing return over `vov_lookback` is positive AND today's
vol-of-vol is at or below its own rolling median over `vov_window`.

## Source

No single canonical paper -- a practitioner filter used in systematic
vol-managed strategies (same "no citation, standard practitioner
construction" posture as VOL_REGIME_SWITCH/N_DAY_LOW/ZSCORE).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `vov_vol_window`, `vov_window`, `vov_lookback` | `(20,40,20), (20,60,20)` | Same posture as VOL_REGIME_SWITCH -- no canonical defaults; a 20-bar realized-vol window feeding a 40-bar vol-of-vol window, plus a longer-vol-of-vol-window variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

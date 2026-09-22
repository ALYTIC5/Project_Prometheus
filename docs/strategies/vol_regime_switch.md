# VOL_REGIME_SWITCH

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #43: realised-volatility regime switch. Realized
volatility (rolling std of returns over `vre_vol_window`) is compared
against its own rolling median over `vre_regime_window`: in the LOW
regime, long when the trailing return over `vre_lookback` is positive
(trend-following); in the HIGH regime, long when close is below its own
SMA over `vre_lookback` (mean-reversion). A genuine regime SWITCH, not
just a trend filter -- the two regimes use opposite trading logic.

## Source

A practitioner regime-switching heuristic, informed by the general
finding that trend-following tends to underperform in high-volatility/
choppy regimes while mean-reversion tends to dominate then. No single
canonical paper cites this exact construction -- honest "no citation,
standard practitioner heuristic" posture, same as N_DAY_LOW/
CONSECUTIVE_DOWN/ZSCORE.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `vre_vol_window`, `vre_regime_window`, `vre_lookback` | `(20,100,20), (20,200,20)` | No canonical defaults exist; a 20-bar realized-vol window (a common short window) against a 100-bar regime median (a common "recent history" window), plus a longer-regime variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close -- already available.

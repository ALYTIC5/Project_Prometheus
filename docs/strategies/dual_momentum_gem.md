# DUAL_MOMENTUM_GEM (ROTATION_FAMILY_DUAL_MOMENTUM_GEM)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

Combines absolute momentum (is the asset's own trailing return positive?)
with relative momentum (is US or non-US equity stronger?) to time between
equities and bonds — capturing the momentum premium while avoiding
sustained equity drawdowns by rotating into a defensive asset whenever
neither equity leg has positive trailing momentum of its own.

## Source

Antonacci, *Dual Momentum Investing* (2014). GEM's own published rule
set — not this project's invention.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | `("SPY", "EFA", "TLT")` | Antonacci's own published proxies (US equity, non-US developed equity, long treasuries as the defensive asset). `EFA` and `TLT` are both already in `config/universe_etf.yaml` with real listing dates. |
| `lookback_days` | `252` | GEM's own published 12-month lookback — fixed, not a grid, because it is the strategy's own definition per the source. |
| `rebalance_frequency_days` | `21` | GEM's own published monthly check. |
| `top_n` | none | GEM's rule is binary selection (hold 100% of whichever one of SPY/EFA has the higher trailing return, if positive; else 100% TLT), not a ranked top-N. |

**Universe-order convention (implicit contract):** `spec.universe` for
this family is always `(equity_leg_1, equity_leg_2, ..., defensive_leg)`
— the **last** tuple position is always the defensive asset (`TLT` for
the canonical `("SPY", "EFA", "TLT")` universe). Every symbol before the
last position is an equity leg scored on its own trailing return; the
last position is never scored against the equity legs, only used as the
fallback when no equity leg has positive trailing momentum. This
convention is depended on by both `weights_for_dual_momentum_gem`
(`prometheus/backtest/portfolio_engine.py`) and the deterministic grid
generator (Task 7) — any future GEM-family universe must preserve
"defensive leg is the last tuple element" or both will silently
misidentify which asset is the fallback.

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) — matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

Equal-weight of `{SPY, EFA, TLT}` (Law 8's own words — "equal-weight for
multi-asset" — applied to GEM's specific 3-asset universe, not the
11-sector universe the other families in this batch use, since GEM's is
a genuinely different universe).

## Data requirements

Daily OHLCV for `SPY`, `EFA`, `TLT`, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias). Alpaca ETF ingestion already covers this universe;
no new data infrastructure is needed.

## Implementation note: defensive-leg identification under eligibility filtering

`_eligible_symbols` reconstructs point-in-time membership and preserves
`spec.universe`'s ordering, but it can *drop* a universe member entirely
if that symbol fails its own listing/delisting check on the decision
date. Since the defensive leg is `spec.universe[-1]`, dropping it would
leave `eligible[-1]` pointing at whatever equity leg remains — silently
wrong. `_weights_for`'s dispatch for this family guards against this by
checking `spec.universe[-1] in eligible` explicitly *before* calling
`weights_for_dual_momentum_gem`, returning `{}` (an honestly-skipped
rebalance) if the defensive leg itself is not eligible on `as_of`. Once
that check passes, universe-order preservation guarantees the defensive
leg is also the last element of `eligible` (nothing follows it in
`spec.universe`), so `weights_for_dual_momentum_gem`'s own
`*equity_legs, defensive_leg = eligible` unpacking is safe.

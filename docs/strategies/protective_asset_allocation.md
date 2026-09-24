# PROTECTIVE_ASSET_ALLOCATION (PAA)

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #55: Protective Asset Allocation. Each offensive
asset's momentum score is its close's distance from its own
`lookback_days`-bar SMA. `n` of the N scorable offensive assets with a
positive score determines the bond fraction:
`min(1, (N-n)*protection_factor/N)`. The remaining equity fraction is
split equally among the top `top_n` positive-score assets.

## Source

Wouter Keller & Jan Willem Keuning, "Protective Asset Allocation (PAA):
A Simple Momentum-Based Alternative for Term Deposits" (2017).
`protection_factor` is the paper's own explicitly-varied "a" parameter
(the paper itself sweeps a=0..2), so sweeping it here is not an
invented threshold. `lookback_days=210` (10 months) is Faber/Keller's
own shared SMA-timing convention.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `top_n` | `1, 6` | A concentrated and a broad variant. |
| `protection_factor` | `0.5, 1.0, 2.0` | The paper's own explicitly-varied "a" range. |
| `lookback_days` | `210` | Faber/Keller's own shared 10-month SMA convention. |

## Universe

`(SPY, QQQ, IWM, EFA, EEM, VNQ, GLD, HYG, IEF)` -- 8-asset offensive
pool, IEF as the bond/defensive proxy.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

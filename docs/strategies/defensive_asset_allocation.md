# DEFENSIVE_ASSET_ALLOCATION (DAA)

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #54: Defensive Asset Allocation. A "canary" pair of
assets judges the market regime: T of the 2 canary assets showing a
negative 13612W momentum score sends T/(scored canary count) of the
portfolio to a defensive leg; the remainder is split equally among the
top `top_n` (breadth) positive-momentum offensive assets.

## Source

Wouter Keller & Jan Willem Keuning, "Breadth Momentum and the Canary
Universe: Defensive Asset Allocation (DAA)" (2016). A **documented
simplification** of the published construction: `universe` = (canary_1,
canary_2, offensive_1, ..., offensive_N, defensive) uses a SINGLE
defensive leg (IEF) rather than the paper's own 3-asset protective pool
(SHY/IEF/UST) -- this project's ingested universe
(`config/universe_etf.yaml`) has no ultra-short-duration Treasury ETF
equivalent to SHY. EEM (emerging-market equities) + IEF (intermediate
treasuries) substitute for the paper's own VWO+BND canary pair, the
closest available pair. The 13612W momentum score itself (weighted
average of 1/3/6/12-month returns, weights 12/4/2/1) is the paper's own
exact construction, not simplified.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `top_n` (breadth) | `1, 2, 6` | Keller & Keuning's own published G1/G2/G6 breadth variants. |

## Universe

`(EEM, IEF, SPY, QQQ, IWM, EFA, VNQ, GLD, TLT, HYG, LQD, IEF)` -- canary
(EEM, IEF), 9-asset offensive pool, IEF as defensive.

## Expected horizon

Monthly (21 trading days) -- this project's own rebalance-cadence
convention, matching the paper's own monthly cadence.

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

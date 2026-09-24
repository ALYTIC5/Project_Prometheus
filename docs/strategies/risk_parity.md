# RISK_PARITY_INVERSE_VOL

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #57: risk parity. Weight inversely proportional to
each asset's own rolling volatility (daily-return std over
`lookback_days`), so no single volatile asset can dominate the
portfolio's own risk contribution.

## Source

A documented SIMPLIFICATION of full covariance-based risk parity (Edward
Qian, "Risk Parity Portfolios", PanAgora, 2005). The naive
("inverse-volatility") form implemented here is the standard
practitioner shorthand for it and ignores cross-asset correlation
entirely -- distinct from MINIMUM_VARIANCE, which does use the full
covariance matrix.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `lookback_days` | `63, 126` | A quarterly and a semi-annual volatility-estimation window. |

## Universe

The same 11-sector universe SECTOR_MOMENTUM uses.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

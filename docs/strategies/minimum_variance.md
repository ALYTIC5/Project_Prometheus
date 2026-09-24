# MINIMUM_VARIANCE

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #58: minimum variance. The unconstrained analytic
solution `w = (Sigma^-1 * 1) / (1^T * Sigma^-1 * 1)` using the sample
covariance matrix of daily returns over `lookback_days`.

## Source

Classic mean-variance portfolio theory (Markowitz). A documented
SIMPLIFICATION of the true long-only-constrained quadratic program
(which has no closed form and would need an iterative solver -- a new
dependency this project's cost-discipline rule would require
justifying): the unconstrained solution can assign negative weights,
which are clipped to zero and the remainder renormalized, a standard
practitioner approximation to the constrained optimum. Falls back to
RISK_PARITY_INVERSE_VOL (documented, not silent) whenever fewer than 2
symbols have aligned history or the covariance matrix is singular.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `lookback_days` | `63, 126` | Same window choices as RISK_PARITY_INVERSE_VOL. |

## Universe

`(SPY, EFA, IEF, VNQ, GLD)` -- the same 5-asset universe GTAA_SMA uses,
kept small so the covariance matrix stays well-conditioned relative to
the estimation window.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

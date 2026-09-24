# RESIDUAL_MOMENTUM

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #62: residual momentum (beta-adjusted). Rank assets by
their CUMULATIVE RESIDUAL return over `lookback_days` -- the daily
return left over after subtracting away each asset's own
market-beta-scaled share of the benchmark's daily return -- rather than
raw momentum, isolating the idiosyncratic component.

## Source

David Blitz, Joop Huij & Martin Martens, "Residual Momentum" (*Journal
of Empirical Finance*, 2011) -- the paper's own finding that the
idiosyncratic component is the more persistent momentum signal, net of
market beta. Beta is estimated via the same closed-form OLS slope
(`cov(asset, benchmark) / var(benchmark)`) the LINREG_SLOPE classic
family already uses, "approximate with SPY beta" per STRATEGIES_100.md's
own note for #62.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `lookback_days` | `63, 126, 252` | Quarterly, semi-annual, and annual estimation windows, same shape SECTOR_MOMENTUM uses. |
| `top_n` | `3` | A concentrated top-3, matching RELATIVE_STRENGTH_TOP3's own convention. |

## Universe

`(SPY, XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC)` --
`universe[0]` is always the market-benchmark symbol (never itself
held); the 11 sector SPDRs are the ranked pool.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the ranked pool (excludes the benchmark
leg itself).

## Data requirements

OHLCV close, all symbols already ingested.

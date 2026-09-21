# RELATIVE_STRENGTH_TOP3 (ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

Same cross-sectional momentum mechanism as #49 (`SECTOR_MOMENTUM_ROTATION`),
specifically at the top-3 concentration named in the STRATEGIES_100
doc — a narrower, higher-conviction version of #49.

## Source

Jegadeesh & Titman (1993), same as #49.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) | the batch's shared sector universe |
| `lookback_days` | `{63, 126, 252}` | same literature-standard momentum horizons as #49 |
| `top_n` | `3` (fixed) | it is the strategy's own definition, not a swept parameter |
| `rebalance_frequency_days` | `21` (monthly) | the batch's shared monthly-rebalance convention |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) — matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

#59's (`EQUAL_WEIGHT_BASELINE`) equal-weight sector universe buy-and-hold.

## Clustering note

Pre-registered expectation, stated honestly before any backtest runs —
#51 is very likely to cluster with #49 at `top_n=3`, since they're the
same ranking mechanism at one shared parameter value. That is the
correlation-clustering machinery working correctly, not a bug, per
`docs/strategies/STRATEGIES_100.md`'s own framing ("a cluster counts as
ONE discovery").

## Data requirements

Daily OHLCV for the 11 SPDR sector ETFs, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias). Alpaca ETF ingestion already covers this universe;
no new data infrastructure is needed.

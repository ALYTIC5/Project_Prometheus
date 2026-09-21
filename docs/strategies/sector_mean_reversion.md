# SECTOR_MEAN_REVERSION (ROTATION_FAMILY_SECTOR_MEAN_REVERSION)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

The STRATEGIES_100 doc's own framing — "inverse of #49
(`SECTOR_MOMENTUM_ROTATION`)." Short-to-medium-horizon reversal: sectors
that most underperformed over the trailing lookback are bought, on the
hypothesis that cross-sectional momentum decays into reversal at
shorter horizons (De Bondt & Thaler's overreaction finding, applied
cross-sectionally at the sector level).

## Source

De Bondt & Thaler (1985).

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) | the batch's shared sector universe |
| `lookback_days` | `{21, 63}` | De Bondt & Thaler's own reversal effect is shorter-horizon than momentum's continuation effect — different grid range from #49/#51 for exactly that reason, not arbitrarily |
| `top_n` | `{3, 5}` | buys the worst N, not the best — same breadth grid as #49, sort direction flipped |
| `rebalance_frequency_days` | `21` (monthly) | the batch's shared monthly-rebalance convention |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) — matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

#59's (`EQUAL_WEIGHT_BASELINE`) equal-weight sector universe buy-and-hold.

## Implementation note

Implemented as `weights_for_top_n_momentum(..., worst=True)` — the same
ranking primitive #49 and #51 call, with the sort direction flipped, per
this family's own "inverse of #49" framing, not a separate ranking
algorithm.

## Data requirements

Daily OHLCV for the 11 SPDR sector ETFs, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias). Alpaca ETF ingestion already covers this universe;
no new data infrastructure is needed.

# SECTOR_MOMENTUM_ROTATION (ROTATION_FAMILY_SECTOR_MOMENTUM)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

Cross-sectional momentum — sectors that outperformed over the trailing
lookback tend to keep outperforming over the next period (Jegadeesh &
Titman's original single-asset finding, applied cross-sectionally to
sectors rather than to individual stocks).

## Source

Jegadeesh & Titman (1993); sector-level application is the "honest
ETF-universe" version of the sector-rotation idea named in the
STRATEGIES_100 doc.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) | the batch's shared sector universe |
| `lookback_days` | `{63, 126, 252}` | 3/6/12 trading months — the standard momentum lookback horizons in the literature, not invented |
| `top_n` | `{3, 5}` | breadth of the rotating basket held each rebalance |
| `rebalance_frequency_days` | `21` (monthly) | the batch's shared monthly-rebalance convention |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) — matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

#59's (`EQUAL_WEIGHT_BASELINE`) equal-weight sector universe buy-and-hold.

## Data requirements

Daily OHLCV for the 11 SPDR sector ETFs, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias). Alpaca ETF ingestion already covers this universe;
no new data infrastructure is needed.

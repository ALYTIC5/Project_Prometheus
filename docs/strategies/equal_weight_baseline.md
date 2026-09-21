# EQUAL_WEIGHT_BASELINE (ROTATION_FAMILY_EQUAL_WEIGHT)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

Not an edge claim — this is the baseline every other rotation strategy
in this batch must beat, per the STRATEGIES_100 doc's own instruction
("Include #59 equal-weight as the baseline every rotation strategy must
beat").

## Source

n/a — construction, not a cited effect.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) | the batch's shared sector universe, so #59 is a valid benchmark for every other family in this batch |
| `rebalance_frequency_days` | `21` (monthly) | the batch's shared monthly-rebalance convention |
| `lookback_days` | none | every constituent gets `1/N` always — no ranking, no history needed |
| `top_n` | none | not a ranking family — the whole eligible universe is held every rebalance |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) — matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

This family's own Law 8 buy-and-hold is the same universe's equal-weight
buy-and-hold — this family and its own Law 8 benchmark are the same
portfolio without periodic rebalancing back to equal weight, so the
"edge" this family tests for is specifically the rebalancing effect
(selling winners / buying losers back to 1/N on each rebalance date),
not stock/sector selection.

## Data requirements

Daily OHLCV for the 11 SPDR sector ETFs, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias — a delisted/replaced sector ETF must drop out of
eligibility as of its own delisting date, not silently persist).
Alpaca ETF ingestion already covers this universe; no new data
infrastructure is needed.

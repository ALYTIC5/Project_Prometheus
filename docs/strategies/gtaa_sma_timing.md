# GTAA_SMA_TIMING (ROTATION_FAMILY_GTAA_SMA)

**Registered:** 2026-09-21, before any backtest of this family has run.

## Hypothesis

A simple trend filter (price above/below its own trailing simple moving
average) reduces drawdowns versus buy-and-hold with little cost to
return, applied per-asset across a multi-asset universe. Each asset's
in/out decision is fully independent of every other asset's -- this is
a per-asset timing filter, not a cross-sectional ranking.

## Source

Faber, "A Quantitative Approach to Tactical Asset Allocation" (2007) --
the paper's own published 10-month SMA rule.

## Parameters

| Field (RotationSpec) | Grid values | Rationale |
|---|---|---|
| `universe` | `("SPY", "EFA", "IEF", "VNQ", "GLD")` | Faber's own published 5-asset GTAA universe (US equity, foreign equity, bonds, REITs, gold). All 5 already exist in `config/universe_etf.yaml`. |
| `lookback_days` | `210` | Faber's own published 10-month x 21 trading days -- fixed, per-source, not swept. |
| `rebalance_frequency_days` | `21` | Faber's own published monthly rule. |
| `top_n` | none | not a ranking family -- each of the 5 assets is independently in (above its own SMA) or out (below it, into cash), never ranked against each other. |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

21 (one rebalance cycle) -- matches `RotationSpec.expected_horizon`'s
own "real input to decay testing, not decoration" requirement.

## Benchmark

Equal-weight of `{SPY, EFA, IEF, VNQ, GLD}` (Law 8's own words --
"equal-weight for multi-asset" -- applied to GTAA's specific 5-asset
universe, not the 11-sector universe the other families in this batch
use, since GTAA's is a genuinely different universe).

## Data requirements

Daily OHLCV for `SPY`, `EFA`, `IEF`, `VNQ`, `GLD`, point-in-time via
`PointInTimeFrame`/`prometheus/data/schema.py`, and universe membership
windows (`listed_at`/`delisted_at`) via
`prometheus/data/universe.py::membership_windows()` for Law 2 (no
survivorship bias). Alpaca ETF ingestion already covers this universe;
no new data infrastructure is needed.

## Implementation note: no redistribution of an "out" asset's slice

`weights_for_gtaa_sma` gives each of `len(eligible)` assets a FIXED
`1/N` slice of capital, independent of how many other assets are
currently "in." An asset whose close is at or below its own trailing
`lookback_days`-bar SMA simply has its slice omitted from the returned
weights (that capital sits in cash) -- it is never redistributed to the
assets still "in," unlike `weights_for_top_n_momentum` or
`weights_for_equal_weight`, which always divide 100% of capital among
whatever survives a rebalance. This means the sum of GTAA's returned
weights can be less than 1.0 (partial cash position), which is the
correct, intended behavior per Faber's own published mechanics, not a
bug -- `sum(weights.values()) <= 1.0` always, and equals `1.0` only
when every eligible asset is above its own SMA simultaneously.

Each symbol's SMA is computed from that symbol's own bars only (no
cross-asset comparison, unlike GEM's ranking of equity legs against
each other), so there is no cross-contamination between symbols'
in/out decisions. A symbol with fewer than `lookback_days` available
bars as of the decision date is skipped entirely (its slice sits in
cash) rather than judged on a partial window -- an honestly-unjudged
asset, not a fabricated in/out call, the same convention
`trailing_return` uses for insufficient history. An all-out rebalance
correctly returns `{}` (100% cash), and an empty `eligible` list also
returns `{}`, both without raising.

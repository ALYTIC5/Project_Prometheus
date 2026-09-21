# Cross-sectional rotation engine (100-strategies Batch A, ranking subset) — design

**Status:** approved for planning, 2026-09-21.

**Resolves:** `docs/DEFERRED.md`'s PROMPT 3 entry — "`StrategySpec` is
still single-`symbol`... **Trigger:** whenever `StrategySpec` gains a
real multi-asset `universe` field with an engine that can trade it — no
prompt has committed to that yet." This is that trigger, scoped to a new
parallel spec type rather than widening `StrategySpec` itself (see
Approach below for why).

## Goal

Implement the 6 ranking-based strategies from `docs/strategies/
STRATEGIES_100.md`'s Batch A (#49 sector momentum rotation, #50 dual
momentum GEM, #51 relative-strength top-3, #52 sector mean reversion,
#53 GTAA 10-month SMA timing, #59 equal-weight baseline) as real,
backtested, validated strategies against the existing ETF universe.

**Explicitly out of scope for this pass** (both decided in brainstorming):
- Risk parity (#57), minimum variance (#58), Defensive/Protective Asset
  Allocation (#54/#55), accelerating dual momentum (#56), 52-week-high
  proximity (#60), cross-asset trend (#61), residual momentum (#62) —
  all need either a covariance/optimizer layer or more design work than
  a ranking primitive covers. Real follow-up, not abandoned.
- Live paper-trading execution. `paper/execution.py` calls `signal_for()`
  for one symbol and diffs one position — a portfolio strategy needs a
  real weight-diffing multi-symbol order generator. That is its own
  fork, built only once something here has actually reached CHAMPION.

## Why this needs new architecture, not just new families

Every family shipped so far — all 17 (13 classic + 4 ML) — is
single-symbol: `StrategySpec.symbol: str` (required), `backtest/
engine.py`'s `run_backtest()` takes one symbol's bars, `signal_for()`
returns one position series. Rotation strategies rank and weight a
*universe* of ETFs at once and hold a portfolio, not a single position.

The good news, confirmed by reading the actual schema before designing
around it: `Strategy.spec` and `Experiment.payload` are already JSONB
(no migration needed for storage), `Strategy.family` is a plain string
discriminator (just widened to VARCHAR(32) in migration 0015),
`benchmark.py`'s `compute_benchmark_curve` already computes Law 8's
"equal-weight for multi-asset" curve for an arbitrary symbol list, and
`config/universe_etf.yaml` + the existing `universe_membership` table
(Law 2 point-in-time reconstruction) already carry every ETF this batch
needs with real listing dates (XLC 2018-06-18, XLRE 2015-10-07, etc.).

The gap is entirely on the strategy-execution and validation side, not
the schema.

## Approach: separate `RotationSpec`, parallel portfolio backtest engine

Two alternatives considered and rejected:

- **Extend `StrategySpec` with an optional `universe` field.** Rejected:
  `symbol: str` is required and read directly by `_min_bars_for`,
  `signal_for`'s dispatch, `config_hash`'s identity fields, and every
  existing call site across 17 families. Making it conditional risks
  regressing already-shipped, already-deployed strategies for a family
  type that doesn't share their execution model at all.
- **Full unification** (rewrite the single-symbol path to be a
  degenerate case of a general multi-asset engine). Rejected as
  unjustified scope: 17 working families, `ml_signal.py`'s walk-forward
  loop, and `paper/execution.py` would all need touching for zero
  incremental benefit to this batch. YAGNI.

Chosen: a new `RotationSpec` model and a new `run_portfolio_backtest()`
that returns the *same* `BacktestResult` shape `run_backtest()` does, so
everything downstream that already consumes a `BacktestResult` (PBO,
Deflated Sharpe, clustering, dashboard rendering of equity curves) needs
no changes at all. Only the dispatch layer (which function to call for
which spec type) is new.

## Components

### 1. `prometheus/strategy/rotation_spec.py` (new)

```python
ROTATION_FAMILY_SECTOR_MOMENTUM = "SECTOR_MOMENTUM_ROTATION"
ROTATION_FAMILY_DUAL_MOMENTUM_GEM = "DUAL_MOMENTUM_GEM"
ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3 = "RELATIVE_STRENGTH_TOP3"
ROTATION_FAMILY_SECTOR_MEAN_REVERSION = "SECTOR_MEAN_REVERSION"
ROTATION_FAMILY_GTAA_SMA = "GTAA_SMA_TIMING"
ROTATION_FAMILY_EQUAL_WEIGHT = "EQUAL_WEIGHT_BASELINE"

ROTATION_FAMILIES = (
    ROTATION_FAMILY_SECTOR_MOMENTUM, ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3, ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_GTAA_SMA, ROTATION_FAMILY_EQUAL_WEIGHT,
)

class RotationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    family: str
    universe: tuple[str, ...]
    timeframe: str
    lookback_days: int | None = None     # None only for EQUAL_WEIGHT (no ranking)
    top_n: int | None = None             # None for GEM/GTAA (binary in/out, not top-N)
    rebalance_frequency_days: int
    expected_horizon: int
    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"
```

Same shape conventions as `StrategySpec`: frozen, `extra="forbid"`, a
`model_validator(mode="after")` enforcing each family only sets the
fields it actually uses (mirrors `_FAMILY_PARAMS`/`_params_match_family`),
`config_hash()` identical in structure to `StrategySpec.config_hash()`
(sha256 of sorted canonical JSON over identity fields — `universe` as a
sorted tuple so member order never changes identity).

### 2. `prometheus/backtest/portfolio_engine.py` (new)

`run_portfolio_backtest(pit, spec: RotationSpec, as_of_cutoff, *,
cost_model=apply_cost, benchmark_result=None) -> BacktestResult`

- Universe reconstructed **per rebalance date**, not once at the end,
  via the existing `universe_membership` table — a rebalance in 2016
  must not see XLC (didn't exist until 2018). Reuses whatever
  point-in-time accessor `data/universe.py` already exposes.
- Rebalance dates: every `rebalance_frequency_days` trading days from
  the first date enough history exists for `lookback_days`.
- On each rebalance date, family-specific logic computes target weights
  (see Family definitions below). Between rebalances, weights drift
  with each constituent's own price — no daily rebalancing drag assumed.
- Turnover cost charged via the existing `cost_model` on the notional
  actually traded (entries, exits, and resizes) at each rebalance —
  same cost model every other family uses, per Law 8's "same cost model
  for entry" fairness requirement applied consistently.
- Returns `BacktestResult` — same dataclass, same fields, same shape.
- Benchmark: `compute_benchmark_curve(pit, list(spec.universe),
  as_of_cutoff, cost_model=cost_model)` — literally the existing
  function, zero new benchmark code. This *is* Law 8's own "equal-weight
  for multi-asset" benchmark, verbatim.

### 3. `prometheus/research/rotation_generate.py` (new)

One grid generator per family. Grid values are the frozen, exact numbers
below — pre-registered here before any backtest, per `docs/strategies/
README.md`'s convention.

### 4. `experiments/runner.py` (modified)

A thin dispatch, `_backtest_result_for(pit, spec, as_of_cutoff, ...)`,
picks `run_backtest` vs `run_portfolio_backtest` by
`isinstance(spec, RotationSpec)`. `run_one` and `enqueue_specs` become
generic over `StrategySpec | RotationSpec` (their bodies barely
reference the spec's internals beyond `.config_hash()`, `.family`,
`.symbol`/`.universe`, and passing it through) — same generalization
precedent already used for the RANDOM_FOREST-era enqueue/validate fix.

**Job payload deserialization, resolved explicitly:** `_run_job` today
does `StrategySpec.model_validate(job.payload["spec"])` unconditionally
— it has no way to know a payload dict is a `RotationSpec`'s dump
instead. Fix: `enqueue_specs` writes an explicit `job.payload["spec_kind"]`
(`"strategy"` or `"rotation"`, matching each spec's own `type(spec).__name__`
at enqueue time, not inferred from field-sniffing the dict), and `_run_job`
branches on it before calling the matching model's `model_validate`. A
missing `spec_kind` (every job enqueued before this change) defaults to
`"strategy"` — the only kind that has ever existed until now, so old
in-flight jobs keep parsing exactly as before.

**Validation gap, stated honestly, not routed around:** `validate_specs`'s
`compute_metrics()` calls `information_coefficient()`/
`information_coefficient_ratio()`, which call `signal_for(bars, spec)`
directly — a single-symbol, single-signal-value concept (Spearman
correlation between one raw signal strength and one symbol's forward
return) that has no defined meaning for a multi-asset weight vector this
project has a citation for. Rather than inventing a translation, a
`RotationSpec`'s `ValidationMetrics.information_coefficient`/`.icir` are
`None` — honestly absent, matching this codebase's own existing
precedent (`excess_sharpe` is `None` below cpz-quant's 30-observation
floor rather than fabricated). `ScoreInputs`/`compute_score` already
don't require IC/ICIR (only `excess_return`, `excess_sharpe`, `pbo`,
`deflated_sharpe`, `has_power_at_claimed_horizon`), so this doesn't
block scoring. `has_power_at_claimed_horizon` (decay.py) also depends on
`information_coefficient_with_pvalue` — same treatment, `None`/not
computed for `RotationSpec`, documented as a known gap in
`docs/DEFERRED.md` once shipped, not silently worked around.

### 5. Clustering — unchanged

`research/clustering.py`'s `cluster_by_correlation` operates on
`(spec, equity_curve)` pairs and only ever calls `.config_hash()` on the
spec. `RotationSpec` exposing the same method means rotation strategies
participate in the same correlation-clustering pool as every other
family — which is economically correct: a sector-momentum rotation
strategy that's mostly re-deriving trend-following should cluster with
`MOMENTUM`/`TRIX`-family finds, not be artificially siloed.

### 6. Frontend — verify, don't assume

Before shipping, check `frontend/src/dashboard/` for any place that
reads `strategy.spec.symbol` directly for display (the existing
`Strategy.spec` JSONB payload). A `RotationSpec`'s dumped JSON has no
`symbol` key. Where found, render `spec.universe` (joined) as a fallback
when `spec.symbol` is absent, rather than crashing or showing "undefined".

### 7. Pre-registration docs

One `docs/strategies/<family_slug>.md` per family (below), written
before this design's implementation plan produces the first backtest,
per the existing convention.

## Family definitions (hypothesis, source, fixed parameters)

### #59 EQUAL_WEIGHT_BASELINE

**Hypothesis:** not an edge claim — the baseline every other rotation
strategy in this batch must beat, per the STRATEGIES_100 doc's own
instruction ("Include #59 equal-weight as the baseline every rotation
strategy must beat").
**Source:** n/a — construction, not a cited effect.
**Universe:** the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY,
XLP, XLU, XLB, XLRE, XLC).
**Parameters:** `rebalance_frequency_days = 21` (monthly). No
`lookback_days`/`top_n` (every constituent gets `1/N` always).
**Expected horizon:** 21 (one rebalance cycle).
**Benchmark:** same universe's own equal-weight buy-and-hold — this
family and its own Law 8 benchmark are the same portfolio without
periodic rebalancing back to equal weight, so the "edge" this family
tests for is specifically the rebalancing effect.

### #49 SECTOR_MOMENTUM_ROTATION

**Hypothesis:** cross-sectional momentum — sectors that outperformed
over the trailing lookback tend to keep outperforming over the next
period (Jegadeesh & Titman's original single-asset finding, applied
cross-sectionally to sectors rather than to individual stocks).
**Source:** Jegadeesh & Titman (1993); sector-level application is the
"honest ETF-universe" version of the sector-rotation idea named in the
STRATEGIES_100 doc.
**Universe:** the 11 SPDR sectors.
**Parameters:** `lookback_days` grid `{63, 126, 252}` (3/6/12 trading
months — the standard momentum lookback horizons in the literature, not
invented), `top_n` grid `{3, 5}`, `rebalance_frequency_days = 21`.
**Expected horizon:** 21.
**Benchmark:** #59's equal-weight sector universe.

### #51 RELATIVE_STRENGTH_TOP3

**Hypothesis:** same cross-sectional momentum mechanism as #49,
specifically at the top-3 concentration named in the STRATEGIES_100
doc — a narrower, higher-conviction version of #49.
**Source:** Jegadeesh & Titman (1993), same as #49.
**Universe:** the 11 SPDR sectors.
**Parameters:** `lookback_days` grid `{63, 126, 252}`, `top_n = 3`
(fixed — it is the strategy's own definition, not a swept parameter),
`rebalance_frequency_days = 21`.
**Expected horizon:** 21.
**Benchmark:** #59.
**Clustering note:** pre-registered expectation, stated honestly before
any backtest runs — #51 is very likely to cluster with #49 at
`top_n=3`, since they're the same ranking mechanism at one shared
parameter value. That is the correlation-clustering machinery working
correctly, not a bug, per `docs/strategies/STRATEGIES_100.md`'s own
framing ("a cluster counts as ONE discovery").

### #52 SECTOR_MEAN_REVERSION

**Hypothesis:** the STRATEGIES_100 doc's own framing — "inverse of #49."
Short-to-medium-horizon reversal: sectors that most underperformed over
the trailing lookback are bought, on the hypothesis that cross-sectional
momentum decays into reversal at shorter horizons (De Bondt & Thaler's
overreaction finding, applied cross-sectionally at the sector level).
**Source:** De Bondt & Thaler (1985).
**Universe:** the 11 SPDR sectors.
**Parameters:** `lookback_days` grid `{21, 63}` (De Bondt & Thaler's own
reversal effect is shorter-horizon than momentum's continuation effect
— different grid range from #49/#51 for exactly that reason, not
arbitrarily), `top_n` grid `{3, 5}` (buys the worst N, not the best),
`rebalance_frequency_days = 21`.
**Expected horizon:** 21.
**Benchmark:** #59.

### #50 DUAL_MOMENTUM_GEM (Gary Antonacci's Global Equities Momentum)

**Hypothesis:** combines absolute momentum (is the asset's own trailing
return positive?) with relative momentum (is US or non-US equity
stronger?) to time between equities and bonds, avoiding sustained equity
drawdowns while capturing the momentum premium.
**Source:** Antonacci, *Dual Momentum Investing* (2014). GEM's own
published rule set — not this project's invention.
**Universe:** `{SPY, EFA, TLT}` — Antonacci's own published proxies
(US equity, non-US developed equity, long treasuries as the defensive
asset). `EFA` and `TLT` are both already in `config/universe_etf.yaml`
with real listing dates.
**Parameters:** `lookback_days = 252` (GEM's own published 12-month
lookback — fixed, not a grid, because it is the strategy's own
definition per the source), `rebalance_frequency_days = 21` (GEM's own
published monthly check). No `top_n` (GEM's rule: hold 100% of whichever
one of SPY/EFA has the higher trailing return, if positive; else 100%
TLT — binary selection, not a ranked top-N).
**Expected horizon:** 21.
**Benchmark:** equal-weight of `{SPY, EFA, TLT}` (Law 8's own words —
"equal-weight for multi-asset" — applied to GEM's specific 3-asset
universe, not the 11-sector universe the other families use, since
GEM's is a genuinely different universe).

### #53 GTAA_SMA_TIMING (Mebane Faber's Global Tactical Asset Allocation)

**Hypothesis:** a simple trend filter (price above/below its own trailing
simple moving average) reduces drawdowns versus buy-and-hold with little
cost to return, applied per-asset across a multi-asset universe.
**Source:** Faber, "A Quantitative Approach to Tactical Asset Allocation"
(2007) — the paper's own published 10-month SMA rule.
**Universe:** `{SPY, EFA, IEF, VNQ, GLD}` — Faber's own published
5-asset GTAA universe (US equity, foreign equity, bonds, REITs, gold).
All 5 already exist in `config/universe_etf.yaml`.
**Parameters:** `lookback_days = 210` (Faber's own published 10-month ×
21 trading days — fixed, per-source, not swept), `rebalance_frequency_days
= 21` (Faber's own published monthly rule). No `top_n` — each of the 5
assets is independently in (above its own SMA) or out (below it, into
cash), not ranked against each other.
**Expected horizon:** 21.
**Benchmark:** equal-weight of `{SPY, EFA, IEF, VNQ, GLD}`.

## Testing plan

- Unit tests for `RotationSpec`'s validator (family/field matching,
  `config_hash()` stability, universe-order independence).
- Unit tests for `run_portfolio_backtest`'s rebalancing mechanics on
  synthetic bars: a 2-asset universe with a known, hand-computed weight
  trajectory and turnover cost, verified against a manually-derived
  expected equity curve (same style as the existing `_run_accounting`
  tests).
- A Law-2 test: a rebalance date before an ETF's `listed_at` must not
  include it in that rebalance's universe (synthetic universe_membership
  fixture, same pattern `tests/laws/` already uses for survivorship).
- A Law-1 test: no rebalance's weight decision may read a bar whose
  `available_at` is after the rebalance's own decision timestamp.
- `compute_metrics` on a `RotationSpec`'s result returns
  `information_coefficient=None`/`icir=None` without raising.
- End-to-end: `run_one`/`enqueue_specs`/`validate_specs` accept a
  `RotationSpec` without touching `StrategySpec`'s own test suite.

## What this does NOT claim

Most of Batch A will likely fail Law 8 (underperform buy-and-hold after
costs) or get PBO-rejected — expected, per the STRATEGIES_100 doc's own
"What to expect" section, and not something this design tries to avoid.
GEM and GTAA in particular are well-cited but were both discovered on
pre-2015 data; this project's own out-of-sample window is exactly the
honest test of whether they still hold.

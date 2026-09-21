# Cross-Sectional Rotation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 6 cross-sectional rotation strategies (#49, #50, #51,
#52, #53, #59 from `docs/strategies/STRATEGIES_100.md`) as real,
backtested, validated strategies against the existing ETF universe, via
a new parallel `RotationSpec` model and portfolio backtest engine.

**Architecture:** A new `RotationSpec` (multi-asset universe, not a
single symbol) and a new `run_portfolio_backtest()` that returns the
same `BacktestResult` shape `run_backtest()` already returns, so
everything downstream (PBO, DSR, clustering, dashboard) needs no
changes. `experiments/runner.py` gets a thin dispatch by spec type.
Validation's IC/ICIR/decay (which are inherently single-symbol-signal
concepts) are honestly `None` for `RotationSpec` rather than a
fabricated translation.

**Tech Stack:** Python 3.11, polars, pydantic, SQLAlchemy 2.x async,
pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-21-cross-sectional-rotation-design.md`

## Global Constraints

- Law 1 (no look-ahead): every rebalance decision uses only bars whose
  `available_at <= decision_timestamp`; universe membership at a
  rebalance date uses only `listed_at <= date < delisted_at`.
- Law 2 (no survivorship bias): universe reconstructed **per rebalance
  date** from `universe_membership`, never a fixed today's-list applied
  retroactively.
- Law 6 (append-only): `Experiment`/`Result`/`Decision`/`ValidationResult`
  rows are INSERT-only, same as every existing family.
- Law 7 (no invented thresholds): every parameter grid value below is
  copied from a cited source (Antonacci 2014, Faber 2007, Jegadeesh &
  Titman 1993, De Bondt & Thaler 1985) or is this batch's own explicit
  convention (monthly rebalance = 21 trading days), never invented.
- Law 8 (benchmark): every `RotationSpec`'s benchmark is
  `compute_benchmark_curve(pit, list(spec.universe), ...)` —
  equal-weight of that spec's own universe, per Law 8's literal text.
- `RotationSpec` is frozen, `extra="forbid"`, same conventions as
  `StrategySpec` (`prometheus/strategy/spec.py`).
- IC/ICIR/decay honestly `None` for `RotationSpec` — do not invent a
  multi-asset translation of a single-symbol-signal concept.
- No schema migration in this plan beyond what's already shipped
  (`0015_widen_strategy_family.py`). `Strategy.spec`/`Experiment.payload`
  are JSONB; no new columns needed.

---

## Task 1: `RotationSpec` model + widen the strategy-id family regex

**Files:**
- Create: `prometheus/strategy/rotation_spec.py`
- Modify: `prometheus/core/ids.py:39` (widen `_FAMILY_RE`)
- Test: `tests/test_rotation_spec.py` (new)
- Test: `tests/test_ids.py` (extend, if it exists — otherwise add cases
  to whatever test file currently covers `next_strategy_id`)

**Interfaces:**
- Produces: `RotationSpec` (frozen pydantic model), `ROTATION_FAMILIES`
  (tuple of 6 family-name strings), `ROTATION_FAMILY_SECTOR_MOMENTUM`,
  `ROTATION_FAMILY_DUAL_MOMENTUM_GEM`, `ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3`,
  `ROTATION_FAMILY_SECTOR_MEAN_REVERSION`, `ROTATION_FAMILY_GTAA_SMA`,
  `ROTATION_FAMILY_EQUAL_WEIGHT` (module-level string constants),
  `RotationSpec.config_hash() -> str`.

**Background — a second real family-name-length bug, caught before it
ships:** `prometheus/core/ids.py:39`'s `_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")`
caps family names at 20 characters total. 4 of the 6 rotation family
names below exceed it: `SECTOR_MOMENTUM_ROTATION` (24 chars),
`RELATIVE_STRENGTH_TOP3` (22), `SECTOR_MEAN_REVERSION` (21),
`EQUAL_WEIGHT_BASELINE` (21). Only `DUAL_MOMENTUM_GEM` (17) and
`GTAA_SMA_TIMING` (15) fit today. This must be fixed in this same task
or `next_strategy_id()` raises `ValueError: invalid strategy family` the
first time any of these 4 families is used — same failure class as the
`VOL_BREAKOUT` bug this file's own comment already documents, and the
same class as migration `0015`'s `strategies.family` VARCHAR fix.

- [ ] **Step 1: Write the failing test for the widened family regex**

Add to whichever test file exercises `next_strategy_id` today (search
`tests/` for `next_strategy_id` if unsure which file):

```python
import pytest
from prometheus.core.ids import next_strategy_id

@pytest.mark.db
async def test_next_strategy_id_accepts_rotation_family_names() -> None:
    # SECTOR_MOMENTUM_ROTATION is 24 chars -- exceeds the old 20-char cap.
    strategy_id = await next_strategy_id("SECTOR_MOMENTUM_ROTATION")
    assert strategy_id.startswith("SECTOR_MOMENTUM_ROTATION-")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ids.py -k rotation_family -v` (adjust path to
the actual file)
Expected: FAIL with `ValueError: invalid strategy family: 'SECTOR_MOMENTUM_ROTATION'`

- [ ] **Step 3: Widen `_FAMILY_RE`**

In `prometheus/core/ids.py`, change:

```python
_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
```

to:

```python
# Widened again (cross-sectional rotation) after SECTOR_MOMENTUM_ROTATION
# (24 chars), RELATIVE_STRENGTH_TOP3 (22), SECTOR_MEAN_REVERSION (21), and
# EQUAL_WEIGHT_BASELINE (21) all exceeded the old 20-char cap -- same bug
# class as the VOL_BREAKOUT fix above, caught this time before shipping
# rather than after. 32 chars matches strategies.family's own VARCHAR(32)
# width (migration 0015) so this regex can never accept a family name the
# database would then reject.
_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_ids.py -k rotation_family -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for `RotationSpec`**

Create `tests/test_rotation_spec.py`:

```python
"""tests/test_rotation_spec.py"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

_SECTORS = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)


def test_equal_weight_spec_requires_no_lookback_or_top_n() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=_SECTORS,
        timeframe="1d",
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec.lookback_days is None
    assert spec.top_n is None


def test_sector_momentum_requires_lookback_and_top_n() -> None:
    with pytest.raises(ValidationError, match="requires"):
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MOMENTUM,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_sector_momentum_rejects_foreign_fields() -> None:
    with pytest.raises(ValidationError, match="must not set"):
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTORS,
            timeframe="1d",
            lookback_days=63,  # EQUAL_WEIGHT never ranks -- foreign field
            top_n=3,
            rebalance_frequency_days=21,
            expected_horizon=21,
        )


def test_config_hash_is_stable_and_universe_order_independent() -> None:
    spec_a = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLK", "XLF"),
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    spec_b = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLF", "XLK"),  # same members, different order
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    assert spec_a.config_hash() == spec_b.config_hash()


def test_config_hash_changes_with_top_n() -> None:
    base = dict(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=_SECTORS,
        timeframe="1d",
        lookback_days=126,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    spec_top3 = RotationSpec(**base, top_n=3)
    spec_top5 = RotationSpec(**base, top_n=5)
    assert spec_top3.config_hash() != spec_top5.config_hash()


def test_frozen_and_extra_forbidden() -> None:
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=_SECTORS,
        timeframe="1d",
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    with pytest.raises(ValidationError):
        spec.rebalance_frequency_days = 42  # frozen
    with pytest.raises(ValidationError):
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTORS,
            timeframe="1d",
            rebalance_frequency_days=21,
            expected_horizon=21,
            symbol="SPY",  # not a RotationSpec field -- extra="forbid"
        )
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/test_rotation_spec.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'prometheus.strategy.rotation_spec'`)

- [ ] **Step 7: Implement `RotationSpec`**

Create `prometheus/strategy/rotation_spec.py`. Mirror
`prometheus/strategy/spec.py`'s own conventions exactly (frozen,
`extra="forbid"`, `_FAMILY_PARAMS`-style dict, `model_validator`,
`config_hash()` over sorted canonical JSON):

```python
"""Cross-sectional rotation strategies -- multi-asset, ranking a
UNIVERSE rather than trading one symbol. Deliberately a separate model
from StrategySpec, not an extension of it: StrategySpec.symbol is
required and read directly throughout backtest/engine.py's dispatch,
core.ids' seed derivation, and config_hash's identity fields across all
17 already-shipped single-symbol families -- making it conditional would
risk regressing those for a family type that shares none of their
execution model. See docs/superpowers/specs/2026-09-21-cross-sectional-
rotation-design.md for the full design.

Six families, all cited (Jegadeesh & Titman 1993, De Bondt & Thaler
1985, Antonacci 2014, Faber 2007) or this batch's own explicit
convention (equal-weight baseline, monthly = 21-trading-day rebalance).
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, model_validator

ROTATION_FAMILY_SECTOR_MOMENTUM = "SECTOR_MOMENTUM_ROTATION"
ROTATION_FAMILY_DUAL_MOMENTUM_GEM = "DUAL_MOMENTUM_GEM"
ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3 = "RELATIVE_STRENGTH_TOP3"
ROTATION_FAMILY_SECTOR_MEAN_REVERSION = "SECTOR_MEAN_REVERSION"
ROTATION_FAMILY_GTAA_SMA = "GTAA_SMA_TIMING"
ROTATION_FAMILY_EQUAL_WEIGHT = "EQUAL_WEIGHT_BASELINE"

ROTATION_FAMILIES = (
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_EQUAL_WEIGHT,
)

# Which optional fields each family actually reads -- a model_validator
# below enforces a spec never carries a field its own family doesn't use,
# same discipline StrategySpec's _FAMILY_PARAMS/_params_match_family uses.
_FAMILY_PARAMS: dict[str, tuple[str, ...]] = {
    ROTATION_FAMILY_SECTOR_MOMENTUM: ("lookback_days", "top_n"),
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM: ("lookback_days",),
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3: ("lookback_days", "top_n"),
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION: ("lookback_days", "top_n"),
    ROTATION_FAMILY_GTAA_SMA: ("lookback_days",),
    ROTATION_FAMILY_EQUAL_WEIGHT: (),
}
_ALL_PARAM_FIELDS = ("lookback_days", "top_n")

# config_hash()'s identity fields -- everything that changes this spec's
# actual backtested BEHAVIOR. parent_id/description/source are
# provenance, not behavior, same exclusion StrategySpec.config_hash()
# already makes.
_IDENTITY_FIELDS = (
    "family", "universe", "timeframe", "lookback_days", "top_n",
    "rebalance_frequency_days", "expected_horizon",
)


class RotationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str
    universe: tuple[str, ...]
    timeframe: str
    lookback_days: int | None = None
    top_n: int | None = None
    rebalance_frequency_days: int
    expected_horizon: int

    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"

    @model_validator(mode="after")
    def _params_match_family(self) -> RotationSpec:
        if self.family not in _FAMILY_PARAMS:
            raise ValueError(f"unknown rotation family: {self.family!r}")
        if not self.universe:
            raise ValueError("universe must be non-empty")
        required = _FAMILY_PARAMS[self.family]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"family {self.family!r} requires {missing}")
        foreign = [
            f for f in _ALL_PARAM_FIELDS
            if f not in required and getattr(self, f) is not None
        ]
        if foreign:
            raise ValueError(f"family {self.family!r} must not set {foreign}")
        if self.rebalance_frequency_days <= 0:
            raise ValueError("rebalance_frequency_days must be positive")
        if self.lookback_days is not None and self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if self.top_n is not None and not (0 < self.top_n <= len(self.universe)):
            raise ValueError("top_n must be in (0, len(universe)]")
        return self

    def config_hash(self) -> str:
        """Same pattern as StrategySpec.config_hash() -- a stable hash of
        canonical content. `universe` is sorted before hashing so member
        ORDER never changes identity (a grid generator building the tuple
        from a set, or a caller passing it in a different order, must not
        silently mint a second, spuriously-distinct spec for the same
        actual strategy)."""
        canonical = self.model_dump(include=set(_IDENTITY_FIELDS))
        canonical["universe"] = sorted(canonical["universe"])
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

- [ ] **Step 8: Run to verify all pass**

Run: `pytest tests/test_rotation_spec.py tests/test_ids.py -v`
Expected: PASS (all tests from Steps 1 and 5)

- [ ] **Step 9: Type-check**

Run: `mypy prometheus/strategy/rotation_spec.py prometheus/core/ids.py --strict`
Expected: `Success: no issues found`

- [ ] **Step 10: Commit**

```bash
git add prometheus/strategy/rotation_spec.py prometheus/core/ids.py tests/test_rotation_spec.py tests/test_ids.py
git commit -m "feat(strategy): RotationSpec for cross-sectional rotation families"
```

---

## Task 2: point-in-time universe membership windows accessor

**Files:**
- Modify: `prometheus/data/universe.py`
- Test: `tests/test_universe.py` (extend if it exists, else create;
  `pytest.mark.db` since it needs a real `universe_membership` table)

**Interfaces:**
- Consumes: `UniverseMembership` (already imported in `data/universe.py`
  from `prometheus.data.models`).
- Produces: `membership_windows(session, asset_class, symbols) ->
  dict[str, tuple[date, date | None]]` — `{symbol: (listed_at,
  delisted_at)}` for every requested symbol that has a
  `universe_membership` row under `asset_class`. A symbol with no
  matching row is simply absent from the returned dict (caller's job to
  decide what "never listed under this asset_class" means — for this
  plan's use, portfolio_engine.py in Task 3 treats "absent" as "never
  eligible," which is correct: it means this symbol was never
  registered as part of this asset class's universe at all).

**Why this exists, not reuse of `as_of()`:** `as_of(session, date,
asset_class)` (already in this file) answers "which symbols were live
on ONE date" — it needs a fresh DB round-trip per date. `run_portfolio_
backtest` (Task 3) needs to check membership at potentially dozens of
rebalance dates across a multi-year backtest, and must stay a pure,
synchronous, deterministic function (this project's own "every backtest
takes an explicit seed and is bit-reproducible" rule) with no hidden IO.
`membership_windows` is fetched ONCE by the caller (`run_one`/`validate_
rotation_specs` in Task 8/9) and passed into `run_portfolio_backtest` as
plain data; the pure function then does `listed_at <= rebalance_date <
(delisted_at or date.max)` in-memory, no session needed.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_universe.py` (check existing file structure first;
match its existing fixture-setup style for inserting `UniverseMembership`
rows against a real test DB):

```python
@pytest.mark.db
async def test_membership_windows_returns_listed_and_delisted_dates(db_session) -> None:
    # Adjust fixture name (db_session) to match this file's existing
    # convention -- read the top of tests/test_universe.py first.
    from datetime import date
    from prometheus.data.universe import membership_windows
    from prometheus.data.models import UniverseMembership

    db_session.add_all([
        UniverseMembership(
            symbol="XLC", exchange="alpaca", asset_class="etf",
            listed_at=date(2018, 6, 18), delisted_at=None,
        ),
        UniverseMembership(
            symbol="XLK", exchange="alpaca", asset_class="etf",
            listed_at=date(1998, 12, 16), delisted_at=None,
        ),
    ])
    await db_session.flush()

    windows = await membership_windows(db_session, "etf", ["XLC", "XLK", "GLD"])

    assert windows["XLC"] == (date(2018, 6, 18), None)
    assert windows["XLK"] == (date(1998, 12, 16), None)
    assert "GLD" not in windows  # never registered under "etf" in this test
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_universe.py -k membership_windows -v`
Expected: FAIL (`ImportError: cannot import name 'membership_windows'`)

- [ ] **Step 3: Implement**

Add to `prometheus/data/universe.py` (after `as_of`):

```python
async def membership_windows(
    session: AsyncSession, asset_class: str, symbols: list[str]
) -> dict[str, tuple[date, date | None]]:
    """One (listed_at, delisted_at) window per symbol under
    `asset_class`, fetched once so a caller doing point-in-time universe
    reconstruction across many dates (run_portfolio_backtest's many
    rebalance dates) does one query, not one per date. A symbol with no
    matching row is absent from the result -- it was never part of this
    asset class's universe at all, under any date."""
    stmt = select(
        UniverseMembership.symbol, UniverseMembership.listed_at, UniverseMembership.delisted_at
    ).where(
        UniverseMembership.asset_class == asset_class,
        UniverseMembership.symbol.in_(symbols),
    )
    result = await session.execute(stmt)
    return {row.symbol: (row.listed_at, row.delisted_at) for row in result.all()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_universe.py -k membership_windows -v`
Expected: PASS

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/data/universe.py --strict`
Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add prometheus/data/universe.py tests/test_universe.py
git commit -m "feat(data): membership_windows accessor for portfolio backtest"
```

---

## Task 3: portfolio backtest core mechanics + EQUAL_WEIGHT_BASELINE (#59)

**Files:**
- Create: `prometheus/backtest/portfolio_engine.py`
- Create: `docs/strategies/equal_weight_baseline.md`
- Test: `tests/test_portfolio_engine.py` (new)

**Interfaces:**
- Consumes: `RotationSpec` (Task 1), `membership_windows()` return shape
  (Task 2: `dict[str, tuple[date, date | None]]`), `PointInTimeFrame`
  (`prometheus/data/schema.py`), `CostModel`/`apply_cost`
  (`prometheus/backtest/costs.py`), `compute_benchmark_curve`
  (`prometheus/backtest/benchmark.py`), `BacktestResult`/`VsBenchmark`
  (`prometheus/backtest/benchmark.py` — `VsBenchmark` — and wherever
  `BacktestResult` itself is defined in `prometheus/backtest/engine.py`
  — check its exact field list there before writing this task's code:
  `equity_curve: tuple[tuple[str, float], ...]`, `total_return_pct: float`,
  `max_drawdown_pct: float`, `turnover: float`, `gross_return_pct: float`,
  `total_costs: float`, `vs_benchmark: VsBenchmark`).
- Produces: `run_portfolio_backtest(pit, spec, membership, as_of_cutoff,
  *, cost_model=apply_cost, benchmark_result=None) -> BacktestResult`
  (`membership: dict[str, tuple[date, date | None]]` from Task 2),
  `weights_for_equal_weight(eligible_symbols: list[str]) -> dict[str, float]`
  (the simplest family's weight function, and the shape every later
  family's weight function in Tasks 4-6 matches:
  `(eligible_symbols, price_history_by_symbol, lookback_days, top_n) ->
  dict[str, float]`, summing to 1.0 or to 0.0 if nothing is eligible).

**Rebalancing mechanics (apply to every family, this task proves it
against the simplest one):**

1. Rebalance dates: starting from the first date with `lookback_days`
   (or 0 for `EQUAL_WEIGHT_BASELINE`, which has none) of prior daily
   bars available for at least one universe member, every
   `rebalance_frequency_days` **trading days** thereafter (counted over
   the union of all universe members' available dates, sorted) through
   `as_of_cutoff`.
2. At each rebalance date, determine the eligible subset of
   `spec.universe` via `membership`: symbol is eligible if
   `membership[symbol][0] <= rebalance_date and (membership[symbol][1]
   is None or rebalance_date < membership[symbol][1])`. A symbol absent
   from `membership` entirely is never eligible.
3. Compute target weights over the eligible subset via the family's own
   weight function (Task 3 builds `weights_for_equal_weight`; Tasks 4-6
   add the rest, all called from the same dispatch inside
   `run_portfolio_backtest` keyed on `spec.family`).
4. Between rebalance dates, each held symbol's weight drifts with its
   own daily return (no daily rebalancing drag) — track per-symbol
   dollar allocations, not fixed weights, between rebalances.
5. At each rebalance, cost is charged via `cost_model` on the notional
   actually traded: `sum(abs(new_dollar_alloc[s] - old_dollar_alloc[s])
   for s in union(old, new))`. A symbol entering or leaving costs its
   full notional; a symbol staying in but resized costs only the delta.
6. `turnover` accumulates the same traded-notional sum across every
   rebalance, expressed as a fraction of portfolio equity at that
   rebalance (matching `_run_accounting`'s own `_position_change`
   convention of summing fractional position changes, generalized to a
   sum over symbols instead of a single scalar).

- [ ] **Step 1: Write the failing test — equal-weight rebalancing with hand-computed expected values**

Create `tests/test_portfolio_engine.py`:

```python
"""tests/test_portfolio_engine.py"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.portfolio_engine import (
    run_portfolio_backtest,
    weights_for_equal_weight,
)
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import ROTATION_FAMILY_EQUAL_WEIGHT, RotationSpec


def test_weights_for_equal_weight_splits_evenly() -> None:
    weights = weights_for_equal_weight(["A", "B", "C"])
    assert weights == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_weights_for_equal_weight_empty_universe_is_empty() -> None:
    assert weights_for_equal_weight([]) == {}


def _synthetic_pit(prices: dict[str, list[float]], start: datetime) -> PointInTimeFrame:
    rows = []
    for symbol, closes in prices.items():
        for i, close in enumerate(closes):
            ts = start + timedelta(days=i)
            rows.append(
                {
                    "symbol": symbol, "timeframe": "1d", "available_at": ts,
                    "open": close, "high": close, "low": close, "close": close,
                    "volume": 1000.0,
                }
            )
    return PointInTimeFrame(pl.DataFrame(rows))


def test_equal_weight_two_symbols_no_rebalance_drift_matches_hand_calc() -> None:
    # A: flat at 100 the whole time. B: 100 -> 110 (a +10% move on day 5).
    # rebalance_frequency_days larger than the window -- exactly ONE
    # rebalance at the start, no mid-window rebalance -- isolates pure
    # buy-and-hold-of-equal-weight drift with a hand-computable answer:
    # start $1000 equally split ($500/$500), zero cost model, B's leg
    # grows 10% -> $550, A's leg flat -> $500, total $1050 = +5.0%.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {"A": [100.0] * 6, "B": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]}, start
    )
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2019, 1, 1), None),
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,  # longer than the 6-day window
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, start + timedelta(days=5),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(5.0, abs=0.01)


def test_equal_weight_excludes_symbol_before_its_listed_at() -> None:
    # B isn't "listed" (per membership) until day 3 -- a rebalance at
    # day 0 must be 100% A, not split with a not-yet-eligible B.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit({"A": [100.0] * 4, "B": [100.0] * 4}, start)
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2020, 1, 4), None),  # listed after this whole window
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, start + timedelta(days=3),
        cost_model=lambda notional: 0.0,
    )
    # Flat prices throughout, whichever symbols were actually held --
    # the real assertion is that this doesn't raise and returns ~0%,
    # proving B's exclusion didn't leave a dangling/NaN allocation.
    assert result.total_return_pct == pytest.approx(0.0, abs=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_portfolio_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'prometheus.backtest.portfolio_engine'`)

- [ ] **Step 3: Implement `portfolio_engine.py`**

Read `prometheus/backtest/engine.py`'s `_run_accounting` (around line
740) and `BacktestResult`'s exact field list before writing this, so the
returned object matches field-for-field. Then create
`prometheus/backtest/portfolio_engine.py`:

```python
"""Portfolio-level backtest engine for RotationSpec -- cross-sectional
rotation strategies that hold a weighted basket of a UNIVERSE rather
than a single symbol's position. Returns the same BacktestResult shape
run_backtest() does (backtest/engine.py) so every downstream consumer
(PBO, Deflated Sharpe, clustering, dashboard) needs zero changes.

See docs/superpowers/specs/2026-09-21-cross-sectional-rotation-design.md.
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl

from prometheus.backtest.benchmark import compute_benchmark_curve, compute_vs_benchmark, BenchmarkResult
from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, BacktestResult
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import ROTATION_FAMILY_EQUAL_WEIGHT, RotationSpec

Membership = dict[str, tuple[date, date | None]]


def weights_for_equal_weight(eligible_symbols: list[str]) -> dict[str, float]:
    """#59's own definition: 1/N across whatever is eligible right now,
    always. Empty input -> empty weights (100% cash), not a ZeroDivisionError."""
    if not eligible_symbols:
        return {}
    share = 1.0 / len(eligible_symbols)
    return {symbol: share for symbol in eligible_symbols}


def _eligible_symbols(universe: tuple[str, ...], membership: Membership, as_of: date) -> list[str]:
    eligible = []
    for symbol in universe:
        window = membership.get(symbol)
        if window is None:
            continue
        listed_at, delisted_at = window
        if listed_at <= as_of and (delisted_at is None or as_of < delisted_at):
            eligible.append(symbol)
    return eligible


def _weights_for(
    spec: RotationSpec, eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of_idx: int
) -> dict[str, float]:
    if spec.family == ROTATION_FAMILY_EQUAL_WEIGHT:
        return weights_for_equal_weight(eligible)
    raise ValueError(f"no weight function wired for family {spec.family!r}")  # Tasks 4-6 extend this


def _rebalance_dates(
    dates: list[date], first_eligible_idx: int, rebalance_frequency_days: int
) -> list[int]:
    """Indices into `dates` (already deduplicated, sorted) where a
    rebalance happens: the first eligible index, then every
    `rebalance_frequency_days` trading-day step after it."""
    return list(range(first_eligible_idx, len(dates), rebalance_frequency_days))


def run_portfolio_backtest(
    pit: PointInTimeFrame,
    spec: RotationSpec,
    membership: Membership,
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    frame = pit.as_of(as_of_cutoff).filter(pl.col("symbol").is_in(list(spec.universe)))
    all_dates = sorted({row["available_at"].date() for row in frame.iter_rows(named=True)})
    if not all_dates:
        raise ValueError(f"no bars for universe {spec.universe} as of {as_of_cutoff}")

    bars_by_symbol = {
        symbol: frame.filter(pl.col("symbol") == symbol).sort("available_at")
        for symbol in spec.universe
    }
    close_by_symbol_date: dict[str, dict[date, float]] = {
        symbol: {row["available_at"].date(): row["close"] for row in bars.iter_rows(named=True)}
        for symbol, bars in bars_by_symbol.items()
    }

    warmup = spec.lookback_days or 0
    first_idx = min(warmup, len(all_dates) - 1)
    rebalance_indices = set(_rebalance_dates(all_dates, first_idx, spec.rebalance_frequency_days))

    dollar_alloc: dict[str, float] = {}  # symbol -> current $ allocation
    equity = STARTING_CAPITAL
    gross_equity = STARTING_CAPITAL
    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    turnover = 0.0
    total_costs = 0.0
    curve: list[tuple[str, float]] = []

    for idx, as_of in enumerate(all_dates):
        if idx >= first_idx:
            # Drift existing allocations forward by each held symbol's
            # own return since the previous date, before any rebalance
            # decision at this date -- yesterday's weights earned
            # yesterday-to-today's return first.
            if idx > first_idx:
                prev_date = all_dates[idx - 1]
                for symbol in list(dollar_alloc):
                    prev_close = close_by_symbol_date[symbol].get(prev_date)
                    curr_close = close_by_symbol_date[symbol].get(as_of)
                    if prev_close and curr_close:
                        dollar_alloc[symbol] *= curr_close / prev_close

            if idx in rebalance_indices:
                eligible = _eligible_symbols(spec.universe, membership, as_of)
                target_weights = _weights_for(spec, eligible, bars_by_symbol, idx)
                current_equity = sum(dollar_alloc.values()) or STARTING_CAPITAL
                target_alloc = {s: w * current_equity for s, w in target_weights.items()}
                traded = sum(
                    abs(target_alloc.get(s, 0.0) - dollar_alloc.get(s, 0.0))
                    for s in set(target_alloc) | set(dollar_alloc)
                )
                if traded:
                    cost = cost_model(traded)
                    current_equity -= cost
                    total_costs += cost
                    turnover += traded / current_equity if current_equity else 0.0
                    # Re-scale target_alloc down proportionally for the cost paid.
                    scale = current_equity / sum(target_alloc.values()) if sum(target_alloc.values()) else 1.0
                    target_alloc = {s: v * scale for s, v in target_alloc.items()}
                dollar_alloc = target_alloc

        equity = sum(dollar_alloc.values()) if dollar_alloc else equity
        gross_equity = equity + total_costs  # approx gross -- costs added back
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        curve.append((datetime.combine(as_of, datetime.min.time()).isoformat(), equity))

    equity_curve = tuple(curve)
    total_return_pct = (equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    gross_return_pct = (gross_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, list(spec.universe), as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(equity_curve, max_drawdown * 100, benchmark_result)

    return BacktestResult(
        equity_curve=equity_curve,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown * 100,
        turnover=turnover,
        gross_return_pct=gross_return_pct,
        total_costs=total_costs,
        vs_benchmark=vs_benchmark,
    )
```

**Note for the implementer:** before writing this file, `Read` the real
`BacktestResult` dataclass definition in `prometheus/backtest/engine.py`
and confirm the field list above matches exactly (name and order don't
have to match, but every field must be populated with the right type).
If `BacktestResult` lives somewhere else or has different fields, adjust
this task's code accordingly — do not invent new fields on it.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_portfolio_engine.py -v`
Expected: PASS for all 4 tests

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/backtest/portfolio_engine.py --strict`
Expected: `Success: no issues found` (fix any typing issues the sketch
above didn't anticipate — e.g. `pl.DataFrame.iter_rows(named=True)`'s
row type may need explicit handling for mypy strict)

- [ ] **Step 6: Write the pre-registration doc**

Create `docs/strategies/equal_weight_baseline.md` using
`docs/strategies/TEMPLATE.md`'s structure, filled in from this plan's
Global Constraints and this task's own "#59" family definition (copy
the hypothesis/source/parameters/expected horizon/benchmark text from
`docs/superpowers/specs/2026-09-21-cross-sectional-rotation-design.md`'s
`### #59 EQUAL_WEIGHT_BASELINE` section verbatim).

- [ ] **Step 7: Commit**

```bash
git add prometheus/backtest/portfolio_engine.py tests/test_portfolio_engine.py docs/strategies/equal_weight_baseline.md
git commit -m "feat(backtest): portfolio engine core mechanics + EQUAL_WEIGHT_BASELINE"
```

---

## Task 4: ranking primitive + SECTOR_MOMENTUM_ROTATION, RELATIVE_STRENGTH_TOP3, SECTOR_MEAN_REVERSION

**Files:**
- Modify: `prometheus/backtest/portfolio_engine.py` (add ranking weight
  functions, extend `_weights_for`'s dispatch)
- Create: `docs/strategies/sector_momentum_rotation.md`,
  `docs/strategies/relative_strength_top3.md`,
  `docs/strategies/sector_mean_reversion.md`
- Test: extend `tests/test_portfolio_engine.py`

**Interfaces:**
- Consumes: `_eligible_symbols`, `Membership`, `bars_by_symbol` (Task 3).
- Produces: `trailing_return(bars: pl.DataFrame, as_of: date, lookback_days:
  int) -> float | None` (the shared ranking primitive — `None` when
  there isn't `lookback_days` of history before `as_of` for this
  symbol, so it can be excluded from ranking rather than crashing or
  silently using a shorter, non-comparable window), `weights_for_top_n_
  momentum(eligible, bars_by_symbol, as_of, lookback_days, top_n, *,
  worst=False) -> dict[str, float]` (equal-weight across whichever N
  symbols rank highest by trailing return, or lowest when
  `worst=True` — the shared function #49/#51/#52 all call, since
  #52 IS #49's ranking with `worst=True` per the design doc's own "#52
  is the inverse of #49" framing).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_portfolio_engine.py`:

```python
from datetime import date

from prometheus.backtest.portfolio_engine import trailing_return, weights_for_top_n_momentum


def test_trailing_return_none_when_insufficient_history() -> None:
    bars = pl.DataFrame(
        {"available_at": [datetime(2020, 1, 1), datetime(2020, 1, 2)], "close": [100.0, 101.0]}
    )
    assert trailing_return(bars, date(2020, 1, 2), lookback_days=10) is None


def test_trailing_return_computes_pct_change_over_lookback() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(5)]
    closes = [100.0, 101.0, 102.0, 103.0, 110.0]
    bars = pl.DataFrame({"available_at": dates, "close": closes})
    # From day 1 (100.0) to day 5 (110.0), lookback_days=4 (index span).
    assert trailing_return(bars, date(2020, 1, 5), lookback_days=4) == pytest.approx(0.10)


def test_weights_for_top_n_momentum_picks_best_n_equal_weighted() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),  # +5%
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),  # +20% best
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=2,
    )
    assert set(weights) == {"A", "C"}  # top 2 by return: C then A
    assert weights["A"] == pytest.approx(0.5)
    assert weights["C"] == pytest.approx(0.5)


def test_weights_for_top_n_momentum_worst_picks_bottom_n() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2),
        lookback_days=1, top_n=1, worst=True,
    )
    assert set(weights) == {"B"}  # worst performer
    assert weights["B"] == pytest.approx(1.0)


def test_weights_for_top_n_momentum_fewer_eligible_than_top_n_uses_all_eligible() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=3,
    )
    assert weights == {"A": pytest.approx(1.0)}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_portfolio_engine.py -k "trailing_return or top_n_momentum" -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Implement**

Add to `prometheus/backtest/portfolio_engine.py`:

```python
def trailing_return(bars: pl.DataFrame, as_of: date, lookback_days: int) -> float | None:
    """Close-to-close return from `lookback_days` bars before `as_of` to
    `as_of` itself. None when there aren't enough prior bars -- an
    honestly-excluded symbol from this ranking cycle, not a fabricated
    0.0 that would make it look like a flat, tied-for-worst performer."""
    rows = bars.filter(pl.col("available_at") <= datetime.combine(as_of, datetime.min.time()))
    if rows.height <= lookback_days:
        return None
    closes = rows["close"].to_list()
    start_close = closes[-(lookback_days + 1)]
    end_close = closes[-1]
    if start_close == 0:
        return None
    return (end_close - start_close) / start_close


def weights_for_top_n_momentum(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    lookback_days: int,
    top_n: int,
    *,
    worst: bool = False,
) -> dict[str, float]:
    """Shared ranking primitive for #49 (best-N), #51 (best-3, top_n
    fixed by the caller's spec), and #52 (worst-N, worst=True) -- #52 is
    literally #49's own mechanism with the sort direction flipped, per
    the design doc's "inverse of #49" framing, not a separate algorithm."""
    scored: list[tuple[str, float]] = []
    for symbol in eligible:
        ret = trailing_return(bars_by_symbol[symbol], as_of, lookback_days)
        if ret is not None:
            scored.append((symbol, ret))
    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[1], reverse=not worst)
    chosen = scored[: min(top_n, len(scored))]
    share = 1.0 / len(chosen)
    return {symbol: share for symbol, _ in chosen}
```

Then extend `_weights_for`'s dispatch (from Task 3) to:

```python
def _weights_for(
    spec: RotationSpec, eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date
) -> dict[str, float]:
    if spec.family == ROTATION_FAMILY_EQUAL_WEIGHT:
        return weights_for_equal_weight(eligible)
    if spec.family == ROTATION_FAMILY_SECTOR_MOMENTUM:
        return weights_for_top_n_momentum(
            eligible, bars_by_symbol, as_of, spec.lookback_days, spec.top_n,
        )
    if spec.family == ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3:
        return weights_for_top_n_momentum(
            eligible, bars_by_symbol, as_of, spec.lookback_days, spec.top_n,
        )
    if spec.family == ROTATION_FAMILY_SECTOR_MEAN_REVERSION:
        return weights_for_top_n_momentum(
            eligible, bars_by_symbol, as_of, spec.lookback_days, spec.top_n, worst=True,
        )
    raise ValueError(f"no weight function wired for family {spec.family!r}")  # Tasks 5-6 extend this
```

(`_weights_for`'s 4th parameter changes from `as_of_idx: int` to
`as_of: date` here — Task 3's sketch used the index; Task 4 needs the
actual date to pass to `trailing_return`. Update Task 3's call site in
`run_portfolio_backtest`'s main loop accordingly: pass `as_of` instead
of `idx`.)

Add the two new imports (`ROTATION_FAMILY_SECTOR_MOMENTUM`,
`ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3`, `ROTATION_FAMILY_SECTOR_MEAN_
REVERSION`) to this file's existing `from prometheus.strategy.rotation_
spec import ...` line.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_portfolio_engine.py -v`
Expected: PASS (all tests from Task 3 and this task)

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/backtest/portfolio_engine.py --strict`
Expected: `Success: no issues found`

- [ ] **Step 6: Write the 3 pre-registration docs**

Create `docs/strategies/sector_momentum_rotation.md`,
`docs/strategies/relative_strength_top3.md`,
`docs/strategies/sector_mean_reversion.md` from the design doc's `#49`,
`#51`, `#52` sections respectively (same process as Task 3 Step 6).

- [ ] **Step 7: Commit**

```bash
git add prometheus/backtest/portfolio_engine.py tests/test_portfolio_engine.py docs/strategies/sector_momentum_rotation.md docs/strategies/relative_strength_top3.md docs/strategies/sector_mean_reversion.md
git commit -m "feat(backtest): cross-sectional momentum ranking primitive -- #49, #51, #52"
```

---

## Task 5: DUAL_MOMENTUM_GEM (#50)

**Files:**
- Modify: `prometheus/backtest/portfolio_engine.py`
- Create: `docs/strategies/dual_momentum_gem.md`
- Test: extend `tests/test_portfolio_engine.py`

**Interfaces:**
- Produces: `weights_for_dual_momentum_gem(eligible, bars_by_symbol,
  as_of, lookback_days) -> dict[str, float]` — Antonacci's own published
  rule: among the equity legs (every symbol in `eligible` except the
  final, defensive one — GEM's spec always has `universe = (equity_leg_
  1, equity_leg_2, defensive_leg)`, defensive leg is `spec.universe[-1]`
  by convention, stated explicitly in this family's own pre-registration
  doc so it's never ambiguous which universe position means what), pick
  whichever equity leg has the higher trailing return; if that leg's own
  trailing return is negative (absolute momentum failing), hold 100% of
  the defensive leg instead of the winning-but-still-negative equity leg.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_portfolio_engine.py`:

```python
from prometheus.backtest.portfolio_engine import weights_for_dual_momentum_gem


def test_gem_picks_stronger_positive_equity_leg() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 110.0]}),  # +10%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 103.0]}),  # +3%
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"SPY": pytest.approx(1.0)}


def test_gem_falls_back_to_defensive_when_both_equity_legs_negative() -> None:
    dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 95.0]}),   # -5%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%, worse
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"TLT": pytest.approx(1.0)}


def test_gem_missing_defensive_leg_history_returns_empty() -> None:
    # If even the defensive leg lacks lookback history, no honest
    # decision can be made this cycle -- empty (100% cash), not a crash.
    dates = [datetime(2020, 1, 1)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0]}),
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 1), lookback_days=5,
    )
    assert weights == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_portfolio_engine.py -k gem -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Implement**

Add to `prometheus/backtest/portfolio_engine.py`:

```python
def weights_for_dual_momentum_gem(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Antonacci's own published GEM rule. `eligible[-1]` is always the
    defensive leg by this family's own universe convention (stated in
    docs/strategies/dual_momentum_gem.md) -- everything before it is an
    equity leg. Absolute momentum: hold the strongest equity leg only if
    ITS OWN trailing return is positive; otherwise the defensive leg.
    Empty (100% cash) only when there isn't enough history to judge at
    all -- an honestly-skipped rebalance, not a fabricated decision."""
    if len(eligible) < 2:
        return {}
    *equity_legs, defensive_leg = eligible
    equity_returns = [
        (symbol, trailing_return(bars_by_symbol[symbol], as_of, lookback_days))
        for symbol in equity_legs
    ]
    equity_returns = [(s, r) for s, r in equity_returns if r is not None]
    defensive_return = trailing_return(bars_by_symbol[defensive_leg], as_of, lookback_days)
    if not equity_returns or defensive_return is None:
        return {}
    best_symbol, best_return = max(equity_returns, key=lambda pair: pair[1])
    if best_return > 0:
        return {best_symbol: 1.0}
    return {defensive_leg: 1.0}
```

Wire it into `_weights_for`'s dispatch:

```python
    if spec.family == ROTATION_FAMILY_DUAL_MOMENTUM_GEM:
        return weights_for_dual_momentum_gem(eligible, bars_by_symbol, as_of, spec.lookback_days)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_portfolio_engine.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/backtest/portfolio_engine.py --strict`

- [ ] **Step 6: Write the pre-registration doc**

Create `docs/strategies/dual_momentum_gem.md` from the design doc's
`#50` section — **explicitly state the universe-order convention**
(`universe = ("SPY", "EFA", "TLT")`, last position is always the
defensive leg) in this doc's Parameters section, since it's a real
implicit contract the grid generator (Task 7) and this weight function
both depend on.

- [ ] **Step 7: Commit**

```bash
git add prometheus/backtest/portfolio_engine.py tests/test_portfolio_engine.py docs/strategies/dual_momentum_gem.md
git commit -m "feat(backtest): DUAL_MOMENTUM_GEM (#50)"
```

---

## Task 6: GTAA_SMA_TIMING (#53)

**Files:**
- Modify: `prometheus/backtest/portfolio_engine.py`
- Create: `docs/strategies/gtaa_sma_timing.md`
- Test: extend `tests/test_portfolio_engine.py`

**Interfaces:**
- Produces: `weights_for_gtaa_sma(eligible, bars_by_symbol, as_of,
  lookback_days) -> dict[str, float]` — Faber's own published rule:
  each of the 5 assets independently gets an equal share (`1/5` of
  total capital, always, regardless of how many are currently "in") if
  its own close is above its own trailing `lookback_days`-bar SMA, else
  0 (that slice sits in cash — GTAA does not redistribute an out
  asset's slice to the others, per Faber's own published mechanics).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_portfolio_engine.py`:

```python
from prometheus.backtest.portfolio_engine import weights_for_gtaa_sma


def test_gtaa_sma_holds_only_assets_above_their_own_sma() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(4)]
    bars_by_symbol = {
        # SMA(3) as of day 4: mean(100,100,100)=100, close=110 -> above -> IN
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 110.0]}),
        # SMA(3) as of day 4: mean(100,100,100)=100, close=90 -> below -> OUT
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(
        ["SPY", "TLT"], bars_by_symbol, date(2020, 1, 4), lookback_days=3,
    )
    # Each asset's SLICE is always 1/N of capital -- an OUT asset's slice
    # is simply absent (cash), never redistributed to the IN asset.
    assert weights == {"SPY": pytest.approx(0.5)}


def test_gtaa_sma_all_out_returns_empty_weights() -> None:
    dates = [datetime(2020, 1, i + 1) for i in range(4)]
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(["SPY"], bars_by_symbol, date(2020, 1, 4), lookback_days=3)
    assert weights == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_portfolio_engine.py -k gtaa -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
def weights_for_gtaa_sma(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Faber's own published GTAA rule: each of len(eligible) assets
    gets a FIXED 1/N slice if its close is above its own trailing SMA,
    else that slice is simply absent (cash) -- never redistributed to
    the assets still in, unlike a ranking strategy's top-N reallocation."""
    if not eligible:
        return {}
    share = 1.0 / len(eligible)
    weights: dict[str, float] = {}
    for symbol in eligible:
        bars = bars_by_symbol[symbol]
        rows = bars.filter(pl.col("available_at") <= datetime.combine(as_of, datetime.min.time()))
        if rows.height < lookback_days:
            continue
        closes = rows["close"].to_list()
        sma = sum(closes[-lookback_days:]) / lookback_days
        if closes[-1] > sma:
            weights[symbol] = share
    return weights
```

Wire into `_weights_for`:

```python
    if spec.family == ROTATION_FAMILY_GTAA_SMA:
        return weights_for_gtaa_sma(eligible, bars_by_symbol, as_of, spec.lookback_days)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_portfolio_engine.py -v`
Expected: PASS (every test in this file, all 6 families' weight
functions now wired)

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/backtest/portfolio_engine.py --strict`

- [ ] **Step 6: Write the pre-registration doc**

Create `docs/strategies/gtaa_sma_timing.md` from the design doc's `#53`
section.

- [ ] **Step 7: Commit**

```bash
git add prometheus/backtest/portfolio_engine.py tests/test_portfolio_engine.py docs/strategies/gtaa_sma_timing.md
git commit -m "feat(backtest): GTAA_SMA_TIMING (#53) -- all 6 rotation families now implemented"
```

---

## Task 7: grid generators for all 6 families

**Files:**
- Create: `prometheus/research/rotation_generate.py`
- Test: `tests/test_rotation_generate.py` (new)

**Interfaces:**
- Consumes: `RotationSpec`, `ROTATION_FAMILY_*` constants (Task 1).
- Produces: `generate_equal_weight_grid() -> list[RotationSpec]`,
  `generate_sector_momentum_grid() -> list[RotationSpec]`,
  `generate_relative_strength_grid() -> list[RotationSpec]`,
  `generate_sector_mean_reversion_grid() -> list[RotationSpec]`,
  `generate_dual_momentum_grid() -> list[RotationSpec]`,
  `generate_gtaa_grid() -> list[RotationSpec]`,
  `ROTATION_GRID_GENERATORS: tuple[Callable[[], list[RotationSpec]], ...]`
  (all 6, for `worker.py`'s Task 12 wiring to iterate).

Exact fixed values, copied from the design doc — no other values are
valid without a new pre-registration doc first:

| Function | Universe | Grid |
|---|---|---|
| `generate_equal_weight_grid` | 11 SPDR sectors | 1 spec: `rebalance_frequency_days=21` |
| `generate_sector_momentum_grid` | 11 SPDR sectors | `lookback_days in {63,126,252}` × `top_n in {3,5}` = 6 specs, `rebalance_frequency_days=21` |
| `generate_relative_strength_grid` | 11 SPDR sectors | `lookback_days in {63,126,252}` × `top_n=3` (fixed) = 3 specs, `rebalance_frequency_days=21` |
| `generate_sector_mean_reversion_grid` | 11 SPDR sectors | `lookback_days in {21,63}` × `top_n in {3,5}` = 4 specs, `rebalance_frequency_days=21` |
| `generate_dual_momentum_grid` | `("SPY","EFA","TLT")` | 1 spec: `lookback_days=252`, `rebalance_frequency_days=21` |
| `generate_gtaa_grid` | `("SPY","EFA","IEF","VNQ","GLD")` | 1 spec: `lookback_days=210`, `rebalance_frequency_days=21` |

`expected_horizon=21` for every spec in every grid (one rebalance
cycle, per each family's own design-doc entry).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rotation_generate.py`:

```python
"""tests/test_rotation_generate.py"""
from __future__ import annotations

from prometheus.research.rotation_generate import (
    ROTATION_GRID_GENERATORS,
    generate_dual_momentum_grid,
    generate_equal_weight_grid,
    generate_gtaa_grid,
    generate_relative_strength_grid,
    generate_sector_mean_reversion_grid,
    generate_sector_momentum_grid,
)

_SECTORS = {"XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"}


def test_equal_weight_grid_is_one_spec_over_11_sectors() -> None:
    grid = generate_equal_weight_grid()
    assert len(grid) == 1
    assert set(grid[0].universe) == _SECTORS
    assert grid[0].rebalance_frequency_days == 21


def test_sector_momentum_grid_is_6_specs() -> None:
    grid = generate_sector_momentum_grid()
    assert len(grid) == 6
    assert {s.lookback_days for s in grid} == {63, 126, 252}
    assert {s.top_n for s in grid} == {3, 5}


def test_relative_strength_grid_fixes_top_n_at_3() -> None:
    grid = generate_relative_strength_grid()
    assert len(grid) == 3
    assert all(s.top_n == 3 for s in grid)


def test_sector_mean_reversion_grid_is_4_specs() -> None:
    grid = generate_sector_mean_reversion_grid()
    assert len(grid) == 4
    assert {s.lookback_days for s in grid} == {21, 63}


def test_dual_momentum_grid_is_one_spec_over_gem_universe() -> None:
    grid = generate_dual_momentum_grid()
    assert len(grid) == 1
    assert grid[0].universe == ("SPY", "EFA", "TLT")
    assert grid[0].lookback_days == 252


def test_gtaa_grid_is_one_spec_over_5_asset_universe() -> None:
    grid = generate_gtaa_grid()
    assert len(grid) == 1
    assert grid[0].universe == ("SPY", "EFA", "IEF", "VNQ", "GLD")
    assert grid[0].lookback_days == 210


def test_all_6_generators_registered() -> None:
    assert len(ROTATION_GRID_GENERATORS) == 6
    total_specs = sum(len(gen()) for gen in ROTATION_GRID_GENERATORS)
    assert total_specs == 1 + 6 + 3 + 4 + 1 + 1  # 16 total
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_rotation_generate.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

Create `prometheus/research/rotation_generate.py`:

```python
"""Grid generators for the 6 cross-sectional rotation families --
fixed, cited parameter values, pre-registered in docs/strategies/ before
this module existed. See docs/superpowers/specs/2026-09-21-cross-
sectional-rotation-design.md for the citation behind every value here.
"""
from __future__ import annotations

from collections.abc import Callable

from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

_SECTOR_UNIVERSE = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)
_GEM_UNIVERSE = ("SPY", "EFA", "TLT")  # last position is always the defensive leg
_GTAA_UNIVERSE = ("SPY", "EFA", "IEF", "VNQ", "GLD")

_MONTHLY = 21  # trading days -- this batch's own convention, and every
               # cited source's (Antonacci, Faber, Keller) own published cadence


def generate_equal_weight_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_EQUAL_WEIGHT,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


def generate_sector_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MOMENTUM,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126, 252)
        for top_n in (3, 5)
    ]


def generate_relative_strength_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=3,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (63, 126, 252)
    ]


def generate_sector_mean_reversion_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
            universe=_SECTOR_UNIVERSE,
            timeframe="1d",
            lookback_days=lookback,
            top_n=top_n,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
        for lookback in (21, 63)
        for top_n in (3, 5)
    ]


def generate_dual_momentum_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
            universe=_GEM_UNIVERSE,
            timeframe="1d",
            lookback_days=252,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


def generate_gtaa_grid() -> list[RotationSpec]:
    return [
        RotationSpec(
            family=ROTATION_FAMILY_GTAA_SMA,
            universe=_GTAA_UNIVERSE,
            timeframe="1d",
            lookback_days=210,
            rebalance_frequency_days=_MONTHLY,
            expected_horizon=_MONTHLY,
        )
    ]


ROTATION_GRID_GENERATORS: tuple[Callable[[], list[RotationSpec]], ...] = (
    generate_equal_weight_grid,
    generate_sector_momentum_grid,
    generate_relative_strength_grid,
    generate_sector_mean_reversion_grid,
    generate_dual_momentum_grid,
    generate_gtaa_grid,
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_rotation_generate.py -v`

- [ ] **Step 5: Type-check**

Run: `mypy prometheus/research/rotation_generate.py --strict`

- [ ] **Step 6: Commit**

```bash
git add prometheus/research/rotation_generate.py tests/test_rotation_generate.py
git commit -m "feat(research): grid generators for all 6 rotation families"
```

---

## Task 8: `experiments/runner.py` dispatch — `run_one`/`enqueue_specs` generalized

**Files:**
- Modify: `prometheus/experiments/runner.py`
- Test: `tests/test_runner.py` or wherever `run_one`/`enqueue_specs` are
  currently tested (search for it; extend, don't duplicate the file)

**Interfaces:**
- Consumes: `RotationSpec` (Task 1), `run_portfolio_backtest` (Task 3),
  `membership_windows` (Task 2).
- Produces: `run_one` and `enqueue_specs` accept `StrategySpec |
  RotationSpec`. New: `enqueue_rotation_grid(family_generator, days, *,
  priority, expected_information_value, estimated_cost, max_attempts) ->
  list[str]` (thin wrapper, same shape as `enqueue_grid`/`enqueue_
  baseline_grid`, but takes a grid-generator function directly since
  rotation grids take no `(symbol, timeframe)` args unlike classic
  grids).

**Read `prometheus/experiments/runner.py` lines 1-260 (`run_one`) and
597-670 (`enqueue_specs`/`enqueue_grid`/`enqueue_baseline_grid`) and
`prometheus/experiments/queue.py`'s `Job`/`_run_job` (in this same file,
around line 671) before starting — this task edits code that already
exists, and the exact current bodies must be read, not guessed.**

Key changes:

1. `enqueue_specs`'s `specs` parameter type widens to `list[StrategySpec
   | RotationSpec]`. Inside its loop, when building the job payload, add
   `"spec_kind": "rotation" if isinstance(spec, RotationSpec) else
   "strategy"` alongside the existing `"spec": spec.model_dump()`.

2. `_run_job` (around line 671-698): currently does
   `spec = StrategySpec.model_validate(job.payload["spec"])`
   unconditionally. Change to:

```python
spec_kind = job.payload.get("spec_kind", "strategy")
if spec_kind == "rotation":
    spec: StrategySpec | RotationSpec = RotationSpec.model_validate(job.payload["spec"])
else:
    spec = StrategySpec.model_validate(job.payload["spec"])
```

3. `run_one`'s body needs 4 small generalizations (its overall
   structure — build Experiment/Result/Decision rows — stays identical
   for both spec types):
   - `load_point_in_time(session, [spec.symbol], ...)` becomes
     `load_point_in_time(session, [spec.symbol] if isinstance(spec, StrategySpec) else list(spec.universe), spec.timeframe, start, end)`.
   - `derive_seed(spec.symbol, spec.timeframe, spec.config_hash())`
     becomes `derive_seed(*(sorted([spec.symbol]) if isinstance(spec, StrategySpec) else sorted(spec.universe)), spec.timeframe, spec.config_hash())`.
   - `compute_benchmark_curve(pit, [spec.symbol], end, cost_model=cost_model)`
     becomes the same symbol-list generalization.
   - `run_backtest(pit, spec, end, cost_model=cost_model, benchmark_result=benchmark_result)`
     becomes: if `isinstance(spec, RotationSpec)`, first fetch
     `membership = await membership_windows(session, "etf", list(spec.universe))`
     then call `run_portfolio_backtest(pit, spec, membership, end, cost_model=cost_model, benchmark_result=benchmark_result)`;
     else call `run_backtest` as today.
   - Type signature: `run_one(session, spec: StrategySpec | RotationSpec, start, end, *, ...)`.

4. New thin wrapper, added near `enqueue_baseline_grid`:

```python
async def enqueue_rotation_grid(
    generate_grid_fn: Callable[[], list[RotationSpec]], days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Enqueues one rotation family's own grid -- no (symbol, timeframe)
    args, unlike enqueue_grid/enqueue_baseline_grid, because a
    RotationSpec's universe is fixed by its own grid generator, not
    supplied per-call the way a single-symbol grid needs a symbol."""
    return await enqueue_specs(
        "", "", generate_grid_fn(), days,  # symbol/timeframe params are unused inside enqueue_specs today -- verify this still holds after reading its current body
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )
```

**Verify the claim in that comment** by reading `enqueue_specs`'s
current body (line 597 onward) before relying on it — if a later change
made `symbol`/`timeframe` actually used inside `enqueue_specs`, this
wrapper needs adjusting (e.g. `enqueue_specs` may need its own
`symbol`/`timeframe` parameters made `str | None = None` instead of
passing empty strings).

- [ ] **Step 1: Write the failing test**

Find or create the test file covering `run_one`/`enqueue_specs` (search
`tests/` for `run_one(` to find it) and add:

```python
@pytest.mark.db
async def test_run_one_accepts_rotation_spec(db_session) -> None:
    # Adjust fixture/setup to match this file's existing convention for
    # seeding real OHLCV bars + universe_membership rows before calling
    # run_one -- read an existing StrategySpec-based test in this same
    # file first and mirror its data setup for the GEM universe
    # (SPY, EFA, TLT) instead of one crypto symbol.
    from prometheus.research.rotation_generate import generate_dual_momentum_grid
    spec = generate_dual_momentum_grid()[0]
    experiment_id = await run_one(db_session, spec, start, end)
    assert experiment_id is not None
```

(Exact fixture/setup code depends on how this project's existing DB
tests seed bars — read a neighboring `StrategySpec`-based `run_one` test
in the same file and copy its data-seeding pattern, substituting the
GEM universe's 3 symbols for its one crypto symbol.)

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — either an `isinstance` check missing or `spec.symbol`
raising `AttributeError` on a `RotationSpec` (which has no `symbol`
field).

- [ ] **Step 3: Apply the 4 generalizations + new wrapper described above**

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_runner.py -k rotation -v` (or wherever the test
lives)

- [ ] **Step 5: Run the FULL existing runner test suite to confirm no regression**

Run: `pytest tests/ -q -k "runner or run_one or enqueue"`
Expected: every pre-existing `StrategySpec`-path test still passes
unchanged — this task's generalizations must be purely additive.

- [ ] **Step 6: Type-check**

Run: `mypy prometheus/experiments/runner.py --strict`

- [ ] **Step 7: Commit**

```bash
git add prometheus/experiments/runner.py tests/test_runner.py
git commit -m "feat(experiments): runner.py dispatch for RotationSpec"
```

---

## Task 9: `validate_rotation_specs` + `_validate_one_spec` generalized for honest-None decay/IC

**Files:**
- Modify: `prometheus/experiments/runner.py`
- Test: extend the same test file as Task 8

**Interfaces:**
- Consumes: `RotationSpec`, `run_portfolio_backtest`, `membership_windows`.
- Produces: `_validate_one_spec` accepts a new `decay_profile: DecayProfile`
  keyword parameter instead of computing it via `compute_decay(bars, spec)`
  internally (its only spec-type-specific line). New:
  `validate_rotation_specs(session, specs: list[RotationSpec], days: int)
  -> list[str]` — same overall shape as `validate_specs` (PBO across the
  batch, clustering, per-spec scoring/decision/ValidationResult write),
  but with no `symbol`/`timeframe` top-level params (each `RotationSpec`
  already carries its own universe) and `information_coefficient`/`icir`/
  decay honestly `None`.

**Read `_validate_one_spec` (runner.py, around line 481-591) and
`validate_specs` (line 294-452) in full before starting.**

1. In `_validate_one_spec`, replace:

```python
decay_profile = compute_decay(bars, spec)
```

with a parameter:

```python
async def _validate_one_spec(
    session: AsyncSession,
    *,
    spec: StrategySpec | RotationSpec,
    result: Any,
    validation_metrics: Any,
    decay_profile: DecayProfile,
    bars: pl.DataFrame | None,
    ...
) -> None:
```

(`bars` becomes `pl.DataFrame | None` since `validate_rotation_specs`
has no natural single "bars" — see point 3 below for what it passes for
the informational `current_regime` label instead. `decay_profile` is
computed by each caller now, not inside this function.)

2. In `validate_specs` (the existing `StrategySpec` path), add
   `decay_profile = compute_decay(bars, spec)` at its own call site
   (right before it currently calls `_validate_one_spec`) and pass it
   through as the new keyword arg — this is the ONLY change
   `validate_specs` itself needs.

3. Add `validate_rotation_specs`:

```python
from prometheus.validation.decay import DecayProfile

_NULL_DECAY_PROFILE_TEMPLATE = {
    "ic_by_horizon": {}, "claimed_horizon_ic": None,
    "claimed_horizon_p_value": None, "has_power_at_claimed_horizon": None,
}


def _null_decay_profile(spec: RotationSpec) -> DecayProfile:
    """RotationSpec's information_coefficient has no defined meaning
    (compute_decay calls signal_for(bars, spec), a single-symbol-signal
    concept a portfolio weight vector doesn't reduce to) -- honestly
    None throughout, matching this codebase's existing 'absent beats
    fabricated' precedent (excess_sharpe below cpz-quant's 30-observation
    floor), not a silently-invented translation. Documented as a known
    gap in docs/DEFERRED.md once this ships."""
    return DecayProfile(claimed_horizon=spec.expected_horizon, **_NULL_DECAY_PROFILE_TEMPLATE)


async def validate_rotation_specs(
    session: AsyncSession, specs: list[RotationSpec], days: int
) -> list[str]:
    """Same re-scoring shape as validate_specs (PBO across the batch,
    correlation clustering, per-spec scoring/decision), but for
    RotationSpec: no top-level symbol/timeframe (each spec carries its
    own universe), and information_coefficient/icir/decay honestly None
    -- see _null_decay_profile."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    cost_config, _cost_config_hash = load_cost_config()
    cost_model = make_cost_model(cost_config)

    per_spec: list[tuple[RotationSpec, Any]] = []
    for spec in specs:
        try:
            all_symbols = list(spec.universe)
            pit, _data_version_hash = await load_point_in_time(session, all_symbols, spec.timeframe, start, end)
            membership = await membership_windows(session, "etf", all_symbols)
            benchmark_result = compute_benchmark_curve(pit, all_symbols, end, cost_model=cost_model)
            result = run_portfolio_backtest(
                pit, spec, membership, end, cost_model=cost_model, benchmark_result=benchmark_result
            )
        except ValueError:
            continue
        per_spec.append((spec, result))

    if not per_spec:
        return []

    min_len = min(len(result.equity_curve) for _, result in per_spec)
    n_splits = _pbo_n_splits(min_len - 1)
    pbo_value: float | None = None
    if n_splits is not None and len(per_spec) >= 2:
        returns_columns = []
        for _, result in per_spec:
            equities = [equity for _, equity in result.equity_curve[-min_len:]]
            returns_columns.append([equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))])
        returns_matrix = np.array(returns_columns).T
        pbo_result = probability_of_backtest_overfitting(returns_matrix, n_splits=n_splits)
        pbo_value = pbo_result.pbo

    clusters = cluster_by_correlation([(spec, result.equity_curve) for spec, result in per_spec])
    cluster_info_by_hash: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        cluster_key = cluster.representative.config_hash()
        for member in cluster.members:
            cluster_info_by_hash[member.config_hash()] = {
                "cluster_key": cluster_key,
                "cluster_size": len(cluster.members),
                "is_representative": member.config_hash() == cluster_key,
                "mean_pairwise_correlation": cluster.mean_pairwise_correlation,
            }

    from prometheus.validation.metrics import ValidationMetrics  # local import mirrors compute_metrics' own return type

    validated_specs: list[tuple[RotationSpec, Any, Any]] = []
    trial_sharpes: list[float] = []
    for spec, result in per_spec:
        equity_values = [equity for _, equity in result.equity_curve]
        risk = compute_risk_analytics(equity_values) if len(equity_values) >= 2 else None
        validation_metrics = ValidationMetrics(
            risk=risk, turnover=result.turnover, hit_rate=None,
            information_coefficient=None, icir=None,
        )
        validated_specs.append((spec, result, validation_metrics))
        if risk is not None and risk.sharpe is not None:
            trial_sharpes.append(risk.sharpe)

    n_trials_for_deflation = max(await trials_to_date(session), len(per_spec))

    experiment_ids: list[str] = []
    for spec, result, validation_metrics in validated_specs:
        row = (
            await session.execute(_SELECT_LATEST_EXPERIMENT_FOR_SPEC, {"config_hash": spec.config_hash()})
        ).first()
        if row is None:
            continue
        experiment_id, strategy_id = row.id, row.strategy_id
        try:
            await _validate_one_spec(
                session, spec=spec, result=result, validation_metrics=validation_metrics,
                decay_profile=_null_decay_profile(spec), bars=None,
                experiment_id=experiment_id, strategy_id=strategy_id,
                pbo_value=pbo_value, trial_sharpes=trial_sharpes,
                n_trials_for_deflation=n_trials_for_deflation,
                current_regime="UNKNOWN",  # honest: no single symbol's bars to classify a regime from
                cluster_info=cluster_info_by_hash.get(spec.config_hash()),
            )
        except Exception as exc:
            print(f"validate_rotation_specs: skipping {spec.config_hash()}: {exc!r}")
            continue
        experiment_ids.append(experiment_id)

    await elect_champions(session)
    await session.commit()
    return experiment_ids
```

**Note for the implementer:** `ValidationMetrics`'s exact field list and
`compute_risk_analytics`'s import path must be confirmed by reading
`prometheus/validation/metrics.py` in full before writing this — the
sketch above assumes `ValidationMetrics(risk, turnover, hit_rate,
information_coefficient, icir)` matches its real dataclass fields;
adjust if it doesn't (e.g. if `hit_rate` isn't `Optional`, computing a
real `hit_rate(equity_curve)` — imported from the same metrics module —
instead of `None` is a one-line fix, since hit rate IS just an equity
curve property, not a single-symbol-signal concept like IC).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.db
async def test_validate_rotation_specs_writes_validation_result_with_null_ic(db_session) -> None:
    # Seed real bars for the GEM universe (SPY, EFA, TLT) + run run_one
    # first so an Experiment row exists to attach to (validate_* never
    # creates Experiments itself, same as validate_specs).
    ...
    experiment_ids = await validate_rotation_specs(db_session, [spec], days=800)
    assert experiment_ids
    row = await db_session.execute(
        select(ValidationResult).where(ValidationResult.experiment_id == experiment_ids[0])
    )
    validation_result = row.scalar_one()
    assert validation_result.metrics["information_coefficient"] is None
    assert validation_result.metrics["icir"] is None
```

- [ ] **Step 2: Run to verify failure, Step 3: implement (above), Step 4: run to verify pass**

- [ ] **Step 5: Run the full existing validate_specs test suite to confirm no regression**

Run: `pytest tests/ -q -k "validate"`

- [ ] **Step 6: Type-check**

Run: `mypy prometheus/experiments/runner.py --strict`

- [ ] **Step 7: Add the `docs/DEFERRED.md` entry for the known IC/ICIR/decay gap**

Append a new entry under whatever section covers validation
completeness (search `docs/DEFERRED.md` for `information_coefficient` or
the PROMPT 5 section header):

```markdown
- **`RotationSpec`'s information_coefficient/icir/decay are always
  `None`** — `information_coefficient()`/`compute_decay()`
  (`validation/metrics.py`, `validation/decay.py`) call
  `signal_for(bars, spec)`, a single-symbol-signal concept with no
  defined multi-asset-weight-vector translation this project has a
  citation for. `validate_rotation_specs` passes a null `DecayProfile`
  and `information_coefficient=None`/`icir=None` rather than inventing
  one. Doesn't block scoring (`ScoreInputs` doesn't require them).
  **Trigger:** a real, cited definition of IC for a portfolio weight
  vector (e.g. against each rebalance's realized forward portfolio
  return) — no source consulted for this batch defines one.
```

- [ ] **Step 8: Commit**

```bash
git add prometheus/experiments/runner.py tests/test_runner.py docs/DEFERRED.md
git commit -m "feat(experiments): validate_rotation_specs with honest null IC/decay"
```

---

## Task 10: frontend — verify no `spec.symbol` assumption breaks

**Files:**
- Investigate: `frontend/src/dashboard/` (all files)
- Modify: whichever component(s) the investigation finds

**Interfaces:** none new — this task is verify-then-patch, not a new
feature.

- [ ] **Step 1: Search for the assumption**

Run: `grep -rn "\.spec\.symbol\|spec\[.symbol.\]" frontend/src/`

- [ ] **Step 2: For each match found**

Read the component. If it renders `strategy.spec.symbol` directly for
display (e.g. a strategy card's subtitle), add a fallback:

```typescript
const displaySymbol = strategy.spec.symbol ?? (strategy.spec.universe as string[] | undefined)?.join(", ") ?? "—";
```

(Adjust to match this component's actual existing TypeScript patterns —
read its neighboring code for the established style before writing this.)

- [ ] **Step 3: If no matches found**

Document in this task's own commit message that the search was run and
found nothing — this is a valid, complete outcome, not a step to skip.

- [ ] **Step 4: Manually verify in a running dev instance**

Run: `cd frontend && npm run dev`, open the dashboard, confirm no
strategy card shows literal `"undefined"` or throws a console error.
(If no rotation strategies have run yet in this dev environment, this
step confirms existing `StrategySpec`-based cards still render
correctly after the fallback change — a `RotationSpec` card can't be
manually verified until Task 12's worker wiring has actually produced one.)

- [ ] **Step 5: `npx tsc --noEmit`**

Expected: no new type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "fix(frontend): render spec.universe fallback for symbol-less specs"
```

(If Step 3's outcome was "no matches," commit nothing for this task —
note it as complete-with-no-change in the plan's tracking, not a
skipped task.)

---

## Task 11: worker.py wiring — enqueue + validate the rotation grids each cycle

**Files:**
- Modify: `prometheus/worker.py`
- Test: none new (this wires existing, already-tested functions into
  the existing cadence-gated concern functions; covered by whatever
  integration test already exercises `_run_research`, if one exists —
  otherwise this task's own manual verification step is the check)

**Interfaces:**
- Consumes: `ROTATION_GRID_GENERATORS` (Task 7), `enqueue_rotation_grid`
  (Task 8), `validate_rotation_specs` (Task 9).

**Read `prometheus/worker.py`'s `_run_research` function (around line
468-514) in full before starting.** Rotation strategies use a FIXED
universe per family (not one symbol per iteration), so this wiring goes
OUTSIDE the existing `for symbol in symbols:` loop — `symbols` there
comes from `load_universe_symbols()`, which is the crypto universe
(`config/universe.yaml`), not the ETF universe rotation strategies need.

Add, inside `_run_research()`, after the existing `for symbol in
symbols:` loop and before `ran = await drain_queue()`:

```python
    for generate_rotation_grid in ROTATION_GRID_GENERATORS:
        await enqueue_rotation_grid(
            generate_rotation_grid, _GRID_LOOKBACK_DAYS,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )
```

And inside the validation block (the `async with get_session() as
session:` block that currently loops `for symbol in symbols:` calling
`validate_baseline_grid`/`validate_specs`), add after that loop:

```python
        for generate_rotation_grid in ROTATION_GRID_GENERATORS:
            validated.extend(
                await validate_rotation_specs(session, generate_rotation_grid(), _GRID_LOOKBACK_DAYS)
            )
```

Add the new imports at the top of `worker.py`:

```python
from prometheus.experiments.runner import enqueue_rotation_grid, validate_rotation_specs
from prometheus.research.rotation_generate import ROTATION_GRID_GENERATORS
```

- [ ] **Step 1: Confirm ETF bars are actually ingested in production**

This wiring is only useful once real ETF OHLCV data exists in
`ohlcv_bars` for the sector/GEM/GTAA universes. Check whether the
existing ETF ingestion pipeline (from the earlier "multi-asset ETF
provider" work) already runs on a schedule in `worker.py`, or only via a
manual backfill script. If only manual: **stop and flag this to the
user** before wiring rotation validation in — enqueueing rotation grids
against a database with no ETF bars will make every rotation `run_one`
raise `ValueError: not enough bars`, caught and classified
`INSUFFICIENT_DATA` (harmless, but silently pointless every single
cycle) rather than ever producing a real result. Do not silently work
around missing data by lowering `_GRID_LOOKBACK_DAYS` or fabricating a
smaller warmup requirement — either the data exists or this step
surfaces that it doesn't, honestly, per the same "don't invent
thresholds" rule that governs everything else in this project.

- [ ] **Step 2: Apply the wiring above (only if Step 1 confirms real ETF data is ingested)**

- [ ] **Step 3: Manually verify one cycle locally**

Run: `python -m prometheus.worker` against a real (dev) database with
ETF bars ingested. Confirm no unhandled exception, and check
`strategies` table afterward for new rows with `family` in
`ROTATION_FAMILIES`.

- [ ] **Step 4: Type-check**

Run: `mypy prometheus/worker.py --strict`

- [ ] **Step 5: Run the full non-db test suite**

Run: `pytest tests/ -q -m "not db"`
Expected: same pass count as before this task, plus everything added in
Tasks 1-10 — no regressions.

- [ ] **Step 6: Commit**

```bash
git add prometheus/worker.py
git commit -m "feat(worker): wire cross-sectional rotation grids into research/validation cadence"
```

---

## Final Verification

- [ ] Full suite: `pytest tests/ -q -m "not db"` — 0 failures.
- [ ] Full suite including DB tests, against a real dev Postgres:
  `pytest tests/ -q` — 0 failures.
- [ ] `mypy prometheus/ --strict` — only the pre-existing, unrelated
  `prometheus/data/loaders.py:36: pl.PolarsDataType` error, nothing new.
- [ ] `cd frontend && npx tsc --noEmit && npm run build` — clean.
- [ ] Every one of the 6 rotation families has its own
  `docs/strategies/<family>.md`, written before this plan's own first
  backtest of that family ran (true by construction, since each task
  above writes the doc in the same commit as the family's own code).
- [ ] `docs/DEFERRED.md` has the new IC/ICIR/decay entry from Task 9.
- [ ] Every parameter value in every grid generator (Task 7) traces to
  either a cited source or this batch's own stated convention — spot-
  check against `docs/superpowers/specs/2026-09-21-cross-sectional-
  rotation-design.md`'s Family definitions section.

## Self-Review Notes (completed during plan authoring)

1. **Spec coverage:** all 6 families (Tasks 3-6), grid generators (Task
   7), runner dispatch (Task 8), validation (Task 9), frontend check
   (Task 10), worker wiring (Task 11), the pre-existing `_FAMILY_RE`
   bug caught during Task 1 authoring. The design doc's "Frontend —
   verify, don't assume" and "Testing plan" sections both map directly
   to Task 10 and the per-task test steps respectively.
2. **Placeholder scan:** no TBD/TODO. Task 11 Step 1 is a genuine
   stop-and-check gate (ETF ingestion cadence), not a placeholder —
   it has a concrete decision rule (data exists → proceed; data
   doesn't → stop and flag), matching this project's existing
   "don't invent thresholds" discipline rather than skipping the check.
3. **Type consistency:** `Membership` (`dict[str, tuple[date, date |
   None]]`) is defined once in Task 2/3 and reused identically through
   Tasks 3, 8, 9. `RotationSpec`, `ROTATION_FAMILY_*` constants, and
   `run_portfolio_backtest`'s signature are each defined exactly once
   (Tasks 1, 3) and referenced identically in every later task.

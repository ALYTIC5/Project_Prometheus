# Paper Trading (PROMPT 8 — Harbour) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the paper-trading layer — CHAMPION strategies trade €1,000 of paper capital each against Binance's real spot testnet, get reconciled against their own backtest predictions and against buy-and-hold, and get quarantined with a recorded recalibration proposal when reality diverges from the cost model.

**Architecture:** Five new modules under `prometheus/paper/` (broker, execution, reconciliation, divergence, duration) plus one new function in `prometheus/validation/multiple_testing.py`. The worker's single Railway cron tightens from `*/30 * * * *` to `*/15 * * * *`; a new `worker_cadence` table lets three concerns (ingest/hourly, research/30min, paper/15min) run from that one entrypoint at three different rates, so this stays one scheduled worker, not a new service. No websockets, no persistent connections — every paper-trading action is one bounded REST pass per tick, matching how `worker.py` already runs.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x async (asyncpg), Polars, ccxt 4.5.77 (already a pinned dependency), pytest + pytest-asyncio (`asyncio_mode = "auto"`, no decorator needed), alembic.

**Spec:** `docs/superpowers/specs/2026-09-17-paper-trading-design.md` — read it alongside this plan; this plan implements it task-by-task and does not repeat its rationale.

## Global Constraints

- Law 5 (absolute): no code path here may ever submit a real-money order. `paper/broker.py` asserts testnet at construction and raises if it can't confirm it.
- Law 4: order sizing reads `prometheus.core.config.RISK_LIMITS` (`MAX_POSITION_PCT`, `MAX_GROSS_EXPOSURE_PCT`, `MAX_LEVERAGE`) and never mutates it.
- Law 8: every paper P&L comparison is against a €1,000 buy-and-hold over the identical window, via `backtest/benchmark.py::compute_benchmark_curve` — no separate benchmark math.
- Law 6: `paper_findings` is append-only (same trigger-set treatment as `experiments`/`results`/`decisions`); `paper_orders` and `worker_cadence` are mutable current-state tables, same exemption `strategies.status` and `jobs` already have.
- Only `CHAMPION` strategies board a ship (per `research/population.py::elect_champions`, already called from `experiments/runner.py:419` — nothing to add there).
- Capital per boarded strategy is exactly `backtest.engine.STARTING_CAPITAL` (1000.0) — reuse the constant, never a new literal.
- The champion's trading decision uses `signal_for()` on 1d bars, identical to the backtest — never recomputed on a shorter bar.
- No invented numeric thresholds: the divergence materiality check reuses the existing z=1.96 convention (`tests/test_null_strategies.py`, `validation/decay.py`); `paper/duration.py` uses Bailey & López de Prado's Minimum Track Record Length, not an invented sample-size number.
- mypy strict applies to `prometheus/validation/` (existing) — this plan does not add `prometheus/paper/` to the strict list (matching `prometheus/experiments/`, `prometheus/research/`, which are not strict either); still fully type-annotated, just not mypy-strict-gated.
- Next alembic revision is `0012` (down_revision `0011`).

---

## Task 1: Migration 0012 — `paper_orders`, `paper_findings`, `worker_cadence`

**Files:**
- Create: `alembic/versions/0012_paper_trading.py`
- Modify: `prometheus/core/db.py` (add `PaperOrder`, `PaperFinding`, `WorkerCadence` ORM classes after `ComponentRegistry`)
- Modify: `prometheus/core/ids.py` (add `next_paper_order_id`)
- Test: `tests/test_paper_ids.py`

**Interfaces:**
- Produces: `prometheus.core.ids.next_paper_order_id(day: date | None = None) -> str` (format `PAPER-YYYYMMDD-NNNNNN`, same pattern as `next_job_id`). ORM classes `PaperOrder`, `PaperFinding`, `WorkerCadence` (see below) for later tasks to import.

- [ ] **Step 1: Write the failing test for `next_paper_order_id`**

```python
# tests/test_paper_ids.py
import re
from datetime import date

import pytest

from prometheus.core.ids import next_paper_order_id

pytestmark = pytest.mark.db


async def test_next_paper_order_id_format(db_engine):
    order_id = await next_paper_order_id(day=date(2026, 9, 17))
    assert re.match(r"^PAPER-20260917-\d{6}$", order_id)


async def test_next_paper_order_id_increments(db_engine):
    first = await next_paper_order_id(day=date(2026, 9, 18))
    second = await next_paper_order_id(day=date(2026, 9, 18))
    assert first != second
```

Check `tests/conftest.py` and any existing `db_engine`/`TEST_DATABASE_URL` fixture used by `tests/test_ablation_placebo.py` — if no shared fixture exists yet, mark this test the same way that file does:

```python
pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0012 applied)",
    ),
]
```

and drop the `db_engine` fixture argument, calling `next_paper_order_id` directly (it opens its own engine via `core.db.get_engine()`, same as `next_job_id`) after setting `os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]` at module load, matching `test_ablation_placebo.py`'s exact setup. Copy that file's setup block verbatim rather than inventing a new pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_ids.py -v`
Expected: FAIL — `ImportError: cannot import name 'next_paper_order_id'`

- [ ] **Step 3: Add `next_paper_order_id` to `prometheus/core/ids.py`**

Add after `next_job_id`:

```python
PAPER_ORDER_ID_RE = re.compile(r"^PAPER-\d{8}-\d{6}$")


async def next_paper_order_id(day: date | None = None) -> str:
    """PAPER-YYYYMMDD-NNNNNN, same per-day scoping and 6-digit headroom
    as next_job_id() -- a live champion polling every 15 minutes can
    plausibly submit or re-check many orders a day."""
    resolved_day = day if day is not None else datetime.now(UTC).date()
    scope = f"paper_order:{resolved_day:%Y%m%d}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    if n > 999_999:
        raise IdSequenceExhausted(f"paper order id sequence exhausted for {resolved_day:%Y%m%d}")
    return f"PAPER-{resolved_day:%Y%m%d}-{n:06d}"
```

Add `PAPER_ORDER_ID_RE` next to the other `*_ID_RE` constants near the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_ids.py -v`
Expected: PASS (or SKIPPED if `TEST_DATABASE_URL` is not set locally — that's acceptable for this step; Task 11 runs the full suite against a real database).

- [ ] **Step 5: Write the migration**

```python
# alembic/versions/0012_paper_trading.py
"""paper_orders + paper_findings + worker_cadence -- PROMPT 8's Harbour

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-17

`paper_orders`: mutable current-state table, same exemption as
`strategies.status`/`jobs` -- a fill UPDATEs the same row, it is not an
event log.

`paper_findings`: INSERT-only by convention, same precedent as
`research_violations` (migration 0008) and `ablation_trials`
(migration 0011) -- a measurement record, not a decision history, so
not added to Law 6's append-only trigger set (matches those two).
Column names (`finding_type`, `detail`, `detected_at`) deliberately
mirror `research_violations`'s existing shape rather than inventing new
names for the same concept.

`worker_cadence`: scheduling state for worker.py's cadence-gated
concerns (ingest hourly / research 30min / paper 15min from one
tightened */15 cron) -- mutable, like strategies.status, not a log.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("strategy_id", sa.String(16), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("exchange_order_id", sa.String(64), nullable=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric(28, 8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="SUBMITTED"),
        sa.Column("expected_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("expected_qty", sa.Numeric(28, 8), nullable=False),
        sa.Column("filled_qty", sa.Numeric(28, 8), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_paper_orders_strategy_id", "paper_orders", ["strategy_id"])
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])

    op.create_table(
        "paper_findings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(16), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("finding_type", sa.String(32), nullable=False),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_paper_findings_strategy_id", "paper_findings", ["strategy_id"])

    op.create_table(
        "worker_cadence",
        sa.Column("concern", sa.String(16), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_cadence")
    op.drop_index("ix_paper_findings_strategy_id", table_name="paper_findings")
    op.drop_table("paper_findings")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_strategy_id", table_name="paper_orders")
    op.drop_table("paper_orders")
```

Note the added `event_time` column (not in the spec's SQL sketch): it records which bar's close the decision was based on — `paper/execution.py` (Task 6) needs it to build the deterministic `client_order_id` (`sha256(strategy_id | event_time | side)`), and `paper/reconciliation.py` (Task 7) needs it to find the matching backtest prediction for that exact bar. Recorded here since the spec's data model section didn't spell out this column but Task 6/7 both depend on it existing.

- [ ] **Step 6: Add ORM classes to `prometheus/core/db.py`**

Add after the `ComponentRegistry` class (end of file), following the exact style of `Strategy`/`AblationTrialRow`:

```python
class PaperOrder(Base):
    """Mutable current-state table -- a fill UPDATEs this row, it is not
    an event log (same exemption as Strategy.status/Job)."""

    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    client_order_id: Mapped[str] = mapped_column(sa.String(64), unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    side: Mapped[str] = mapped_column(sa.String(4))
    qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))
    status: Mapped[str] = mapped_column(default="SUBMITTED")
    expected_price: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    expected_qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))
    filled_qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False), default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(
        sa.Numeric(20, 8, asdecimal=False), nullable=True
    )
    event_time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )
    filled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class PaperFinding(Base):
    """Append-only by convention (Law 6-adjacent, same treatment as
    research_violations and ablation_trials -- see migration 0012's own
    docstring)."""

    __tablename__ = "paper_findings"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    finding_type: Mapped[str] = mapped_column(sa.String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class WorkerCadence(Base):
    """Scheduling state for worker.py's cadence-gated concerns -- mutable,
    like Strategy.status, not a history log."""

    __tablename__ = "worker_cadence"

    concern: Mapped[str] = mapped_column(primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
```

- [ ] **Step 7: Run the migration against a real Postgres and verify**

Run: `alembic upgrade head`
Expected: applies `0012` cleanly with no errors. Then:
Run: `alembic current`
Expected: shows `0012` as the current revision.

- [ ] **Step 8: Run the id test again against the real database**

Run: `TEST_DATABASE_URL=<your local/test postgres url> pytest tests/test_paper_ids.py -v`
Expected: PASS (both tests).

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/0012_paper_trading.py prometheus/core/db.py prometheus/core/ids.py tests/test_paper_ids.py
git commit -m "feat(paper): migration 0012 -- paper_orders, paper_findings, worker_cadence"
```

---

## Task 2: Qubx evaluation — `docs/DEPENDENCIES.md` and `docs/DEFERRED.md`

**Files:**
- Modify: `docs/DEPENDENCIES.md` (append a new dependency-evaluation entry, same style as the "External art-processing tools evaluated and not adopted" block)
- Modify: `docs/DEFERRED.md` (append a short entry noting the rejection and its trigger for revisiting)

**Interfaces:** none (documentation only; no other task depends on this one, but it should land before or alongside Task 5-8 since PROMPTS.md explicitly asks for this evaluation as part of PROMPT 8).

- [ ] **Step 1: Append to `docs/DEPENDENCIES.md`**

Add a new paragraph after the isometric math attribution paragraph at the end of the file:

```markdown

**Qubx evaluated and not adopted (2026-09-17):** PROMPTS.md PROMPT 8 asks
that `github.com/xLydianSoftware/Qubx` be evaluated as the paper-trading
execution layer before building our own. Checked via `gh repo view
xLydianSoftware/Qubx`: GPLv3-licensed ("Framework for quantitative
strategies development, backtesting and live execution"), primary
language Jupyter Notebook, 69 stars. Two disqualifying findings, not a
technical feature comparison: (1) GPLv3 linked into this codebase risks
obligating the whole combined work to GPLv3 if this repo is ever
distributed, an unforced risk when `ccxt` (already an MIT dependency,
already used in `data/ingestion.py`) covers everything a testnet broker
adapter needs directly; (2) a notebook-first repo is a poor fit for the
bounded, async, Postgres-`SKIP LOCKED`-queue-driven worker this codebase
already runs (`worker.py`, `experiments/queue.py`) -- there is no clean
headless entrypoint to integrate against without adopting its whole
framework shape. `paper/broker.py` is a ~100-line `ccxt.binance()`
wrapper instead. PROMPTS.md explicitly permits concluding "our adapter is
simpler" -- this is that conclusion.
```

- [ ] **Step 2: Append to `docs/DEFERRED.md`**

Add a new bullet at the end of the file's deferred-items list:

```markdown
- **Qubx (`xLydianSoftware/Qubx`) was evaluated and rejected for the
  paper-trading execution layer** -- GPLv3 license risk plus a
  notebook-first shape that doesn't fit this repo's bounded async worker
  (full reasoning in `docs/DEPENDENCIES.md`'s 2026-09-17 entry).
  **Trigger:** revisit only if Qubx relicenses under a permissive license
  AND ships a real headless library entrypoint -- neither is expected,
  so this is not an active watch item.
```

- [ ] **Step 3: Commit**

```bash
git add docs/DEPENDENCIES.md docs/DEFERRED.md
git commit -m "docs: record Qubx evaluation for PROMPT 8 (GPLv3, rejected)"
```

---

## Task 3: `minimum_track_record_length` in `validation/multiple_testing.py`

**Files:**
- Modify: `prometheus/validation/multiple_testing.py` (extract `_psr_denominator` helper from `probabilistic_sharpe_ratio`, add `minimum_track_record_length`)
- Test: `tests/test_multiple_testing.py` (extend existing file if present; otherwise this task's tests confirm one already exists — check first with `ls tests/test_multiple_testing.py`)

**Interfaces:**
- Consumes: `_phi_inv` (private helper already in this file, unchanged signature `(p: float) -> float`).
- Produces: `minimum_track_record_length(*, sharpe_hat: float, benchmark_sharpe: float, skewness: float, kurtosis: float, confidence: float) -> int | None` — Task 4 (`paper/duration.py`) imports this directly.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_multiple_testing.py
from prometheus.validation.multiple_testing import minimum_track_record_length


def test_minimum_track_record_length_positive_case():
    # SR_hat well above benchmark, mild negative skew, near-Gaussian
    # kurtosis -- a finite, small required track record.
    n = minimum_track_record_length(
        sharpe_hat=1.5,
        benchmark_sharpe=0.0,
        skewness=-0.2,
        kurtosis=3.2,
        confidence=0.95,
    )
    assert n is not None
    assert n >= 2


def test_minimum_track_record_length_zero_edge_returns_none():
    # sharpe_hat == benchmark_sharpe: no finite track record makes the
    # observed edge distinguishable from the benchmark.
    assert (
        minimum_track_record_length(
            sharpe_hat=0.5,
            benchmark_sharpe=0.5,
            skewness=0.0,
            kurtosis=3.0,
            confidence=0.95,
        )
        is None
    )


def test_minimum_track_record_length_matches_closed_form_by_hand():
    # Bailey & Lopez de Prado's MinTRL, computed independently here to
    # cross-check the implementation rather than trust it circularly.
    import math

    sharpe_hat, benchmark_sharpe, skew, kurt, confidence = 1.0, 0.2, 0.0, 3.0, 0.95
    denom = 1.0 - skew * sharpe_hat + ((kurt - 1.0) / 4.0) * sharpe_hat**2
    z = 1.6448536269514722  # Phi^-1(0.95), computed independently
    expected = 1.0 + denom * z**2 / (sharpe_hat - benchmark_sharpe) ** 2
    n = minimum_track_record_length(
        sharpe_hat=sharpe_hat,
        benchmark_sharpe=benchmark_sharpe,
        skewness=skew,
        kurtosis=kurt,
        confidence=confidence,
    )
    assert n == math.ceil(expected)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_multiple_testing.py -k minimum_track_record_length -v`
Expected: FAIL — `ImportError: cannot import name 'minimum_track_record_length'`

- [ ] **Step 3: Extract `_psr_denominator` and add `minimum_track_record_length`**

In `prometheus/validation/multiple_testing.py`, replace the inline denominator computation inside `probabilistic_sharpe_ratio` with a shared helper, then add the new function after `probabilistic_sharpe_ratio`:

```python
def _psr_denominator(skewness: float, kurtosis: float, sharpe_hat: float) -> float:
    """The PSR/MinTRL shared denominator -- Bailey & Lopez de Prado
    (2012/2014)'s adjustment for skew and (non-excess) kurtosis. Shared
    by probabilistic_sharpe_ratio and minimum_track_record_length so the
    same formula is never duplicated between the two companion
    statistics."""
    return 1.0 - skewness * sharpe_hat + ((kurtosis - 1.0) / 4.0) * sharpe_hat**2
```

Update `probabilistic_sharpe_ratio` to call it:

```python
def probabilistic_sharpe_ratio(
    sharpe_hat: float,
    benchmark_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
) -> float | None:
    """... (docstring unchanged) ..."""
    if n_observations < 2:
        return None
    denom = _psr_denominator(skewness, kurtosis, sharpe_hat)
    if denom <= 0:
        return None
    z = (sharpe_hat - benchmark_sharpe) * math.sqrt(n_observations - 1) / math.sqrt(denom)
    return _phi(z)
```

Add the new function:

```python
def minimum_track_record_length(
    *,
    sharpe_hat: float,
    benchmark_sharpe: float,
    skewness: float,
    kurtosis: float,
    confidence: float,
) -> int | None:
    """Bailey & Lopez de Prado's Minimum Track Record Length -- the
    number of independent observations needed before an observed Sharpe
    is distinguishable from benchmark_sharpe at the given confidence,
    given the same skew/kurtosis adjustment probabilistic_sharpe_ratio
    already applies (same paper, same _psr_denominator helper -- the
    natural companion statistic, not a new formula family). Used by
    paper/duration.py to answer PROMPTS.md's "observation period derived
    from horizon and independent trade count needed for significance"
    with a citable closed form instead of an invented number.

    None if the denominator is non-positive (same degenerate case
    probabilistic_sharpe_ratio guards against) or sharpe_hat equals
    benchmark_sharpe (no finite track record distinguishes an edge of
    exactly zero from the benchmark)."""
    denom = _psr_denominator(skewness, kurtosis, sharpe_hat)
    if denom <= 0:
        return None
    diff = sharpe_hat - benchmark_sharpe
    if diff == 0:
        return None
    z = _phi_inv(confidence)
    n_star = 1.0 + denom * (z**2) / (diff**2)
    return max(2, math.ceil(n_star))
```

- [ ] **Step 4: Run the full test file to verify nothing broke and new tests pass**

Run: `pytest tests/test_multiple_testing.py -v`
Expected: all PASS, including the pre-existing `probabilistic_sharpe_ratio` tests (confirms the `_psr_denominator` extraction didn't change its behavior).

- [ ] **Step 5: Commit**

```bash
git add prometheus/validation/multiple_testing.py tests/test_multiple_testing.py
git commit -m "feat(validation): add minimum_track_record_length (Bailey & Lopez de Prado MinTRL)"
```

---

## Task 4: `paper/duration.py`

**Files:**
- Create: `prometheus/paper/__init__.py` (empty)
- Create: `prometheus/paper/duration.py`
- Test: `tests/test_paper_duration.py`

**Interfaces:**
- Consumes: `validation.multiple_testing.minimum_track_record_length` (Task 3); `backtest.engine.BacktestResult` (existing, has `.turnover: float`).
- Produces: `required_observation_days(*, minimum_trades: int, historical_turnover: float, historical_window_days: int) -> int | None` and `required_paper_trading_duration(*, sharpe_hat: float, benchmark_sharpe: float, skewness: float, kurtosis: float, confidence: float, historical_turnover: float, historical_window_days: int) -> int | None` — Task 6 (`execution.py`) or Task 9 (`worker.py`) may call the latter when first boarding a champion, to log the expected observation horizon alongside its findings.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_duration.py
import math

from prometheus.paper.duration import required_observation_days, required_paper_trading_duration


def test_required_observation_days_basic():
    # 1.0 turnover/day historically -> 1 trade/day roughly -> 20 trades
    # needed means ~20 days.
    days = required_observation_days(
        minimum_trades=20, historical_turnover=100.0, historical_window_days=100
    )
    assert days == 20


def test_required_observation_days_no_historical_activity_returns_none():
    assert (
        required_observation_days(
            minimum_trades=20, historical_turnover=0.0, historical_window_days=100
        )
        is None
    )


def test_required_paper_trading_duration_end_to_end():
    days = required_paper_trading_duration(
        sharpe_hat=1.5,
        benchmark_sharpe=0.0,
        skewness=-0.2,
        kurtosis=3.2,
        confidence=0.95,
        historical_turnover=50.0,
        historical_window_days=200,
    )
    assert days is not None
    assert days > 0


def test_required_paper_trading_duration_none_when_mintrl_none():
    # sharpe_hat == benchmark_sharpe -> minimum_track_record_length
    # returns None -> this must propagate, not raise or fabricate 0.
    assert (
        required_paper_trading_duration(
            sharpe_hat=0.3,
            benchmark_sharpe=0.3,
            skewness=0.0,
            kurtosis=3.0,
            confidence=0.95,
            historical_turnover=50.0,
            historical_window_days=200,
        )
        is None
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_duration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.paper'`

- [ ] **Step 3: Create `prometheus/paper/__init__.py`**

Empty file (package marker, matching every other `prometheus/*/` subpackage).

- [ ] **Step 4: Write `prometheus/paper/duration.py`**

```python
"""How long a CHAMPION must paper-trade before its realized Sharpe is
statistically distinguishable from the benchmark -- PROMPTS.md's
"observation period derived from horizon and independent trade count
needed for significance," answered with Bailey & Lopez de Prado's
Minimum Track Record Length (validation/multiple_testing.py) rather than
an invented number of days.

Trade frequency is extrapolated from the champion's own historical
backtest turnover (BacktestResult.turnover -- the sum of absolute
position changes over the backtest window, PROMPTS's own accounting
already produces this, nothing new computed here) rather than assuming
a fixed cadence: a strategy that rebalances daily and one that
rebalances monthly need very different real-world observation windows
for the same required trade count.
"""
from __future__ import annotations

import math

from prometheus.validation.multiple_testing import minimum_track_record_length


def required_observation_days(
    *,
    minimum_trades: int,
    historical_turnover: float,
    historical_window_days: int,
) -> int | None:
    """Translates a required independent-trade count into a calendar
    horizon using the champion's own historical trade frequency
    (historical_turnover / historical_window_days). None if there is no
    historical trade activity to extrapolate from -- a strategy that
    never rebalanced in its backtest window gives no basis to predict
    when it next will."""
    if historical_turnover <= 0 or historical_window_days <= 0:
        return None
    trades_per_day = historical_turnover / historical_window_days
    return math.ceil(minimum_trades / trades_per_day)


def required_paper_trading_duration(
    *,
    sharpe_hat: float,
    benchmark_sharpe: float,
    skewness: float,
    kurtosis: float,
    confidence: float,
    historical_turnover: float,
    historical_window_days: int,
) -> int | None:
    """End-to-end: MinTRL's required independent-trade count, translated
    into a calendar day count via this champion's own historical trade
    frequency. None propagates from either step -- a strategy whose
    Sharpe is statistically indistinguishable from its own benchmark
    (minimum_track_record_length returns None) has no finite answer to
    fabricate."""
    n_trades = minimum_track_record_length(
        sharpe_hat=sharpe_hat,
        benchmark_sharpe=benchmark_sharpe,
        skewness=skewness,
        kurtosis=kurtosis,
        confidence=confidence,
    )
    if n_trades is None:
        return None
    return required_observation_days(
        minimum_trades=n_trades,
        historical_turnover=historical_turnover,
        historical_window_days=historical_window_days,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_paper_duration.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add prometheus/paper/__init__.py prometheus/paper/duration.py tests/test_paper_duration.py
git commit -m "feat(paper): duration.py -- MinTRL-derived observation horizon"
```

---

## Task 5: `paper/broker.py`

**Files:**
- Create: `prometheus/paper/broker.py`
- Test: `tests/test_paper_broker.py`
- Modify: `pyproject.toml` — none needed; `ccxt` is already pinned (line 19) and already has a mypy `ignore_missing_imports` override (lines 77-81) covering this new import too.

**Interfaces:**
- Consumes: `ccxt.binance` (from the already-pinned `ccxt==4.5.77`); `prometheus.experiments.queue.get_queue_settings` (for backoff constants).
- Produces: `class PaperBroker` with `submit_order(*, symbol: str, side: str, qty: float, client_order_id: str) -> dict[str, Any]`, `fetch_order(*, symbol: str, exchange_order_id: str) -> dict[str, Any]`, `fetch_open_orders(*, symbol: str) -> list[dict[str, Any]]`, `cancel_order(*, symbol: str, exchange_order_id: str) -> dict[str, Any]` — Task 6 (`execution.py`) depends on exactly these four methods and this constructor's raise behavior.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_broker.py
import os

import pytest

from prometheus.paper.broker import PaperBroker, _LIVE_VAR_NAMES


class FakeCcxtExchange:
    """The ccxt subset PaperBroker uses -- same fake-injection precedent
    as data/ingestion.py's ExchangeClient tests."""

    def __init__(self) -> None:
        self.sandbox_enabled = False
        self.urls = {"api": "https://api.binance.com"}
        self.calls: list[tuple[str, tuple, dict]] = []

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_enabled = enabled
        if enabled:
            self.urls = {"api": "https://testnet.binance.vision/api"}

    def create_order(self, symbol, side, order_type, qty, price=None, params=None):
        self.calls.append(("create_order", (symbol, side, order_type, qty), params or {}))
        return {"id": "exch-1", "status": "open"}

    def fetch_order(self, exchange_order_id, symbol):
        return {"id": exchange_order_id, "status": "closed", "filled": 1.0, "average": 100.0}

    def fetch_open_orders(self, symbol):
        return []

    def cancel_order(self, exchange_order_id, symbol):
        return {"id": exchange_order_id, "status": "canceled"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _LIVE_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_API_KEY", "test-key")
    monkeypatch.setenv("PAPER_API_SECRET", "test-secret")


def test_broker_asserts_testnet_url(monkeypatch):
    broker = PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())
    assert "testnet" in str(broker.exchange.urls["api"]).lower()


def test_broker_raises_if_live_var_present(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "danger")
    with pytest.raises(RuntimeError, match="live-sounding"):
        PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())


def test_broker_raises_if_paper_credentials_missing(monkeypatch):
    monkeypatch.delenv("PAPER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PAPER_API_KEY"):
        PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())


def test_submit_order_calls_create_order_with_client_order_id():
    fake = FakeCcxtExchange()
    broker = PaperBroker(exchange_factory=lambda **_: fake)
    result = broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="abc123")
    assert result["id"] == "exch-1"
    assert fake.calls[0][2].get("newClientOrderId") == "abc123"


def test_submit_order_retries_on_network_error_then_succeeds(monkeypatch):
    import ccxt

    from prometheus.core.config import QueueSettings

    class FlakyExchange(FakeCcxtExchange):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def create_order(self, symbol, side, order_type, qty, price=None, params=None):
            self.attempts += 1
            if self.attempts < 2:
                raise ccxt.NetworkError("simulated transient failure")
            return super().create_order(symbol, side, order_type, qty, price, params)

    monkeypatch.setattr("time.sleep", lambda _seconds: None)  # no real delay in tests
    fast_settings = QueueSettings(
        JOB_HEARTBEAT_INTERVAL_SECONDS=1.0,
        JOB_HEARTBEAT_TIMEOUT_SECONDS=5.0,
        JOB_BACKOFF_BASE_SECONDS=0.01,
        JOB_BACKOFF_MAX_SECONDS=0.02,
    )
    fake = FlakyExchange()
    broker = PaperBroker(exchange_factory=lambda **_: fake, queue_settings=fast_settings)
    result = broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="retry-1")
    assert result["id"] == "exch-1"
    assert fake.attempts == 2


def test_submit_order_gives_up_after_max_attempts(monkeypatch):
    import ccxt

    from prometheus.core.config import QueueSettings

    class AlwaysFlaky(FakeCcxtExchange):
        def create_order(self, symbol, side, order_type, qty, price=None, params=None):
            raise ccxt.NetworkError("simulated permanent failure")

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    fast_settings = QueueSettings(
        JOB_HEARTBEAT_INTERVAL_SECONDS=1.0,
        JOB_HEARTBEAT_TIMEOUT_SECONDS=5.0,
        JOB_BACKOFF_BASE_SECONDS=0.01,
        JOB_BACKOFF_MAX_SECONDS=0.02,
    )
    broker = PaperBroker(exchange_factory=lambda **_: AlwaysFlaky(), queue_settings=fast_settings)
    with pytest.raises(ccxt.NetworkError):
        broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="retry-2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_broker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.paper.broker'`

- [ ] **Step 3: Write `prometheus/paper/broker.py`** (includes retry-with-backoff on transient `ccxt.NetworkError`, reusing `QueueSettings.JOB_BACKOFF_BASE_SECONDS`/`JOB_BACKOFF_MAX_SECONDS` and this codebase's existing `max_attempts=3` convention — see `experiments/runner.py::enqueue_grid`/`worker.py::_enqueue_child`, both already call `enqueue(..., max_attempts=3, ...)` — reused here rather than inventing a new retry count)

```python
"""A thin ccxt.binance() wrapper for Binance's real spot testnet
(testnet.binance.vision) -- Law 5: no code path here may ever reach a
live venue. Deliberately not ccxt.binanceus() (data/ingestion.py's
choice, forced by Binance.com's 451 geo-block on market-data endpoints
only): the testnet is a wholly separate sandbox with its own credential
pair, unaffected by that geo-block, and binanceus has no equivalent
testnet to point at.

Two independent guards, both enforced at construction, not deferred to
first use: (1) after set_sandbox_mode(True), the resulting exchange.urls
must actually mention "testnet" -- defends against a future ccxt version
changing sandbox behavior silently; (2) construction raises if ANY
live-sounding credential variable is present in the environment at all,
sandboxed or not -- its mere presence is the failure mode this guards
against, not whether it happens to get used this run.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from prometheus.core.config import QueueSettings
from prometheus.experiments.queue import get_queue_settings

_T = TypeVar("_T")

# Bounded retry attempts for one ccxt call -- this codebase's existing
# convention (experiments/runner.py::enqueue_grid, worker.py's own
# _enqueue_child both call enqueue(..., max_attempts=3, ...)), reused
# here rather than inventing a new retry count.
_MAX_ATTEMPTS = 3

# Known live-credential variable names this guard checks for. Not an
# exhaustive pattern match by design -- an explicit, reviewable list is
# safer for a Law-5-adjacent check than a clever regex that could miss a
# real live-sounding name or, worse, false-positive and block PAPER_*
# entirely. Extend this list if a new live integration is ever added.
_LIVE_VAR_NAMES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET_KEY",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
)


class CcxtExchange(Protocol):
    """The ccxt subset this module uses -- same "typed subset, fake in
    tests" convention as data/ingestion.py's ExchangeClient."""

    urls: dict[str, Any]

    def set_sandbox_mode(self, enabled: bool) -> None: ...
    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def fetch_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]: ...
    def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]: ...
    def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]: ...


def _default_exchange_factory(**kwargs: Any) -> CcxtExchange:
    import ccxt

    exchange: CcxtExchange = ccxt.binance(kwargs)
    return exchange


class PaperBroker:
    def __init__(
        self,
        *,
        exchange_factory: Callable[..., CcxtExchange] = _default_exchange_factory,
        queue_settings: QueueSettings | None = None,
    ) -> None:
        # DI, same reason as exchange_factory: get_queue_settings() reads
        # required env vars with no defaults (core/config.py), so tests
        # pass an explicit fast QueueSettings instead of needing those
        # vars set -- same posture tests/test_queue_semantics.py already
        # establishes for QueueSettings in tests generally.
        self._queue_settings = queue_settings
        present_live_vars = [name for name in _LIVE_VAR_NAMES if os.environ.get(name)]
        if present_live_vars:
            raise RuntimeError(
                "live-sounding credential variable(s) present in environment: "
                f"{present_live_vars} -- Law 5 forbids any live-money code path; "
                "unset them before running paper trading, even sandboxed."
            )
        api_key = os.environ.get("PAPER_API_KEY")
        api_secret = os.environ.get("PAPER_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError(
                "PAPER_API_KEY and PAPER_API_SECRET must both be set (testnet "
                "credentials from testnet.binance.vision)"
            )

        self.exchange = exchange_factory(apiKey=api_key, secret=api_secret)
        self.exchange.set_sandbox_mode(True)
        if "testnet" not in str(self.exchange.urls.get("api", "")).lower():
            raise RuntimeError(
                "PaperBroker could not confirm testnet mode: "
                f"exchange.urls['api'] = {self.exchange.urls.get('api')!r}"
            )

    def _with_retry(self, call: Callable[[], _T]) -> _T:
        """Retries a transient ccxt.NetworkError with the same backoff
        shape experiments/queue.py's job retry already uses
        (JOB_BACKOFF_BASE_SECONDS / JOB_BACKOFF_MAX_SECONDS), not a new
        backoff constant. Re-raises after _MAX_ATTEMPTS -- this is a
        bounded worker tick, not a process that should hang retrying
        forever. Generic over the call's return type so both a dict
        (submit_order, fetch_order, cancel_order) and a list
        (fetch_open_orders) can share this one retry path."""
        import ccxt

        settings = self._queue_settings or get_queue_settings()
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return call()
            except ccxt.NetworkError as exc:
                last_error = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    break
                delay = min(
                    settings.JOB_BACKOFF_BASE_SECONDS * (2**attempt),
                    settings.JOB_BACKOFF_MAX_SECONDS,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def submit_order(
        self, *, symbol: str, side: str, qty: float, client_order_id: str
    ) -> dict[str, Any]:
        return self._with_retry(
            lambda: self.exchange.create_order(
                symbol, side, "market", qty, params={"newClientOrderId": client_order_id}
            )
        )

    def fetch_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        return self._with_retry(lambda: self.exchange.fetch_order(exchange_order_id, symbol))

    def fetch_open_orders(self, *, symbol: str) -> list[dict[str, Any]]:
        return self._with_retry(lambda: self.exchange.fetch_open_orders(symbol))

    def cancel_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        return self._with_retry(lambda: self.exchange.cancel_order(exchange_order_id, symbol))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_broker.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
git add prometheus/paper/broker.py tests/test_paper_broker.py
git commit -m "feat(paper): broker.py -- ccxt Binance testnet wrapper, Law 5 guards"
```

---

## Task 6: `paper/execution.py`

**Files:**
- Create: `prometheus/paper/execution.py`
- Test: `tests/test_paper_execution.py`

**Interfaces:**
- Consumes: `paper.broker.PaperBroker` (Task 5); `backtest.engine.signal_for`, `backtest.engine.STARTING_CAPITAL` (existing); `core.config.RISK_LIMITS` (existing); `core.ids.next_paper_order_id` (Task 1); `core.db.PaperOrder` (Task 1); `strategy.spec.StrategySpec` (existing).
- Produces: `current_position(session, strategy_id: str) -> float` (net qty, derived from summed fills); `decide_and_submit(session, broker, *, strategy_id: str, spec: StrategySpec, bars: pl.DataFrame) -> str | None` (returns new `paper_orders.id` or `None` if no change needed); `poll_fills(session, broker, *, symbol: str) -> list[str]` (returns updated order ids).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_execution.py
import hashlib
from datetime import datetime, timezone

import polars as pl
import pytest

from prometheus.core.config import RISK_LIMITS  # noqa: F401  (import confirms env is set by conftest)
from prometheus.paper.execution import current_position, decide_and_submit, poll_fills
from prometheus.strategy.spec import StrategySpec

pytestmark = [
    pytest.mark.db,
]


class FakeBroker:
    def __init__(self):
        self.submitted = []
        self.orders = {}

    def submit_order(self, *, symbol, side, qty, client_order_id):
        self.submitted.append((symbol, side, qty, client_order_id))
        self.orders[client_order_id] = {"id": f"exch-{client_order_id}", "status": "open"}
        return self.orders[client_order_id]

    def fetch_open_orders(self, *, symbol):
        return [
            {"id": v["id"], "clientOrderId": k, "symbol": symbol}
            for k, v in self.orders.items()
            if v["status"] == "open"
        ]

    def fetch_order(self, *, symbol, exchange_order_id):
        return {"id": exchange_order_id, "status": "closed", "filled": 0.01, "average": 50000.0}


def _momentum_spec(symbol: str) -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM",
        symbol=symbol,
        timeframe="1d",
        fast_window=5,
        slow_window=10,
        expected_horizon=30,
    )


async def test_decide_and_submit_submits_when_position_changes(db_session):
    spec = _momentum_spec("BTC/USDT")
    bars = pl.DataFrame(
        {
            "available_at": [datetime(2026, 1, i, tzinfo=timezone.utc) for i in range(1, 15)],
            "close": [100.0 + i for i in range(14)],
        }
    )
    broker = FakeBroker()
    order_id = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-001", spec=spec, bars=bars
    )
    assert order_id is not None
    assert len(broker.submitted) == 1


async def test_decide_and_submit_idempotent_on_replay(db_session):
    spec = _momentum_spec("BTC/USDT")
    bars = pl.DataFrame(
        {
            "available_at": [datetime(2026, 2, i, tzinfo=timezone.utc) for i in range(1, 15)],
            "close": [100.0 + i for i in range(14)],
        }
    )
    broker = FakeBroker()
    first = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-002", spec=spec, bars=bars
    )
    second = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-002", spec=spec, bars=bars
    )
    assert first == second
    assert len(broker.submitted) == 1  # not re-submitted on replay


async def test_current_position_zero_with_no_orders(db_session):
    position = await current_position(db_session, "MOMENTUM-003")
    assert position == 0.0
```

Check `tests/conftest.py` for an existing `db_session` fixture; if none exists, add one to `tests/conftest.py` in this task (a session-scoped async engine + per-test transaction rollback is the standard pattern — check `tests/test_ablation_registry.py` or similar for whether one already exists before adding a duplicate).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_execution.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.paper.execution'`

- [ ] **Step 3: Write `prometheus/paper/execution.py`**

```python
"""Order lifecycle for paper-traded CHAMPION strategies. Position is
DERIVED by summing filled paper_orders, never stored separately -- one
source of truth, no dual-write drift between an orders table and a
positions table.

The trading decision always uses signal_for() on 1d bars, identical to
the backtest -- this module never recomputes a signal on a shorter bar
(see docs/superpowers/specs/2026-09-17-paper-trading-design.md's cadence
discussion). What runs on every 15-minute worker tick is poll_fills, not
a new trading decision.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.engine import STARTING_CAPITAL, signal_for
from prometheus.core.config import RISK_LIMITS
from prometheus.core.ids import next_paper_order_id
from prometheus.strategy.spec import StrategySpec

_SELECT_FILLED_QTY = text(
    """
    SELECT COALESCE(SUM(
        CASE WHEN side = 'buy' THEN filled_qty ELSE -filled_qty END
    ), 0) AS net_qty
    FROM paper_orders
    WHERE strategy_id = :strategy_id AND status = 'FILLED'
    """
)

_SELECT_EXISTING_BY_CLIENT_ORDER_ID = text(
    "SELECT id FROM paper_orders WHERE client_order_id = :client_order_id"
)

_INSERT_PAPER_ORDER = text(
    """
    INSERT INTO paper_orders (
        id, strategy_id, client_order_id, exchange_order_id, symbol, side, qty,
        status, expected_price, expected_qty, event_time
    ) VALUES (
        :id, :strategy_id, :client_order_id, :exchange_order_id, :symbol, :side, :qty,
        'SUBMITTED', :expected_price, :expected_qty, :event_time
    )
    """
)

_SELECT_OPEN_ORDERS = text(
    "SELECT id, exchange_order_id, symbol FROM paper_orders WHERE status = 'SUBMITTED' AND symbol = :symbol"
)

_UPDATE_FILL = text(
    """
    UPDATE paper_orders
       SET status = 'FILLED', filled_qty = :filled_qty, avg_fill_price = :avg_fill_price,
           filled_at = now()
     WHERE id = :id
    """
)


async def current_position(session: AsyncSession, strategy_id: str) -> float:
    """Net base-asset quantity held, derived from every FILLED order's
    signed quantity -- never a separately stored, driftable value."""
    result = await session.execute(_SELECT_FILLED_QTY, {"strategy_id": strategy_id})
    return float(result.scalar_one())


def _client_order_id(strategy_id: str, event_time: datetime, side: str) -> str:
    """Deterministic -- a tick replayed after a crash (same strategy,
    same decision bar, same side) produces the identical id, making
    re-submission a safe no-op via the SELECT-before-INSERT check in
    decide_and_submit, the same idempotency shape queue.enqueue() uses
    for jobs."""
    raw = f"{strategy_id}|{event_time.isoformat()}|{side}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _clamp_target_qty(target_qty: float, price: float) -> float:
    """Law 4: order sizing never exceeds RISK_LIMITS, applied against
    this strategy's own €1000 paper capital (STARTING_CAPITAL), not the
    whole paper-trading book. MAX_LEVERAGE would only matter for a
    margined position, which nothing here ever opens (spot only) --
    included anyway so a future margin feature can't silently bypass it."""
    max_notional = STARTING_CAPITAL * min(
        RISK_LIMITS.MAX_POSITION_PCT / 100.0, RISK_LIMITS.MAX_GROSS_EXPOSURE_PCT / 100.0
    ) * RISK_LIMITS.MAX_LEVERAGE
    max_qty = max_notional / price
    return max(min(target_qty, max_qty), -max_qty)


async def decide_and_submit(
    session: AsyncSession,
    broker: Any,
    *,
    strategy_id: str,
    spec: StrategySpec,
    bars: pl.DataFrame,
) -> str | None:
    """Computes the champion's target position from the exact same
    signal_for() the backtest uses, diffs it against the currently held
    quantity, and submits the delta as a market order sized off €1000
    notional and clamped by RISK_LIMITS. Returns None if no change is
    needed (target already matches current position) or if this exact
    decision (strategy_id, event_time, side) was already submitted --
    the caller should call this every tick; it is a safe no-op when
    there is nothing new to do.
    """
    signaled = signal_for(bars, spec)
    last_row = signaled.tail(1).to_dicts()[0]
    target_fraction = last_row["position"]
    price = bars.tail(1)["close"][0]
    event_time = bars.tail(1)["available_at"][0]

    target_qty = _clamp_target_qty((target_fraction * STARTING_CAPITAL) / price, price)
    held_qty = await current_position(session, strategy_id)
    delta = target_qty - held_qty
    if abs(delta) < 1e-8:
        return None

    side = "buy" if delta > 0 else "sell"
    client_order_id = _client_order_id(strategy_id, event_time, side)

    existing = await session.execute(
        _SELECT_EXISTING_BY_CLIENT_ORDER_ID, {"client_order_id": client_order_id}
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is not None:
        return str(existing_id)

    result = broker.submit_order(
        symbol=spec.symbol, side=side, qty=abs(delta), client_order_id=client_order_id
    )
    order_id = await next_paper_order_id()
    await session.execute(
        _INSERT_PAPER_ORDER,
        {
            "id": order_id,
            "strategy_id": strategy_id,
            "client_order_id": client_order_id,
            "exchange_order_id": result.get("id"),
            "symbol": spec.symbol,
            "side": side,
            "qty": abs(delta),
            "expected_price": price,
            "expected_qty": abs(delta),
            "event_time": event_time,
        },
    )
    await session.commit()
    return order_id


async def poll_fills(session: AsyncSession, broker: Any, *, symbol: str) -> list[str]:
    """Called every 15-minute tick regardless of whether a new bar
    closed -- checks every still-SUBMITTED order for this symbol against
    the exchange and records fills. Returns the ids of orders updated
    this call."""
    open_rows = (await session.execute(_SELECT_OPEN_ORDERS, {"symbol": symbol})).fetchall()
    updated: list[str] = []
    for row in open_rows:
        fetched = broker.fetch_order(symbol=symbol, exchange_order_id=row.exchange_order_id)
        if fetched.get("status") != "closed":
            continue
        await session.execute(
            _UPDATE_FILL,
            {
                "id": row.id,
                "filled_qty": fetched.get("filled", 0.0),
                "avg_fill_price": fetched.get("average"),
            },
        )
        updated.append(row.id)
    if updated:
        await session.commit()
    return updated
```

Note: `poll_fills` looks orders up on the exchange by `exchange_order_id` (ccxt's `fetch_order` takes the exchange's own order id, not the client-assigned one), which is why `_SELECT_OPEN_ORDERS` selects `exchange_order_id` rather than `client_order_id` — `FakeBroker.fetch_order` in the test above takes `exchange_order_id=...` matching `PaperBroker`'s real signature from Task 5.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_execution.py -v`
Expected: PASS (all three tests). If `db_session` fixture doesn't exist yet and had to be added, re-run the full test file after adding it.

- [ ] **Step 5: Commit**

```bash
git add prometheus/paper/execution.py tests/test_paper_execution.py tests/conftest.py
git commit -m "feat(paper): execution.py -- idempotent order submission, fill polling, derived position"
```

---

## Task 7: `paper/reconciliation.py`

**Files:**
- Create: `prometheus/paper/reconciliation.py`
- Test: `tests/test_paper_reconciliation.py`

**Interfaces:**
- Consumes: `core.db.PaperOrder`, `core.db.PaperFinding` (Task 1); `backtest.benchmark.compute_benchmark_curve` (existing); `backtest.engine.STARTING_CAPITAL` (existing); `data.loaders.load_point_in_time` (existing).
- Produces: `reconcile_order(session, *, order_id: str) -> dict[str, float] | None` (per-order expected-vs-actual deltas: `price_delta_pct`, `qty_delta_pct`, `latency_seconds`); `compute_paper_equity_curve(session, *, strategy_id: str, current_price: float) -> list[tuple[date, float]]` (a real mark-to-market curve from actual fills — Task 9 calls this, NOT a raw notional-per-trade query, before calling the next function); `check_worse_than_holding(session, *, strategy_id: str, symbol: str, paper_equity_curve: list[tuple[date, float]], as_of_cutoff: datetime) -> bool` (writes a `PAPER_WORSE_THAN_HOLDING` finding and returns True if it fired).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_reconciliation.py
from datetime import datetime, timezone

import pytest

from prometheus.paper.reconciliation import (
    check_worse_than_holding,
    compute_paper_equity_curve,
    reconcile_order,
)

pytestmark = [pytest.mark.db]


async def test_reconcile_order_computes_price_and_qty_deltas(db_session):
    # Insert a FILLED paper_orders row directly with known
    # expected/actual values, then confirm the deltas.
    from sqlalchemy import text

    await db_session.execute(
        text(
            """
            INSERT INTO strategies (id, family, spec, status)
            VALUES ('MOMENTUM-010', 'MOMENTUM', '{}', 'CHAMPION')
            """
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, filled_qty, avg_fill_price,
                event_time, submitted_at, filled_at
            ) VALUES (
                'PAPER-TEST-1', 'MOMENTUM-010', 'coid-1', 'BTC/USDT', 'buy', 0.01,
                'FILLED', 50000.0, 0.01, 0.01, 50100.0,
                now() - interval '1 hour', now() - interval '1 hour', now()
            )
            """
        )
    )
    await db_session.commit()

    result = await reconcile_order(db_session, order_id="PAPER-TEST-1")
    assert result is not None
    assert result["price_delta_pct"] == pytest.approx((50100.0 - 50000.0) / 50000.0 * 100, rel=1e-6)
    assert result["qty_delta_pct"] == pytest.approx(0.0, abs=1e-9)
    assert result["latency_seconds"] > 0


async def test_reconcile_order_returns_none_when_not_filled(db_session):
    from sqlalchemy import text

    await db_session.execute(
        text(
            """
            INSERT INTO strategies (id, family, spec, status)
            VALUES ('MOMENTUM-011', 'MOMENTUM', '{}', 'CHAMPION')
            """
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, event_time
            ) VALUES (
                'PAPER-TEST-2', 'MOMENTUM-011', 'coid-2', 'BTC/USDT', 'buy', 0.01,
                'SUBMITTED', 50000.0, 0.01, now()
            )
            """
        )
    )
    await db_session.commit()
    assert await reconcile_order(db_session, order_id="PAPER-TEST-2") is None


async def test_check_worse_than_holding_fires_on_losing_curve(db_session):
    from sqlalchemy import text

    await db_session.execute(
        text(
            """
            INSERT INTO strategies (id, family, spec, status)
            VALUES ('MOMENTUM-012', 'MOMENTUM', '{}', 'CHAMPION')
            """
        )
    )
    await db_session.commit()

    # A strictly losing paper equity curve against a flat/rising
    # benchmark should fire the finding. compute_benchmark_curve needs
    # real ingested bars for 'BTC/USDT' -- this test is DB+data gated,
    # see the module-level skip below if no such data exists locally.
    losing_curve = [
        (datetime(2026, 1, i, tzinfo=timezone.utc).date(), 1000.0 - i * 10) for i in range(1, 10)
    ]
    fired = await check_worse_than_holding(
        db_session,
        strategy_id="MOMENTUM-012",
        symbol="BTC/USDT",
        paper_equity_curve=losing_curve,
        as_of_cutoff=datetime(2026, 1, 9, tzinfo=timezone.utc),
    )
    assert fired is True

    findings = (
        await db_session.execute(
            text("SELECT finding_type FROM paper_findings WHERE strategy_id = 'MOMENTUM-012'")
        )
    ).fetchall()
    assert any(row.finding_type == "PAPER_WORSE_THAN_HOLDING" for row in findings)


async def test_compute_paper_equity_curve_from_real_fills(db_session):
    from sqlalchemy import text

    await db_session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES ('MOMENTUM-013', 'MOMENTUM', '{}', 'CHAMPION')"
        )
    )
    # Buy 0.01 BTC at 50000, then sell 0.005 at 51000 -- cash and
    # position both move, and the curve must reflect BOTH fills, not
    # just the size of the last one.
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, filled_qty, avg_fill_price,
                event_time, submitted_at, filled_at
            ) VALUES
            ('PAPER-TEST-3A', 'MOMENTUM-013', 'coid-3a', 'BTC/USDT', 'buy', 0.01, 'FILLED',
             50000.0, 0.01, 0.01, 50000.0,
             now() - interval '2 hours', now() - interval '2 hours', now() - interval '2 hours'),
            ('PAPER-TEST-3B', 'MOMENTUM-013', 'coid-3b', 'BTC/USDT', 'sell', 0.005, 'FILLED',
             51000.0, 0.005, 0.005, 51000.0,
             now() - interval '1 hour', now() - interval '1 hour', now() - interval '1 hour')
            """
        )
    )
    await db_session.commit()

    curve = await compute_paper_equity_curve(
        db_session, strategy_id="MOMENTUM-013", current_price=52000.0
    )
    assert len(curve) == 3  # one point per fill, plus the final mark-to-market point

    # After fill 1 (buy 0.01 @ 50000): cash = 1000 - 500 = 500, position = 0.01
    # equity = 500 + 0.01 * 50000 = 1000
    assert curve[0][1] == pytest.approx(1000.0, abs=1e-6)

    # After fill 2 (sell 0.005 @ 51000): cash = 500 + 255 = 755, position = 0.005
    # equity = 755 + 0.005 * 51000 = 1010
    assert curve[1][1] == pytest.approx(1010.0, abs=1e-6)

    # Final point marked at current_price=52000, not the last fill's price:
    # equity = 755 + 0.005 * 52000 = 1015
    assert curve[2][1] == pytest.approx(1015.0, abs=1e-6)


async def test_compute_paper_equity_curve_empty_with_no_fills(db_session):
    curve = await compute_paper_equity_curve(
        db_session, strategy_id="MOMENTUM-NONEXISTENT", current_price=100.0
    )
    assert curve == []
```

The `test_check_worse_than_holding_fires_on_losing_curve` test needs real ingested `BTC/USDT` bars for `compute_benchmark_curve` to return a non-empty curve — mark it `@pytest.mark.skipif` gated the same way `test_ablation_placebo.py` gates on real data, or seed a handful of `ohlcv_bars` rows directly in the test (`INSERT INTO ohlcv_bars (...)` for a few days) rather than relying on production data being present. Prefer seeding directly — it keeps the test self-contained and deterministic.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_reconciliation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.paper.reconciliation'`

- [ ] **Step 3: Write `prometheus/paper/reconciliation.py`**

```python
"""Compares every FILLED paper order against what was expected at
submission time, and compares realized paper equity against a €1000
buy-and-hold over the same window (Law 8) -- the same
backtest.benchmark.compute_benchmark_curve every other Law-8 comparison
in this codebase uses, not a second benchmark computation.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.benchmark import compute_benchmark_curve
from prometheus.backtest.engine import STARTING_CAPITAL
from prometheus.core.db import PaperFinding
from prometheus.data.loaders import load_point_in_time

_SELECT_ORDER = text(
    """
    SELECT expected_price, expected_qty, filled_qty, avg_fill_price,
           submitted_at, filled_at, status
      FROM paper_orders WHERE id = :order_id
    """
)

_SELECT_FILLED_ORDERS_CHRONO = text(
    """
    SELECT side, filled_qty, avg_fill_price, filled_at
      FROM paper_orders
     WHERE strategy_id = :strategy_id AND status = 'FILLED'
     ORDER BY filled_at
    """
)


async def reconcile_order(session: AsyncSession, *, order_id: str) -> dict[str, float] | None:
    """None if the order hasn't reached FILLED yet -- there is nothing
    to reconcile against a still-open order."""
    row = (await session.execute(_SELECT_ORDER, {"order_id": order_id})).first()
    if row is None or row.status != "FILLED":
        return None

    price_delta_pct = (float(row.avg_fill_price) - float(row.expected_price)) / float(
        row.expected_price
    ) * 100
    qty_delta_pct = (float(row.filled_qty) - float(row.expected_qty)) / float(row.expected_qty) * 100
    latency_seconds = (row.filled_at - row.submitted_at).total_seconds()

    return {
        "price_delta_pct": price_delta_pct,
        "qty_delta_pct": qty_delta_pct,
        "latency_seconds": latency_seconds,
    }


async def compute_paper_equity_curve(
    session: AsyncSession, *, strategy_id: str, current_price: float
) -> list[tuple[date, float]]:
    """A REAL mark-to-market equity curve built from actual fills --
    cash (STARTING_CAPITAL, debited by every buy's notional and credited
    by every sell's) plus the current position's value, same accounting
    shape backtest.engine._run_accounting produces from simulated
    positions, now built from real filled orders. This is deliberately
    NOT "the notional of each individual trade" -- a list of per-trade
    notionals is not an equity curve and cannot be meaningfully compared
    against compute_benchmark_curve's final portfolio value.

    One point per fill event (marked at that fill's own price), plus a
    final point marked at `current_price` (the latest close) -- an open
    position's value moves with the market between fills, not just at
    the moment of the last trade."""
    rows = (
        await session.execute(_SELECT_FILLED_ORDERS_CHRONO, {"strategy_id": strategy_id})
    ).fetchall()
    if not rows:
        return []

    cash = STARTING_CAPITAL
    position_qty = 0.0
    curve: list[tuple[date, float]] = []
    for row in rows:
        signed_qty = float(row.filled_qty) if row.side == "buy" else -float(row.filled_qty)
        cash -= signed_qty * float(row.avg_fill_price)
        position_qty += signed_qty
        curve.append((row.filled_at.date(), cash + position_qty * float(row.avg_fill_price)))

    curve.append((rows[-1].filled_at.date(), cash + position_qty * current_price))
    return curve


async def check_worse_than_holding(
    session: AsyncSession,
    *,
    strategy_id: str,
    symbol: str,
    paper_equity_curve: list[tuple[date, float]],
    as_of_cutoff: datetime,
) -> bool:
    """Compares the champion's realized paper equity (compute_paper_equity_curve's
    output) against a €1000 buy-and-hold of its own symbol over the
    identical window (Law 8). Writes and prominently surfaces
    PAPER_WORSE_THAN_HOLDING -- checked FIRST, same ordering
    validation/decision.py already establishes for the backtest-time
    equivalent of this same check."""
    if not paper_equity_curve:
        return False

    window_start = datetime.combine(paper_equity_curve[0][0], time.min, tzinfo=UTC)
    pit, _data_version_hash = await load_point_in_time(
        session, [symbol], "1d", window_start, as_of_cutoff
    )
    benchmark = compute_benchmark_curve(pit, [symbol], as_of_cutoff)
    if not benchmark.equity_curve:
        return False

    paper_final = paper_equity_curve[-1][1]
    benchmark_final = benchmark.final_value
    if paper_final >= benchmark_final:
        return False

    session.add(
        PaperFinding(
            strategy_id=strategy_id,
            finding_type="PAPER_WORSE_THAN_HOLDING",
            detail={
                "paper_final_value": paper_final,
                "benchmark_final_value": benchmark_final,
                "as_of_cutoff": as_of_cutoff.isoformat(),
            },
        )
    )
    await session.commit()
    return True
```

This uses the ORM `PaperFinding` class from Task 1 (`session.add(...)`) rather than a raw `text()` insert — same pattern `experiments/ablation.py::record_trial` already uses for its own append-only row, and it sidesteps needing an explicit `bindparams(type_=JSONB)` adapter that a raw `text()` insert of a dict would require (see `experiments/queue.py::_INSERT_JOB` for that pattern, used there because `queue.enqueue` also needs the atomic `ON CONFLICT ... RETURNING` raw SQL for idempotency — no equivalent need here).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_reconciliation.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add prometheus/paper/reconciliation.py tests/test_paper_reconciliation.py
git commit -m "feat(paper): reconciliation.py -- expected vs actual, PAPER_WORSE_THAN_HOLDING"
```

---

## Task 8: `paper/divergence.py`

**Files:**
- Create: `prometheus/paper/divergence.py`
- Test: `tests/test_paper_divergence.py`

**Interfaces:**
- Consumes: `paper.reconciliation.reconcile_order` output shape (Task 7); `core.db.PaperFinding` (Task 1); `core.db.Experiment` (existing); `core.ids.next_experiment_id` (existing).
- Produces: `check_divergence(session, *, strategy_id: str, reconciliation_deltas: list[dict[str, float]]) -> bool` (writes `PAPER_DIVERGENCE` finding, quarantines the strategy, and records a `cost_recalibration_proposal` experiment row if a material divergence is found; returns whether it fired).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_divergence.py
import pytest
from sqlalchemy import text

from prometheus.paper.divergence import check_divergence

pytestmark = [pytest.mark.db]


async def _seed_strategy(db_session, strategy_id: str) -> None:
    await db_session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, 'MOMENTUM', '{}', 'CHAMPION')"
        ),
        {"id": strategy_id},
    )
    await db_session.commit()


async def test_check_divergence_fires_on_material_slippage(db_session):
    await _seed_strategy(db_session, "MOMENTUM-020")
    # A consistent, large price_delta_pct across every fill -- clearly
    # material, not noise around zero.
    deltas = [{"price_delta_pct": 5.0, "qty_delta_pct": 0.0, "latency_seconds": 1.0}] * 10

    fired = await check_divergence(db_session, strategy_id="MOMENTUM-020", reconciliation_deltas=deltas)
    assert fired is True

    status = (
        await db_session.execute(
            text("SELECT status FROM strategies WHERE id = 'MOMENTUM-020'")
        )
    ).scalar_one()
    assert status == "QUARANTINED"

    findings = (
        await db_session.execute(
            text("SELECT finding_type FROM paper_findings WHERE strategy_id = 'MOMENTUM-020'")
        )
    ).fetchall()
    assert any(row.finding_type == "PAPER_DIVERGENCE" for row in findings)

    proposals = (
        await db_session.execute(
            text(
                "SELECT status FROM experiments WHERE strategy_id = 'MOMENTUM-020' "
                "AND status = 'proposed'"
            )
        )
    ).fetchall()
    assert len(proposals) == 1


async def test_check_divergence_does_not_fire_on_small_noise(db_session):
    await _seed_strategy(db_session, "MOMENTUM-021")
    deltas = [{"price_delta_pct": d, "qty_delta_pct": 0.0, "latency_seconds": 1.0} for d in
              [0.01, -0.02, 0.015, -0.01, 0.02, -0.015, 0.01, -0.01, 0.02, -0.02]]

    fired = await check_divergence(db_session, strategy_id="MOMENTUM-021", reconciliation_deltas=deltas)
    assert fired is False

    status = (
        await db_session.execute(
            text("SELECT status FROM strategies WHERE id = 'MOMENTUM-021'")
        )
    ).scalar_one()
    assert status == "CHAMPION"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_divergence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.paper.divergence'`

- [ ] **Step 3: Write `prometheus/paper/divergence.py`**

```python
"""Materiality check for expected-vs-actual divergence (slippage, fill
behavior) -- reuses this codebase's existing z=1.96 two-tailed 95%
convention (tests/test_null_strategies.py, validation/decay.py,
experiments/ablation.py's _Z_95) rather than inventing a new percentage
threshold: a divergence is material if zero is outside the 95% CI of the
observed price_delta_pct sample, not merely if the mean is nonzero.

On a material divergence: writes PAPER_DIVERGENCE, quarantines the
strategy (population.py's existing QUARANTINED status -- no new state),
and records the recalibration proposal as a new `experiments` row
(status="proposed"), never a queue job -- experiments/runner.py::run_one
raises ValueError for any job kind other than "run_backtest", and
PROMPTS.md's own wording is "propose... as a new experiment" anyway.
Nothing acts on this proposal automatically: Law 7 requires a threshold
change to be re-evaluated across the entire historical corpus, never
adopted from one strategy's proposal.
"""
from __future__ import annotations

import statistics

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import Experiment, PaperFinding
from prometheus.core.ids import next_experiment_id

_Z_95 = 1.96

_QUARANTINE_STRATEGY = text("UPDATE strategies SET status = 'QUARANTINED' WHERE id = :id")


def _is_material(deltas_pct: list[float]) -> bool:
    """Zero outside the 95% CI of the sample mean -- same z=1.96
    two-tailed convention this codebase already applies elsewhere, not a
    new invented percentage cutoff. Requires at least 2 observations to
    have a variance to test (same guard probabilistic_sharpe_ratio uses
    for n_observations < 2)."""
    if len(deltas_pct) < 2:
        return False
    mean = statistics.mean(deltas_pct)
    stdev = statistics.stdev(deltas_pct)
    if stdev == 0:
        return mean != 0
    n = len(deltas_pct)
    margin = _Z_95 * stdev / (n**0.5)
    return not (mean - margin <= 0 <= mean + margin)


async def check_divergence(
    session: AsyncSession,
    *,
    strategy_id: str,
    reconciliation_deltas: list[dict[str, float]],
) -> bool:
    price_deltas = [d["price_delta_pct"] for d in reconciliation_deltas]
    if not _is_material(price_deltas):
        return False

    mean_delta = statistics.mean(price_deltas)
    session.add(
        PaperFinding(
            strategy_id=strategy_id,
            finding_type="PAPER_DIVERGENCE",
            detail={"mean_price_delta_pct": mean_delta, "n_observations": len(price_deltas)},
        )
    )
    await session.execute(_QUARANTINE_STRATEGY, {"id": strategy_id})

    proposal_id = await next_experiment_id()
    session.add(
        Experiment(
            id=proposal_id,
            status="proposed",
            strategy_id=strategy_id,
            hypothesis=(
                f"Observed mean fill-price divergence of {mean_delta:.3f}% across "
                f"{len(price_deltas)} paper trades exceeds the cost model's implicit "
                "slippage assumption -- recalibrate config/costs.yaml's slippage_bps."
            ),
            change_set={"proposed_recalibration": "slippage_bps", "observed_mean_delta_pct": mean_delta},
        )
    )
    await session.commit()
    return True
```

Both inserts use the ORM classes (`PaperFinding` from Task 1, `Experiment` already existing — same constructor pattern `experiments/runner.py::_build_experiment` uses) via `session.add(...)`, matching Task 7's reconciliation module and avoiding a raw `text()` insert's JSONB-bind ceremony for two simple appends with no concurrency-critical requirement.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_divergence.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add prometheus/paper/divergence.py tests/test_paper_divergence.py
git commit -m "feat(paper): divergence.py -- materiality check, quarantine, recalibration proposal"
```

---

## Task 9: `worker.py` — cadence-gated concerns

**Files:**
- Modify: `prometheus/worker.py`
- Test: `tests/test_worker_cadence.py`

**Interfaces:**
- Consumes: everything from Tasks 1, 5, 6, 7, 8 (`WorkerCadence` ORM class, `PaperBroker`, `decide_and_submit`, `poll_fills`, `check_worse_than_holding`, `check_divergence`).
- Produces: `is_due(session, *, concern: str, interval_seconds: float) -> bool`; `mark_run(session, *, concern: str) -> None`; refactored `run_once()` that calls three now-separate, cadence-gated functions: `_run_ingest`, `_run_research` (today's existing body, unchanged logic, just extracted), `_run_paper`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_worker_cadence.py
import pytest
from sqlalchemy import text

from prometheus.worker import is_due, mark_run

pytestmark = [pytest.mark.db]


async def test_is_due_true_when_no_prior_run(db_session):
    assert await is_due(db_session, concern="test_concern_1", interval_seconds=900) is True


async def test_is_due_false_immediately_after_mark_run(db_session):
    await mark_run(db_session, concern="test_concern_2")
    assert await is_due(db_session, concern="test_concern_2", interval_seconds=900) is False


async def test_is_due_true_after_interval_elapses(db_session):
    await db_session.execute(
        text(
            "INSERT INTO worker_cadence (concern, last_run_at) "
            "VALUES ('test_concern_3', now() - interval '20 minutes')"
        )
    )
    await db_session.commit()
    assert await is_due(db_session, concern="test_concern_3", interval_seconds=900) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker_cadence.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_due'`

- [ ] **Step 3: Refactor `prometheus/worker.py`**

Add near the top (after the existing imports and constants), and update the module docstring to describe the new three-concern cadence. `worker.py` already imports `AsyncSession` and `get_session` — it does NOT yet import `text` (sqlalchemy) or `polars`, both newly needed:

```python
from datetime import UTC, datetime, timedelta

import polars as pl
from sqlalchemy import text

from prometheus.data.loaders import load_point_in_time
from prometheus.paper.broker import PaperBroker
from prometheus.paper.divergence import check_divergence
from prometheus.paper.execution import decide_and_submit, poll_fills
from prometheus.paper.reconciliation import (
    check_worse_than_holding,
    compute_paper_equity_curve,
    reconcile_order,
)
```

(No other function in `worker.py` does a local `import` inside its body — keep these three at module level rather than repeating local imports inside `is_due`/`_run_paper` below, matching the rest of the file's style.)

Add cadence constants next to the existing `_GRID_LOOKBACK_DAYS` etc.:

```python
_INGEST_INTERVAL_SECONDS = 3600.0  # hourly
_RESEARCH_INTERVAL_SECONDS = 1800.0  # 30 min
_PAPER_INTERVAL_SECONDS = 900.0  # 15 min -- also the new cron tick itself
```

Add the cadence-gating helpers (near the top of the file, after imports):

```python
_SELECT_CADENCE = text("SELECT last_run_at FROM worker_cadence WHERE concern = :concern")
_UPSERT_CADENCE = text(
    """
    INSERT INTO worker_cadence (concern, last_run_at) VALUES (:concern, now())
    ON CONFLICT (concern) DO UPDATE SET last_run_at = now()
    """
)


async def is_due(session: AsyncSession, *, concern: str, interval_seconds: float) -> bool:
    """True if `concern` has never run, or last ran more than
    interval_seconds ago. Each concern gates itself independently so one
    tightened */15 cron can serve three different cadences (PROMPTS.md's
    own schedule: ingest hourly / research 30min / paper 15min) without a
    second scheduled service."""
    row = (await session.execute(_SELECT_CADENCE, {"concern": concern})).first()
    if row is None:
        return True
    elapsed = (datetime.now(UTC) - row.last_run_at).total_seconds()
    return elapsed >= interval_seconds


async def mark_run(session: AsyncSession, *, concern: str) -> None:
    """Called only after a concern completes successfully -- a crashed
    tick leaves last_run_at unchanged, so that concern is re-attempted
    next wake rather than silently skipped."""
    await session.execute(_UPSERT_CADENCE, {"concern": concern})
    await session.commit()
```

Now split `run_once()`'s existing body into three functions. Extract the reap-stale-claims + ingest block into `_run_ingest`:

```python
async def _run_ingest() -> None:
    settings = get_queue_settings()
    async with get_session() as session:
        reaped = await reap_stale_claims(
            session, stale_after_seconds=settings.JOB_HEARTBEAT_TIMEOUT_SECONDS
        )
        await session.commit()
    if reaped:
        print(f"worker: reclaimed {len(reaped)} stale claim(s): {reaped}")
    await backfill(_INGEST_CATCHUP_DAYS)
```

Extract the grid-enqueue + drain + validate + evolve block into `_run_research`:

```python
async def _run_research() -> list[str]:
    symbols = load_universe_symbols()
    for symbol in symbols:
        await enqueue_grid(
            symbol,
            _TIMEFRAME,
            _FAMILY,
            _GRID_LOOKBACK_DAYS,
            priority=0,
            expected_information_value=0.0,
            estimated_cost=0.0,
            max_attempts=3,
        )

    ran = await drain_queue()

    validated: list[str] = []
    async with get_session() as session:
        for symbol in symbols:
            validated.extend(
                await validate_grid(session, symbol, _TIMEFRAME, _FAMILY, _GRID_LOOKBACK_DAYS)
            )

    async with get_session() as session:
        evolved_job_ids = await _run_evolution_step(session)
        await session.commit()
    if evolved_job_ids:
        print(f"worker: enqueued {len(evolved_job_ids)} evolved candidate(s): {evolved_job_ids}")

    return ran + validated
```

Add the new paper concern — one real session per loop iteration, no placeholder connections:

```python
async def _run_paper() -> None:
    """Every champion, every tick: poll fills, reconcile, check
    divergence. Trading decisions (decide_and_submit) only actually
    submit when a new 1d bar makes the target position differ from the
    current one -- see paper/execution.py's own idempotency, not a
    separate "is a new bar due" check here."""
    broker = PaperBroker()
    as_of_cutoff = datetime.now(UTC)

    async with get_session() as session:
        champions = (
            await session.execute(
                text("SELECT id, family, spec FROM strategies WHERE status = 'CHAMPION'")
            )
        ).fetchall()

    for row in champions:
        spec = StrategySpec.model_validate(row.spec)
        async with get_session() as session:
            pit, _data_version_hash = await load_point_in_time(
                session,
                [spec.symbol],
                spec.timeframe,
                as_of_cutoff - timedelta(days=_GRID_LOOKBACK_DAYS),
                as_of_cutoff,
            )
            bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == spec.symbol).sort(
                "available_at"
            )
            if bars.height == 0:
                continue

            await decide_and_submit(session, broker, strategy_id=row.id, spec=spec, bars=bars)
            filled_ids = await poll_fills(session, broker, symbol=spec.symbol)

            deltas = []
            for order_id in filled_ids:
                delta = await reconcile_order(session, order_id=order_id)
                if delta is not None:
                    deltas.append(delta)
            if deltas:
                await check_divergence(session, strategy_id=row.id, reconciliation_deltas=deltas)

            current_price = float(bars.tail(1)["close"][0])
            paper_curve = await compute_paper_equity_curve(
                session, strategy_id=row.id, current_price=current_price
            )
            if paper_curve:
                await check_worse_than_holding(
                    session,
                    strategy_id=row.id,
                    symbol=spec.symbol,
                    paper_equity_curve=paper_curve,
                    as_of_cutoff=as_of_cutoff,
                )
```

Note: this uses `compute_paper_equity_curve` (Task 7) — a real mark-to-market curve from actual fills — never a raw `avg_fill_price * filled_qty` per-trade query. The latter is not an equity curve (it's the size of each trade) and would make `check_worse_than_holding`'s comparison against `compute_benchmark_curve`'s final portfolio value meaningless.

Add the needed imports at the top of `worker.py` (`import polars as pl`, `from prometheus.strategy.spec import StrategySpec` — check `StrategySpec` isn't already imported; it is, per the existing `from prometheus.strategy.spec import FAMILIES, StrategySpec` line — just add `pl` and the four `prometheus.paper.*` imports listed at the start of this step).

Finally, rewrite `run_once()` to gate all three concerns:

```python
async def run_once() -> list[str]:
    ran: list[str] = []
    async with get_session() as session:
        ingest_due = await is_due(
            session, concern="ingest", interval_seconds=_INGEST_INTERVAL_SECONDS
        )
        research_due = await is_due(
            session, concern="research", interval_seconds=_RESEARCH_INTERVAL_SECONDS
        )
        paper_due = await is_due(
            session, concern="paper", interval_seconds=_PAPER_INTERVAL_SECONDS
        )

    if ingest_due:
        await _run_ingest()
        async with get_session() as session:
            await mark_run(session, concern="ingest")

    if research_due:
        ran = await _run_research()
        async with get_session() as session:
            await mark_run(session, concern="research")

    if paper_due:
        await _run_paper()
        async with get_session() as session:
            await mark_run(session, concern="paper")

    return ran


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained/validated {len(ran)} experiment(s): {ran}")
```

Update the module docstring's final paragraph (the one about "Three separate Railway Cron services... this single 30-minute cycle already does all of the above") to reflect the new reality:

```python
Now three concerns run at three different rates from this ONE entrypoint,
gated by worker_cadence (is_due/mark_run below): ingest hourly, research
(today's grid/validate/evolve pipeline, unchanged logic) every 30
minutes, paper trading every tick. The Railway cron interval itself
tightens from */30 to */15 (the finest of the three rates) so the paper
concern's tick actually happens on schedule -- still one scheduled
worker, not a second service.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker_cadence.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Run the full existing worker-related test suite to confirm the refactor didn't break anything**

Run: `pytest tests/ -k worker -v`
Expected: PASS. If any existing test called `run_once()` or `main()` expecting the old unconditional-every-cycle behavior, it will need updating to account for cadence-gating (e.g., seed `worker_cadence` rows or accept that a fresh test DB makes everything due on the first call, which is `is_due`'s documented behavior for a concern that's never run).

- [ ] **Step 6: Commit**

```bash
git add prometheus/worker.py tests/test_worker_cadence.py
git commit -m "feat(worker): cadence-gated ingest/research/paper concerns on one tightened */15 cron"
```

---

## Task 10: Manual step — tighten the Railway cron schedule

This is an **operational change, not a code change** — the cron schedule is configured in the Railway dashboard/CLI, not committed to this repo (confirmed: no `railway.json`/`railway.toml` in the repo defines it).

- [ ] **Step 1:** After Task 9 is merged and deployed, update the `prometheus-worker` cron job's schedule from `*/30 * * * *` to `*/15 * * * *`:

```bash
railway service prometheus-worker  # select the cron service
# then in the Railway dashboard: Settings -> Cron Schedule -> */15 * * * *
```

(Or via `railway` CLI if it exposes a cron-edit command — check `railway service --help` for the current CLI's capability; the dashboard path always works.)

- [ ] **Step 2:** Confirm the next scheduled run fires at the new 15-minute cadence via `railway deployment list -s prometheus-worker` or the dashboard's run history.

No commit for this task (nothing in the repo changes).

---

## Task 11: Integration test + full-suite verification

**Files:**
- Create: `tests/test_paper_integration.py`

**Interfaces:** none new — this task only verifies Tasks 1-9 work together against real infrastructure.

- [ ] **Step 1: Write the gated integration test**

```python
# tests/test_paper_integration.py
import os

import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not (os.environ.get("PAPER_API_KEY") and os.environ.get("PAPER_API_SECRET")),
        reason="requires real PAPER_API_KEY/PAPER_API_SECRET testnet credentials",
    ),
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0012 applied)",
    ),
]


async def test_broker_connects_to_real_testnet():
    from prometheus.paper.broker import PaperBroker

    broker = PaperBroker()
    # A real, harmless read-only call against the real testnet --
    # confirms credentials and connectivity without submitting an order.
    open_orders = broker.fetch_open_orders(symbol="BTC/USDT")
    assert isinstance(open_orders, list)
```

- [ ] **Step 2: Run it (only if you have real testnet credentials)**

Run: `PAPER_API_KEY=... PAPER_API_SECRET=... TEST_DATABASE_URL=... pytest tests/test_paper_integration.py -v`
Expected: PASS if credentials are valid, or SKIPPED without them — either is an acceptable outcome for this task; do not fabricate credentials to force a pass.

- [ ] **Step 3: Run the entire test suite**

Run: `pytest -q`
Expected: same shape as before this plan (all previously-passing tests still pass) plus every new test from Tasks 1-9 passing or appropriately skipped without a real database/testnet.

- [ ] **Step 4: Run mypy on the touched strict-checked module**

Run: `mypy prometheus/validation/multiple_testing.py`
Expected: no new errors (Task 3's only change to a strict-checked file).

- [ ] **Step 5: Commit**

```bash
git add tests/test_paper_integration.py
git commit -m "test(paper): gated real-testnet integration check"
```

- [ ] **Step 6: Report per this project's CLAUDE.md convention**

State explicitly: what was built (five `paper/` modules, migration 0012, worker cadence-gating, MinTRL formula, Qubx evaluation), what was deliberately not built (no websocket/streaming execution — REST-poll only, matching the bounded-worker model; no automatic cost-model recalibration — the proposal is recorded, never auto-applied, per Law 7), what remains uncertain (real testnet fill behavior/latency until Task 11's integration test actually runs against live testnet — the 48h verification run from the spec's own "Verification" section is the next real-world check, not part of this plan), and the exact command to verify: `pytest -q && mypy prometheus/validation/`.

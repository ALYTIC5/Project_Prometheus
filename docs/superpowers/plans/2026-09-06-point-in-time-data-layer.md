# Point-in-Time Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the crypto-majors point-in-time data layer: structurally
enforced event_time/available_at separation, ccxt-based Binance
ingestion, universe reconstruction from listing/delisting history, data
versioning, and quality gating — then turn Law 1 (no look-ahead) and
Law 2 (no survivorship bias) from `xfail` stubs into real, passing tests.

**Architecture:** `prometheus/data/` owns five modules (`schema.py`,
`ingestion.py`, `universe.py`, `versioning.py`, `quality.py`) plus a
`models.py` for the four new ORM tables, all sharing
`prometheus.core.db.Base`'s metadata. The point-in-time guarantee is
structural: `PointInTimeFrame.as_of()` is the *only* read path feature
code gets, and its returned schema never contains `event_time` — not
filtered by convention, physically absent as a column. Polars (lazy)
does the dataframe work; pandas stays out of this layer entirely per
CLAUDE.md's stack (Polars for feature math).

**Tech Stack:** Polars (new dependency), ccxt (new dependency),
SQLAlchemy 2.x async (already in use), Alembic (already in use), pytest
+ pytest-asyncio (already in use).

**Spec:** `CLAUDE.md` (repo root) + `PROMPTS.md` PROMPT 1 (repo root) —
this plan implements PROMPT 1 only. PROMPT 0's plan (already executed,
22 commits through `9523b74`) established the `prometheus/` package
layout, the async DB engine/session pattern, and the law-test house
style this plan follows.

## Global Constraints

- Every price/feature row carries `event_time`, `available_at`,
  `ingested_at`, `source`, `revision`. `available_at` is the only one
  feature code may filter on — structurally enforced, not by convention.
- Ingestion is idempotent (re-running never duplicates), resumable,
  rate-limit aware, and writes raw responses to `raw_ingest` before any
  normalisation.
- Universe membership is reconstructed from `listed_at`/`delisted_at` in
  `universe_membership`, never from today's exchange listing. Seed data
  includes at least 5 delisted pairs.
- Every ingest run produces a `data_versions` row: content hash, row
  count, date range, source versions.
- Quality checks (gaps, duplicate timestamps, non-positive prices,
  impossible OHLC, volume spikes >20σ, stale bars) run on every ingest;
  failures quarantine the batch, never silently pass.
- `tests/laws/test_no_lookahead.py` and `tests/laws/test_survivorship.py`
  lose their `xfail` markers and become real. Following this repo's own
  established precedent from PROMPT 0 (`test_history_append_only.py`):
  a law test that is real code but genuinely needs infrastructure this
  sandbox doesn't have (a live Postgres seeded with universe data) is
  `skipif`-gated on `TEST_DATABASE_URL`, not `xfail` — `xfail` is
  reserved for laws whose guarded *code* doesn't exist yet.
  `test_no_lookahead.py` needs no DB at all (pure Polars, synthetic
  data) and must genuinely PASS locally with no gating.
- No mypy strict override applies to `prometheus/data/` (CLAUDE.md scopes
  strict to `core/` and `validation/` only) — ordinary (non-strict) mypy
  still applies repo-wide and must stay clean.
- No live network calls or live Postgres exist in this development
  sandbox. `python -m prometheus.data.ingestion --backfill --days 800`
  (PROMPT 1's second verify command) cannot actually be executed here —
  document this as a known, unavoidable environment limitation (same
  category as PROMPT 0's DB-dependent tests) rather than skip building
  the CLI correctly. Ingestion logic itself is unit-tested via a
  dependency-injected fake exchange client (an `ExchangeClient` Protocol
  ccxt's `Exchange` satisfies at runtime), so idempotency/parsing/
  quarantine logic still gets real, run test coverage without a network.
- Continuing directly on `master` (no new branch/worktree) — PROMPTS.md's
  own design is sequential, cumulative prompts building on each other in
  one repo, not independent feature branches to merge later. This
  matches the working pattern already established for PROMPT 0.
- Every new dependency gets a row in `docs/DEPENDENCIES.md`.

---

### Task 1: DB schema, universe seed data, and dependencies

**Files:**
- Create: `prometheus/data/models.py`
- Create: `alembic/versions/0004_data_layer_tables.py`
- Create: `config/universe.yaml`
- Modify: `pyproject.toml` (add `polars`, `ccxt` to `dependencies`)
- Modify: `docs/DEPENDENCIES.md` (add rows for `polars`, `ccxt`)

**Interfaces:**
- Produces: ORM models `RawIngest`, `OhlcvBar`, `UniverseMembership`,
  `DataVersion` (all on `prometheus.core.db.Base.metadata`); migration
  `0004` creating their tables with indexes matching the ORM exactly
  (learned from PROMPT 0's final review: get ORM/DDL type + index
  alignment right the first time, don't defer it).
- Downstream: Tasks 2-6 import these models; Tasks 7-8 seed/query
  `universe_membership` and `ohlcv_bars`.

- [ ] **Step 1: Check available `ccxt` and `polars` versions and pin exact ones**

```bash
source .venv/Scripts/activate
pip index versions polars 2>&1 | head -3
pip index versions ccxt 2>&1 | head -3
```
Pick the latest stable version each command reports (not a pre-release).
Do not guess a version number — use what's actually resolvable.

- [ ] **Step 2: Add the two dependencies to `pyproject.toml`**

Add to `dependencies = [...]` (alongside the existing pins), using the
exact versions resolved in Step 1:
```toml
    "polars==<resolved-version>",
    "ccxt==<resolved-version>",
```

- [ ] **Step 3: Install and confirm**

```bash
pip install -e . -q
python -c "import polars, ccxt; print(polars.__version__, ccxt.__version__)"
```

- [ ] **Step 4: Write `prometheus/data/models.py`**

```python
"""ORM models for the point-in-time data layer: raw exchange responses,
normalised OHLCV bars, universe membership history, and dataset
versioning. All share prometheus.core.db.Base's metadata.
"""
from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from prometheus.core.db import Base


class RawIngest(Base):
    __tablename__ = "raw_ingest"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(sa.String(32))
    symbol: Mapped[str] = mapped_column(sa.String(32))
    timeframe: Mapped[str] = mapped_column(sa.String(8))
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    quality_issues: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class OhlcvBar(Base):
    __tablename__ = "ohlcv_bars"
    __table_args__ = (
        sa.UniqueConstraint(
            "symbol", "timeframe", "event_time", "revision", name="uq_ohlcv_bar_revision"
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    timeframe: Mapped[str] = mapped_column(sa.String(8))
    event_time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    source: Mapped[str] = mapped_column(sa.String(32))
    revision: Mapped[int] = mapped_column(default=1)
    open: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    high: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    low: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    close: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    volume: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))


class UniverseMembership(Base):
    __tablename__ = "universe_membership"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    exchange: Mapped[str] = mapped_column(sa.String(32))
    listed_at: Mapped[date] = mapped_column(sa.Date)
    delisted_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)


class DataVersion(Base):
    __tablename__ = "data_versions"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    row_count: Mapped[int] = mapped_column(sa.BigInteger)
    date_range_start: Mapped[date] = mapped_column(sa.Date)
    date_range_end: Mapped[date] = mapped_column(sa.Date)
    source_versions: Mapped[dict[str, str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
```

- [ ] **Step 5: Write `alembic/versions/0004_data_layer_tables.py`**

```python
"""data layer tables: raw_ingest, ohlcv_bars, universe_membership, data_versions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_ingest",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("quality_issues", JSONB, nullable=True),
    )
    op.create_index("ix_raw_ingest_symbol_timeframe", "raw_ingest", ["symbol", "timeframe"])

    op.create_table(
        "ohlcv_bars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(28, 8), nullable=False),
        sa.UniqueConstraint(
            "symbol", "timeframe", "event_time", "revision", name="uq_ohlcv_bar_revision"
        ),
    )
    op.create_index(
        "ix_ohlcv_bars_symbol_timeframe_event_time", "ohlcv_bars", ["symbol", "timeframe", "event_time"]
    )
    op.create_index("ix_ohlcv_bars_available_at", "ohlcv_bars", ["available_at"])

    op.create_table(
        "universe_membership",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("listed_at", sa.Date, nullable=False),
        sa.Column("delisted_at", sa.Date, nullable=True),
    )
    op.create_index("ix_universe_membership_symbol", "universe_membership", ["symbol"])

    op.create_table(
        "data_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.BigInteger, nullable=False),
        sa.Column("date_range_start", sa.Date, nullable=False),
        sa.Column("date_range_end", sa.Date, nullable=False),
        sa.Column("source_versions", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("data_versions")
    op.drop_index("ix_universe_membership_symbol", table_name="universe_membership")
    op.drop_table("universe_membership")
    op.drop_index("ix_ohlcv_bars_available_at", table_name="ohlcv_bars")
    op.drop_index("ix_ohlcv_bars_symbol_timeframe_event_time", table_name="ohlcv_bars")
    op.drop_table("ohlcv_bars")
    op.drop_index("ix_raw_ingest_symbol_timeframe", table_name="raw_ingest")
    op.drop_table("raw_ingest")
```

- [ ] **Step 6: Write `config/universe.yaml`**

```yaml
# Universe seed data for Project Prometheus's crypto-majors universe.
# Membership is reconstructed as-of a historical date from listed_at/
# delisted_at, never from "what trades on Binance today" — Law 2.
#
# Dates below are best-effort approximations of real Binance spot
# listing/delisting history (public exchange announcements and
# community records). They are fixtures for survivorship-bias testing,
# not audited exchange records — treat as illustrative until
# cross-checked against Binance's own historical announcements before
# this matters for anything beyond testing the as_of() mechanism.
symbols:
  # --- currently active majors + liquid pairs ---
  - symbol: BTC/USDT
    exchange: binance
    listed_at: 2017-08-01
    delisted_at: null
  - symbol: ETH/USDT
    exchange: binance
    listed_at: 2017-08-01
    delisted_at: null
  - symbol: SOL/USDT
    exchange: binance
    listed_at: 2020-08-11
    delisted_at: null
  - symbol: BNB/USDT
    exchange: binance
    listed_at: 2017-11-06
    delisted_at: null
  - symbol: XRP/USDT
    exchange: binance
    listed_at: 2018-05-04
    delisted_at: null
  - symbol: ADA/USDT
    exchange: binance
    listed_at: 2018-04-25
    delisted_at: null
  - symbol: DOGE/USDT
    exchange: binance
    listed_at: 2019-07-05
    delisted_at: null
  - symbol: TRX/USDT
    exchange: binance
    listed_at: 2018-06-28
    delisted_at: null
  - symbol: DOT/USDT
    exchange: binance
    listed_at: 2020-08-19
    delisted_at: null
  - symbol: MATIC/USDT
    exchange: binance
    listed_at: 2019-04-26
    delisted_at: null
  - symbol: LTC/USDT
    exchange: binance
    listed_at: 2017-08-01
    delisted_at: null
  - symbol: AVAX/USDT
    exchange: binance
    listed_at: 2020-09-22
    delisted_at: null
  - symbol: LINK/USDT
    exchange: binance
    listed_at: 2019-01-16
    delisted_at: null
  - symbol: ATOM/USDT
    exchange: binance
    listed_at: 2019-04-29
    delisted_at: null
  - symbol: UNI/USDT
    exchange: binance
    listed_at: 2020-09-17
    delisted_at: null
  - symbol: XLM/USDT
    exchange: binance
    listed_at: 2018-05-31
    delisted_at: null
  - symbol: ETC/USDT
    exchange: binance
    listed_at: 2018-06-20
    delisted_at: null
  - symbol: FIL/USDT
    exchange: binance
    listed_at: 2020-10-15
    delisted_at: null
  - symbol: APT/USDT
    exchange: binance
    listed_at: 2022-10-19
    delisted_at: null
  - symbol: NEAR/USDT
    exchange: binance
    listed_at: 2020-10-14
    delisted_at: null

  # --- delisted / rebranded pairs, kept for survivorship-bias testing ---
  - symbol: BCHSV/USDT
    exchange: binance
    listed_at: 2018-12-14
    delisted_at: 2019-04-22
  - symbol: VEN/USDT
    exchange: binance
    listed_at: 2017-08-23
    delisted_at: 2018-07-23
  - symbol: LEND/USDT
    exchange: binance
    listed_at: 2018-01-22
    delisted_at: 2020-10-05
  - symbol: PAX/USDT
    exchange: binance
    listed_at: 2018-09-24
    delisted_at: 2021-05-01
  - symbol: SUSD/USDT
    exchange: binance
    listed_at: 2019-03-08
    delisted_at: 2019-11-15
```

- [ ] **Step 7: Add dependency rows to `docs/DEPENDENCIES.md`**

Add two rows (use the versions actually resolved in Step 1) to the
existing table:
```markdown
| polars | <resolved> | Feature math on OHLCV data; `PointInTimeFrame`'s lazy-frame `select()` is what makes `event_time` structurally droppable from feature code's view. | pandas for this layer | Lazy evaluation + explicit column selection make "this column doesn't exist for you" a real schema property, not a convention; pandas has no lazy frame. pandas stays at DB/ORM boundaries only, per CLAUDE.md's stack. |
| ccxt | <resolved> | Exchange data ingestion — Binance spot OHLCV. | Hand-rolled REST client + retry/rate-limit logic | Handles rate limiting, pagination, and exchange quirks across a uniform interface; we use only its Binance spot adapter. |
```

- [ ] **Step 8: Verify and commit**

```bash
mypy prometheus/data/models.py
python -c "from prometheus.data.models import RawIngest, OhlcvBar, UniverseMembership, DataVersion; print('ok')"
python -c "import yaml; d = yaml.safe_load(open('config/universe.yaml')); print(len(d['symbols']), 'symbols')"
git add prometheus/data/models.py alembic/versions/0004_data_layer_tables.py \
  config/universe.yaml pyproject.toml docs/DEPENDENCIES.md
git commit -m "feat(data): ORM models, migration, universe seed data, polars+ccxt deps"
```

---

### Task 2: `prometheus/data/schema.py` — the point-in-time accessor

**Files:**
- Create: `prometheus/data/schema.py`

**Interfaces:**
- Consumes: nothing new (pure Polars).
- Produces: `_REQUIRED_INPUT_COLUMNS` (tuple), `OHLCVBar` (frozen dataclass),
  `PointInTimeFrame` (class) with `.as_of(cutoff) -> pl.DataFrame` and
  `.visible_columns` — the returned frame never contains `event_time`.
- Downstream: Task 7 (`test_no_lookahead.py`) is the primary consumer;
  Task 6 (`ingestion.py`) constructs `OhlcvBar`-shaped dicts matching
  this schema's column names.

- [ ] **Step 1: Write `prometheus/data/schema.py`**

```python
"""Point-in-time OHLCV schema and the structurally-enforced accessor.

Every bar carries five extra fields beyond OHLCV: event_time (the bar's
own timestamp), available_at (when the bar became knowable — the ONLY
timestamp feature code may filter on), ingested_at (when we actually
pulled it), source, and revision (corrections are new rows with an
incremented revision, never an UPDATE — consistent with this repo's
append-only discipline elsewhere).

PointInTimeFrame is the only way feature code touches this data. Its
as_of() drops event_time from the returned schema entirely — not
filtered by convention, physically absent as a column.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

_REQUIRED_INPUT_COLUMNS = (
    "symbol", "timeframe", "event_time", "available_at", "open", "high", "low", "close", "volume",
)
_POINT_IN_TIME_COLUMNS = (
    "symbol", "timeframe", "available_at", "open", "high", "low", "close", "volume",
)


@dataclass(frozen=True)
class OHLCVBar:
    """One normalised bar. source/ingested_at/revision are storage
    bookkeeping, not feature-visible, so they're intentionally absent
    here too — this dataclass shapes what feature code ever sees.
    """

    symbol: str
    timeframe: str
    event_time: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class PointInTimeFrame:
    """Wraps OHLCV rows. `as_of(cutoff)` is the only read path feature
    code gets: filters on available_at, and the returned frame's schema
    never contains event_time.
    """

    def __init__(self, frame: pl.DataFrame | pl.LazyFrame) -> None:
        missing = set(_REQUIRED_INPUT_COLUMNS) - set(frame.collect_schema().names())
        if missing:
            raise ValueError(f"PointInTimeFrame is missing required columns: {sorted(missing)}")
        self._lf = frame.lazy()

    def as_of(self, cutoff: datetime) -> pl.DataFrame:
        return (
            self._lf.filter(pl.col("available_at") <= cutoff)
            .select(list(_POINT_IN_TIME_COLUMNS))
            .sort(["symbol", "available_at"])
            .collect()
        )

    @property
    def visible_columns(self) -> tuple[str, ...]:
        return _POINT_IN_TIME_COLUMNS
```

- [ ] **Step 2: Verify and commit**

```bash
source .venv/Scripts/activate
mypy prometheus/data/schema.py
python -c "
import polars as pl
from datetime import datetime, timezone
from prometheus.data.schema import PointInTimeFrame
df = pl.DataFrame({c: [] for c in ['symbol','timeframe','event_time','available_at','open','high','low','close','volume']})
pit = PointInTimeFrame(df)
out = pit.as_of(datetime.now(timezone.utc))
assert 'event_time' not in out.columns
print('ok')
"
git add prometheus/data/schema.py
git commit -m "feat(data): PointInTimeFrame — structurally enforced event_time exclusion"
```

---

### Task 3: `prometheus/data/quality.py`

**Files:**
- Create: `prometheus/data/quality.py`
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: a `pl.DataFrame` with `_REQUIRED_INPUT_COLUMNS`-shaped rows (Task 2).
- Produces: `QualityReport` (dataclass, `.issues: list[str]`,
  `.passed: bool`), `run_quality_checks(frame, timeframe) -> QualityReport`.
- Downstream: Task 6 (`ingestion.py`) calls `run_quality_checks` before
  normalising a batch.

- [ ] **Step 1: Write the failing tests `tests/test_quality.py`**

```python
"""Quality checks are pure functions over a Polars DataFrame — no DB
needed, fully testable offline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl

from prometheus.data.quality import run_quality_checks

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bar(symbol: str, hour: int, o: float, h: float, low: float, c: float, v: float) -> dict:
    event_time = _T0 + timedelta(hours=hour)
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "event_time": event_time,
        "available_at": event_time + timedelta(minutes=5),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": v,
    }


def test_clean_data_passes() -> None:
    rows = [_bar("BTC/USDT", i, 100 + i, 101 + i, 99 + i, 100.5 + i, 1000.0) for i in range(20)]
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert report.passed
    assert report.issues == []


def test_negative_price_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows[2]["close"] = -1.0
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("non-positive price" in issue for issue in report.issues)


def test_impossible_ohlc_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows[2]["high"] = 90.0  # high below low/open/close
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("impossible OHLC" in issue for issue in report.issues)


def test_duplicate_timestamp_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows.append(dict(rows[2]))  # exact duplicate
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("duplicate rows" in issue for issue in report.issues)


def test_gap_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows.append(_bar("BTC/USDT", 20, 100, 101, 99, 100, 1000.0))  # big jump from hour 4 to 20
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("gap" in issue for issue in report.issues)


def test_volume_spike_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(30)]
    rows[15]["volume"] = 10_000_000.0  # wildly beyond 20 sigma of a flat series
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("volume spike" in issue for issue in report.issues)
```

- [ ] **Step 2: Confirm it fails**

Run: `pytest tests/test_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.quality'`

- [ ] **Step 3: Write `prometheus/data/quality.py`**

```python
"""Quality checks run on every ingest: gaps, duplicate timestamps,
non-positive prices, impossible OHLC relationships, volume spikes,
stale bars. Failures quarantine the batch; they never silently pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

_BAR_HOURS = {"1h": 1, "4h": 4, "1d": 24}


@dataclass
class QualityReport:
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


def _expected_bar_hours(timeframe: str) -> int:
    if timeframe not in _BAR_HOURS:
        raise ValueError(f"unknown timeframe: {timeframe!r}")
    return _BAR_HOURS[timeframe]


def check_gaps(frame: pl.DataFrame, timeframe: str) -> list[str]:
    expected_hours = _expected_bar_hours(timeframe)
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol).sort("event_time")
        deltas = sub["event_time"].diff().drop_nulls()
        gap_count = (deltas.dt.total_hours() > expected_hours).sum()
        if gap_count:
            issues.append(f"{symbol}: {gap_count} gap(s) larger than one {timeframe} bar")
    return issues


def check_duplicate_timestamps(frame: pl.DataFrame) -> list[str]:
    dupes = (
        frame.group_by(["symbol", "timeframe", "event_time"])
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
    )
    return [
        f"{row['symbol']} {row['timeframe']} {row['event_time']}: {row['n']} duplicate rows"
        for row in dupes.iter_rows(named=True)
    ]


def check_price_validity(frame: pl.DataFrame) -> list[str]:
    bad = frame.filter(
        (pl.col("open") <= 0) | (pl.col("high") <= 0) | (pl.col("low") <= 0) | (pl.col("close") <= 0)
    )
    return [f"{row['symbol']} {row['event_time']}: non-positive price" for row in bad.iter_rows(named=True)]


def check_ohlc_relationships(frame: pl.DataFrame) -> list[str]:
    bad = frame.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
    )
    return [
        f"{row['symbol']} {row['event_time']}: impossible OHLC relationship "
        f"(O={row['open']} H={row['high']} L={row['low']} C={row['close']})"
        for row in bad.iter_rows(named=True)
    ]


def check_volume_spikes(frame: pl.DataFrame, sigma_threshold: float = 20.0) -> list[str]:
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol)
        mean = sub["volume"].mean()
        std = sub["volume"].std()
        if std is None or std == 0:
            continue
        spikes = sub.filter((pl.col("volume") - mean).abs() > sigma_threshold * std)
        if spikes.height:
            issues.append(f"{symbol}: {spikes.height} volume spike(s) beyond {sigma_threshold} sigma")
    return issues


def check_stale_bars(frame: pl.DataFrame) -> list[str]:
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol)
        stale = sub.filter(
            (pl.col("open") == pl.col("close"))
            & (pl.col("high") == pl.col("low"))
            & (pl.col("open") == pl.col("high"))
        )
        if stale.height > 1:
            issues.append(f"{symbol}: {stale.height} stale (zero-range) bar(s)")
    return issues


def run_quality_checks(frame: pl.DataFrame, timeframe: str) -> QualityReport:
    issues: list[str] = []
    issues += check_gaps(frame, timeframe)
    issues += check_duplicate_timestamps(frame)
    issues += check_price_validity(frame)
    issues += check_ohlc_relationships(frame)
    issues += check_volume_spikes(frame)
    issues += check_stale_bars(frame)
    return QualityReport(issues=issues)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_quality.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
mypy prometheus/data/quality.py
git add prometheus/data/quality.py tests/test_quality.py
git commit -m "feat(data): quality checks — gaps, duplicates, price validity, OHLC, volume spikes, stale bars"
```

---

### Task 4: `prometheus/data/versioning.py`

**Files:**
- Create: `prometheus/data/versioning.py`
- Test: `tests/test_versioning.py`

**Interfaces:**
- Consumes: `prometheus.data.models.DataVersion` (Task 1).
- Produces: `compute_content_hash(frame: pl.DataFrame) -> str`,
  `async record_data_version(session, frame, date_range_start, date_range_end, source_versions) -> DataVersion`.
- Downstream: Task 6 (`ingestion.py`) calls `record_data_version` after
  a successful backfill run.

- [ ] **Step 1: Write the failing tests `tests/test_versioning.py`**

```python
"""compute_content_hash is a pure function — testable offline.
record_data_version needs a session; tested here with a lightweight
async mock (no real DB), matching the pattern in tests/test_research_policy.py.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import polars as pl
import pytest

from prometheus.data.versioning import compute_content_hash, record_data_version


def _frame(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["BTC/USDT"] * len(closes),
            "timeframe": ["1h"] * len(closes),
            "event_time": [datetime(2024, 1, 1, tzinfo=timezone.utc)] * len(closes),
            "close": closes,
        }
    )


def test_content_hash_deterministic() -> None:
    assert compute_content_hash(_frame([1.0, 2.0, 3.0])) == compute_content_hash(_frame([1.0, 2.0, 3.0]))


def test_content_hash_sensitive_to_content() -> None:
    assert compute_content_hash(_frame([1.0, 2.0, 3.0])) != compute_content_hash(_frame([1.0, 2.0, 3.1]))


def test_content_hash_is_sha256_hex() -> None:
    h = compute_content_hash(_frame([1.0]))
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex


@pytest.mark.asyncio
async def test_record_data_version_adds_and_flushes() -> None:
    session = AsyncMock()
    version = await record_data_version(
        session,
        _frame([1.0, 2.0, 3.0]),
        date_range_start=date(2024, 1, 1),
        date_range_end=date(2024, 1, 2),
        source_versions={"binance": "spot-v3"},
    )
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert version.row_count == 3
    assert version.date_range_start == date(2024, 1, 1)
```

- [ ] **Step 2: Confirm it fails**

Run: `pytest tests/test_versioning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.versioning'`

- [ ] **Step 3: Write `prometheus/data/versioning.py`**

```python
"""Every ingest run produces a data_version row: content hash, row
count, date range, source versions. Backtests reference a data_version
and can be replayed against it.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from prometheus.data.models import DataVersion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def compute_content_hash(frame: pl.DataFrame) -> str:
    """Deterministic hash of a dataset's content: sorted (symbol,
    timeframe, event_time, close) tuples, so two datasets with identical
    bars hash identically regardless of row order.
    """
    canonical = frame.select(["symbol", "timeframe", "event_time", "close"]).sort(
        ["symbol", "timeframe", "event_time"]
    )
    raw = canonical.write_csv()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_data_version(
    session: "AsyncSession",
    frame: pl.DataFrame,
    date_range_start: date,
    date_range_end: date,
    source_versions: dict[str, str],
) -> DataVersion:
    version = DataVersion(
        content_hash=compute_content_hash(frame),
        row_count=frame.height,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        source_versions=source_versions,
    )
    session.add(version)
    await session.flush()
    return version
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_versioning.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
mypy prometheus/data/versioning.py
git add prometheus/data/versioning.py tests/test_versioning.py
git commit -m "feat(data): data_version recording with deterministic content hashing"
```

---

### Task 5: `prometheus/data/universe.py`

**Files:**
- Create: `prometheus/data/universe.py`

**Interfaces:**
- Consumes: `prometheus.data.models.UniverseMembership` (Task 1).
- Produces: `async as_of(session, as_of_date: date) -> list[str]`.
- Downstream: Task 8 (`test_survivorship.py`) is the primary consumer.

- [ ] **Step 1: Write `prometheus/data/universe.py`**

```python
"""Universe reconstruction — Law 2. Membership as of a date comes ONLY
from universe_membership's listed_at/delisted_at, never from today's
exchange listing.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.models import UniverseMembership


async def as_of(session: AsyncSession, as_of_date: date) -> list[str]:
    stmt = select(UniverseMembership.symbol).where(
        UniverseMembership.listed_at <= as_of_date,
        (UniverseMembership.delisted_at.is_(None)) | (UniverseMembership.delisted_at > as_of_date),
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
```

- [ ] **Step 2: Verify and commit**

```bash
mypy prometheus/data/universe.py
python -c "from prometheus.data.universe import as_of; print('ok')"
git add prometheus/data/universe.py
git commit -m "feat(data): as_of() universe reconstruction from listing/delisting history"
```

*(A DB-backed integration test for `as_of()` lands in Task 8 —
`test_survivorship.py` IS that test; a separate unit test here would just
duplicate it.)*

---

### Task 6: `prometheus/data/ingestion.py` — ccxt Binance adapter + CLI

**Files:**
- Create: `prometheus/data/ingestion.py`
- Test: `tests/test_ingestion.py`

**Interfaces:**
- Consumes: `run_quality_checks` (Task 3), `record_data_version`
  (Task 4), `RawIngest`/`OhlcvBar` shape (Task 1),
  `prometheus.core.db.get_session` (existing).
- Produces: `ExchangeClient` (Protocol), `load_universe_symbols(path) -> list[str]`,
  `ccxt_rows_to_bars(raw_rows, symbol, timeframe, source) -> list[dict]`,
  `async ingest_symbol(session, exchange, symbol, timeframe, since, source="binance") -> None`,
  `async backfill(days, symbols=None) -> None`, CLI `main()`.
- Downstream: none within this plan — this is the terminal consumer.

- [ ] **Step 1: Write the failing tests `tests/test_ingestion.py`**

```python
"""Ingestion logic is tested via a fake exchange client (the
ExchangeClient Protocol ccxt's real Exchange also satisfies) — no
network needed. DB-touching behavior (idempotency via the unique
constraint, actual inserts) needs a live Postgres and is out of scope
for this offline suite; the pure parsing/format logic below is not.
"""
from __future__ import annotations

from datetime import datetime, timezone

from prometheus.data.ingestion import ccxt_rows_to_bars, load_universe_symbols


def test_load_universe_symbols_excludes_delisted() -> None:
    symbols = load_universe_symbols("config/universe.yaml")
    assert "BTC/USDT" in symbols
    assert "BCHSV/USDT" not in symbols  # delisted, excluded from the active backfill list
    assert len(symbols) >= 15


def test_ccxt_rows_to_bars_shapes_and_lags_correctly() -> None:
    ts_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    raw_rows = [[ts_ms, 100.0, 101.0, 99.0, 100.5, 1234.0]]

    bars = ccxt_rows_to_bars(raw_rows, "BTC/USDT", "1h", "binance")

    assert len(bars) == 1
    bar = bars[0]
    assert bar["symbol"] == "BTC/USDT"
    assert bar["timeframe"] == "1h"
    assert bar["source"] == "binance"
    assert bar["revision"] == 1
    assert bar["event_time"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert bar["available_at"] > bar["event_time"]  # ingestion lag applied
    assert bar["open"] == 100.0 and bar["close"] == 100.5
```

- [ ] **Step 2: Confirm it fails**

Run: `pytest tests/test_ingestion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.ingestion'`

- [ ] **Step 3: Write `prometheus/data/ingestion.py`**

```python
"""ccxt-based Binance spot OHLCV ingestion. Idempotent via
INSERT ... ON CONFLICT DO NOTHING against ohlcv_bars' unique
(symbol, timeframe, event_time, revision) constraint — re-running never
duplicates. Rate-limit aware via ccxt's own throttling. Writes raw
responses to raw_ingest before any normalisation.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import polars as pl
import yaml
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import get_session
from prometheus.data.quality import run_quality_checks
from prometheus.data.versioning import record_data_version

_TIMEFRAMES = ("1d", "4h")
_INGESTION_LAG = timedelta(minutes=5)

# `expanding=True` lets SQLAlchemy safely bind a Python list against an
# IN clause — the plain-string `ANY(:symbols)` form does not reliably
# adapt a list parameter through text() across dialects.
_SELECT_BARS_FOR_VERSIONING = text(
    """
    SELECT symbol, timeframe, event_time, close
    FROM ohlcv_bars
    WHERE symbol IN :symbols AND event_time >= :since
    """
).bindparams(sa.bindparam("symbols", expanding=True))

_INSERT_RAW = text(
    """
    INSERT INTO raw_ingest (source, symbol, timeframe, payload, status)
    VALUES (:source, :symbol, :timeframe, :payload, 'pending')
    RETURNING id
    """
)

_INSERT_BAR = text(
    """
    INSERT INTO ohlcv_bars
        (symbol, timeframe, event_time, available_at, ingested_at, source, revision,
         open, high, low, close, volume)
    VALUES
        (:symbol, :timeframe, :event_time, :available_at, now(), :source, :revision,
         :open, :high, :low, :close, :volume)
    ON CONFLICT ON CONSTRAINT uq_ohlcv_bar_revision DO NOTHING
    """
)

_UPDATE_RAW_STATUS = text(
    "UPDATE raw_ingest SET status = :status, quality_issues = :quality_issues WHERE id = :id"
)


class ExchangeClient(Protocol):
    """The ccxt subset this module uses. Real ccxt.binance() satisfies
    this at runtime; tests inject a fake.
    """

    rateLimit: int

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int = 1000
    ) -> list[list[float]]: ...


def load_universe_symbols(path: str = "config/universe.yaml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [row["symbol"] for row in data["symbols"] if row.get("delisted_at") is None]


def ccxt_rows_to_bars(
    raw_rows: list[list[float]], symbol: str, timeframe: str, source: str
) -> list[dict[str, Any]]:
    """ccxt's fetch_ohlcv rows are [timestamp_ms, open, high, low, close,
    volume]. available_at = event_time + a fixed ingestion lag: the bar
    isn't knowable until it closes plus the time an exchange takes to
    serve it. This is the one place that lag is decided.
    """
    bars = []
    for ts_ms, o, h, low, c, v in raw_rows:
        event_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        bars.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "event_time": event_time,
                "available_at": event_time + _INGESTION_LAG,
                "source": source,
                "revision": 1,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
            }
        )
    return bars


async def ingest_symbol(
    session: AsyncSession,
    exchange: ExchangeClient,
    symbol: str,
    timeframe: str,
    since: datetime,
    source: str = "binance",
) -> None:
    since_ms = int(since.timestamp() * 1000)
    raw_rows = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
    raw_id = (
        await session.execute(
            _INSERT_RAW,
            {"source": source, "symbol": symbol, "timeframe": timeframe, "payload": {"rows": raw_rows}},
        )
    ).scalar_one()

    if not raw_rows:
        await session.execute(
            _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
        )
        await session.commit()
        return

    bars = ccxt_rows_to_bars(raw_rows, symbol, timeframe, source)
    frame = pl.DataFrame(bars)
    report = run_quality_checks(frame, timeframe)

    if not report.passed:
        await session.execute(
            _UPDATE_RAW_STATUS,
            {"status": "quarantined", "quality_issues": {"issues": report.issues}, "id": raw_id},
        )
        await session.commit()
        return

    for bar in bars:
        await session.execute(_INSERT_BAR, bar)
    await session.execute(
        _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
    )
    await session.commit()


async def _load_bars_for_versioning(
    session: AsyncSession, symbols: list[str], since: datetime
) -> pl.DataFrame:
    result = await session.execute(_SELECT_BARS_FOR_VERSIONING, {"symbols": symbols, "since": since})
    rows = result.mappings().all()
    return pl.DataFrame(
        {
            "symbol": [r["symbol"] for r in rows],
            "timeframe": [r["timeframe"] for r in rows],
            "event_time": [r["event_time"] for r in rows],
            "close": [float(r["close"]) for r in rows],
        }
    )


async def backfill(days: int, symbols: list[str] | None = None) -> None:
    import ccxt

    exchange = ccxt.binance()
    exchange.enableRateLimit = True
    symbols = symbols or load_universe_symbols()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with get_session() as session:
        for symbol in symbols:
            for timeframe in _TIMEFRAMES:
                await ingest_symbol(session, exchange, symbol, timeframe, since)
                await asyncio.sleep(exchange.rateLimit / 1000)

        # Law-adjacent requirement: every ingest run produces a
        # data_version row, not just the ones that happened to insert
        # new bars — this run's dataset is "everything in the backfilled
        # window for these symbols", read back rather than accumulated
        # in memory across the loop above (simpler, and correct even if
        # some bars pre-existed from an earlier run).
        frame = await _load_bars_for_versioning(session, symbols, since)
        if frame.height:
            await record_data_version(
                session,
                frame,
                date_range_start=since.date(),
                date_range_end=datetime.now(timezone.utc).date(),
                source_versions={"binance": "ccxt/" + ccxt.__version__},
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest OHLCV data for the crypto-majors universe.")
    parser.add_argument("--backfill", action="store_true", help="run a historical backfill")
    parser.add_argument("--days", type=int, default=800, help="how many days of history to backfill")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.backfill:
        asyncio.run(backfill(args.days))
    else:
        raise SystemExit("nothing to do — pass --backfill")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_ingestion.py -v`
Expected: 2 passed

- [ ] **Step 5: Verify the CLI is at least invokable (no network call triggered by --help)**

```bash
python -m prometheus.data.ingestion --help
```
Expected: argparse help text, exit 0. Do NOT run `--backfill` for real —
there is no network access or live Postgres in this environment; running
it would hang or fail on a connection attempt, not prove anything.

- [ ] **Step 6: Commit**

```bash
mypy prometheus/data/ingestion.py
git add prometheus/data/ingestion.py tests/test_ingestion.py
git commit -m "feat(data): ccxt Binance ingestion, idempotent via ON CONFLICT, CLI backfill entrypoint"
```

---

### Task 7: `tests/laws/test_no_lookahead.py` — real implementation

**Files:**
- Modify: `tests/laws/test_no_lookahead.py` (currently an `xfail` stub
  from PROMPT 0 — replace entirely)

**Interfaces:**
- Consumes: `prometheus.data.schema.PointInTimeFrame`, `_REQUIRED_INPUT_COLUMNS` (Task 2).

- [ ] **Step 1: Replace `tests/laws/test_no_lookahead.py` with the real implementation**

```python
"""Law 1: no look-ahead. A strategy sees only data whose available_at is
at or before the decision timestamp. PointInTimeFrame.as_of() is the
mechanism; these tests prove it holds under adversarial and randomised
conditions, not just on a hand-picked example. No DB needed — pure
Polars, synthetic data, runs everywhere.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import polars as pl

from prometheus.data.schema import PointInTimeFrame

_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
_N_BARS = 500


def _synthetic_frame(planted_future_marker: float | None = None) -> pl.DataFrame:
    rows = []
    rng = random.Random(1)
    for symbol in _SYMBOLS:
        price = 100.0
        for i in range(_N_BARS):
            event_time = _START + timedelta(hours=i)
            available_at = event_time + timedelta(minutes=5)  # realistic ingestion lag
            price *= 1 + rng.uniform(-0.01, 0.01)
            close = price
            if planted_future_marker is not None and i == _N_BARS - 1:
                close = planted_future_marker
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": "1h",
                    "event_time": event_time,
                    "available_at": available_at,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(rows)


def test_planted_future_value_is_unreachable() -> None:
    marker = 999_999.0
    frame = _synthetic_frame(planted_future_marker=marker)
    pit = PointInTimeFrame(frame)
    cutoff = _START + timedelta(hours=_N_BARS - 10)  # well before the planted bar

    visible = pit.as_of(cutoff)

    assert "event_time" not in visible.columns
    assert marker not in visible["close"].to_list()
    assert (visible["available_at"] <= cutoff).all()


def _rolling_mean_feature(df: pl.DataFrame, window: int = 10) -> pl.DataFrame:
    """A representative feature: trailing rolling mean of close, grouped
    per symbol. Uses Polars' trailing (not centred) rolling_mean, which
    only looks backward — the thing a leaky implementation would get wrong.
    """
    return df.sort(["symbol", "available_at"]).with_columns(
        pl.col("close").rolling_mean(window).over("symbol").alias("feature")
    )


def test_truncation_proof_across_random_sample() -> None:
    """For 200 random (symbol, cutoff) pairs, features computed via
    as_of(cutoff) on the full dataset must be identical to features
    computed on a dataset physically truncated at cutoff before feature
    computation. Any difference means data from beyond the cutoff
    reached the feature — the single most valuable test in this repo.
    """
    frame = _synthetic_frame()
    pit = PointInTimeFrame(frame)
    rng = random.Random(20260906)

    samples = [
        (rng.choice(_SYMBOLS), _START + timedelta(hours=rng.randint(50, _N_BARS - 1)))
        for _ in range(200)
    ]

    for symbol, cutoff in samples:
        visible_via_accessor = pit.as_of(cutoff).filter(pl.col("symbol") == symbol)
        features_from_accessor = _rolling_mean_feature(visible_via_accessor)

        # Ground truth: filter the SOURCE frame (still has event_time, no
        # accessor involved) to what a physically truncated dataset would
        # contain, independent of PointInTimeFrame's own logic.
        truncated_source = (
            frame.filter((pl.col("symbol") == symbol) & (pl.col("available_at") <= cutoff))
            .select(list(pit.visible_columns))
            .sort(["symbol", "available_at"])
        )
        features_from_truncated = _rolling_mean_feature(truncated_source)

        assert features_from_accessor.equals(features_from_truncated), (
            f"feature mismatch for {symbol} at cutoff={cutoff}: as_of() leaked "
            f"or dropped data relative to a physically truncated dataset"
        )
```

- [ ] **Step 2: Run, confirm real pass (no xfail)**

Run: `pytest tests/laws/test_no_lookahead.py -v`
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
mypy prometheus/data/schema.py  # unchanged, sanity check only
git add tests/laws/test_no_lookahead.py
git commit -m "test(laws): Law 1 real implementation — planted-future-value + 200-sample truncation proof"
```

---

### Task 8: `tests/laws/test_survivorship.py` — real implementation

**Files:**
- Modify: `tests/laws/test_survivorship.py` (currently an `xfail` stub
  from PROMPT 0 — replace entirely)

**Interfaces:**
- Consumes: `prometheus.data.universe.as_of` (Task 5), `config/universe.yaml` (Task 1).

- [ ] **Step 1: Replace `tests/laws/test_survivorship.py` with the real implementation**

```python
"""Law 2: no survivorship bias. Universe membership is reconstructed
from listing/delisting dates, never from "what's listed today". A
universe query for a past date must include symbols that have since
been delisted.

Requires a live Postgres with migrations applied and config/universe.yaml
seeded into universe_membership. Skipped (not xfail — missing
infrastructure, not missing code) when TEST_DATABASE_URL isn't set, same
pattern as tests/laws/test_history_append_only.py from PROMPT 0.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prometheus.data.universe import as_of

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations applied)",
)

_UNIVERSE_YAML = "config/universe.yaml"

_INSERT_MEMBERSHIP = text(
    """
    INSERT INTO universe_membership (symbol, exchange, listed_at, delisted_at)
    VALUES (:symbol, :exchange, :listed_at, :delisted_at)
    """
)


@pytest.fixture()
async def seeded_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    with open(_UNIVERSE_YAML, encoding="utf-8") as f:
        symbols = yaml.safe_load(f)["symbols"]

    async with engine.begin() as conn:
        for row in symbols:
            await conn.execute(_INSERT_MEMBERSHIP, row)

    factory = async_sessionmaker(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_universe_as_of_2021_includes_a_since_delisted_symbol(
    seeded_session: AsyncSession,
) -> None:
    symbols_2021 = set(await as_of(seeded_session, date(2021, 1, 1)))
    symbols_today = set(await as_of(seeded_session, date.today()))

    # PAX/USDT: listed 2018-09-24, delisted 2021-05-01 — alive as of
    # 2021-01-01, dead today. This is the case Law 2 exists to catch.
    assert "PAX/USDT" in symbols_2021
    assert "PAX/USDT" not in symbols_today

    # LEND/USDT: delisted 2020-10-05, already dead before the query
    # date — must be absent from BOTH, proving delisted_at is a hard
    # boundary and not just "ever delisted -> always shown".
    assert "LEND/USDT" not in symbols_2021
    assert "LEND/USDT" not in symbols_today

    assert "BTC/USDT" in symbols_2021
    assert "BTC/USDT" in symbols_today
```

- [ ] **Step 2: Run locally, confirm skipped (no `TEST_DATABASE_URL` here)**

Run: `pytest tests/laws/test_survivorship.py -v`
Expected: 1 skipped

- [ ] **Step 3: Commit**

```bash
git add tests/laws/test_survivorship.py
git commit -m "test(laws): Law 2 real implementation — as_of() survivorship, DB-gated like test_history_append_only.py"
```

---

### Task 9: Full verification pass and CI update

**Files:**
- Modify: `.github/workflows/ci.yml` (the `laws` job needs
  `pip install -e .` to now also pull `polars`/`ccxt`, already automatic
  via `pip install -e ".[dev]"` — no change needed there; but confirm the
  job's Postgres-seeded run would actually exercise
  `test_survivorship.py` and the new TRUNCATE-adjacent tests correctly,
  i.e. migrations run through `0004` before the law tests run)

- [ ] **Step 1: Run the exact PROMPT 1 verify commands**

```bash
source .venv/Scripts/activate
pytest tests/laws/ -v
ruff check .
mypy prometheus/core/
mypy prometheus/data/
```
Expected: `test_no_lookahead.py` 2 passed (real), `test_survivorship.py`
1 skipped (real code, DB-gated — will pass in CI), all previously-passing
law tests unchanged, 0 failed. ruff clean. mypy clean on both `core/`
(strict) and `data/` (ordinary).

```bash
pytest tests/ -v
```
Expected: all data-layer unit tests (Tasks 3, 4, 6) pass; whole suite green.

- [ ] **Step 2: Confirm the CLI is documented as environment-limited**

Verify `alembic upgrade head` would apply `0004` cleanly by inspecting
the migration chain (no live DB to actually run it against):
```bash
python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
script = ScriptDirectory.from_config(cfg)
print([rev.revision for rev in script.walk_revisions()])
"
```
Expected: `['0004', '0003', '0002', '0001']` (walked newest-first).

- [ ] **Step 3: Fix anything Step 1 surfaces**

Fix real issues in source files (no `# noqa`/`# type: ignore`/config
weakening), re-run until clean — same discipline as PROMPT 0's Task 9.

- [ ] **Step 4: Commit if Step 3 required changes**

```bash
git add -A
git commit -m "fix: address issues from PROMPT 1 full verify pass"
```

---

## What this plan deliberately does not build

- No feature/signal computation beyond the illustrative rolling-mean
  used to prove the truncation property (that's PROMPT 2's
  `strategy/dsl.py`).
- No live backfill run — no network access or live Postgres exists in
  this environment. The CLI is built and unit-tested via a fake exchange
  client; an actual `python -m prometheus.data.ingestion --backfill
  --days 800` run against real Binance + real Postgres is left for
  whoever has that infrastructure (e.g. CI or a real deployment).
- No equity/yfinance adapter — CLAUDE.md's PROMPT 1 text explicitly
  rules this out (survivorship-biased, split-adjusted-in-place data
  would silently violate Laws 1 and 2).
- No revision/correction workflow beyond the schema supporting it
  (`revision` column, unique constraint per revision) — actually
  *using* revision > 1 to correct a bad bar is not exercised here.

## Uncertain / worth flagging

- `config/universe.yaml`'s listing/delisting dates are best-effort
  approximations from public knowledge, not verified against Binance's
  own historical announcements — fine for testing the `as_of()`
  mechanism, not fine as a source of truth for anything touching real
  capital later.
- The ingestion lag (`_INGESTION_LAG = timedelta(minutes=5)`) is a
  placeholder engineering choice, not a researched value — flagging per
  CLAUDE.md's "ask rather than invent a threshold" instinct, though this
  is an operational parameter (how long until a bar is considered safe
  to read) rather than a validation/research threshold, so it's a
  judgment call, not a Law violation. Revisit once real ingestion
  latency is observed.

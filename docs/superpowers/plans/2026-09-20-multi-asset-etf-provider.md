# Multi-Asset Data Provider Abstraction + ETF Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second, non-crypto asset class (ETFs/indices, via Alpaca) to
the point-in-time data layer, without touching the crypto ingestion path,
by introducing a small `MarketDataProvider` abstraction that a future
sub-project will migrate crypto onto.

**Architecture:** One new abstract interface (`MarketDataProvider`) with one
real implementation (`AlpacaProvider`) and one unimplemented stub
(`StockProvider`). A new, self-contained orchestration function
(`ingest_etf.backfill_etf`) fetches raw bars from the provider, then reuses
the *existing* quality-check, holdout-split, and versioning machinery,
with one small backward-compatible extension to `check_gaps()` (crypto's
24/7-market gap threshold would otherwise quarantine every real ETF
ingestion on its first weekend). `universe_membership` gains an `asset_class` column so the two
asset classes' universes never mix.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x async, Alembic, `httpx` (already
a dependency — no new one added), pytest + pytest-asyncio, Polars.

**Spec:** `docs/superpowers/specs/2026-09-20-multi-asset-data-provider-abstraction-design.md`

## Global Constraints

- Zero new dependencies — `httpx` (already in `pyproject.toml`) covers
  Alpaca's plain-JSON REST API.
- `ingestion.py` (crypto/ccxt path) is not modified in this plan — reuse its
  module-level query constants by import where useful, never edit its body.
- `adjustment=raw` is always passed explicitly to Alpaca, never relied on as
  an implicit default.
- `as_of()`/`sync_from_yaml()` take `asset_class` as a **required**
  parameter, not optional-with-a-default — every existing call site must be
  updated in the same task that changes the signature.
- `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` are read from `os.environ` inside the
  function that needs them, never at module import time (matches
  `worker._anthropic_client()`'s existing posture — importing a module must
  never require a real credential to be set).
- mypy strict applies to everything under `data/` per CLAUDE.md's `core/`
  and `validation/` rule extended by precedent — this codebase already runs
  the existing `data/` modules through mypy cleanly; new code must too.

---

### Task 1: `universe_membership` gains `asset_class`

**Files:**
- Create: `alembic/versions/0014_universe_asset_class.py`
- Modify: `prometheus/data/models.py` (`UniverseMembership` class, ~line 61-69)
- Modify: `prometheus/data/universe.py` (whole file, 59 lines)
- Modify: `prometheus/data/ingestion.py:236` (the one `sync_from_yaml()` call site, inside `backfill()`)
- Modify: `tests/laws/test_survivorship.py` (existing `as_of()`/`sync_from_yaml()` calls + one new test)
- Test: `tests/laws/test_survivorship.py`

**Interfaces:**
- Produces: `data.universe.as_of(session, as_of_date, asset_class: str) -> list[str]`
- Produces: `data.universe.sync_from_yaml(session, path, asset_class: str) -> int`
- Consumes: `prometheus.data.models.UniverseMembership` (adds `asset_class: Mapped[str]`)

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/0014_universe_asset_class.py
"""universe_membership.asset_class -- Law 2's as_of() must be able to
reconstruct one asset class's universe without mixing in another's.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-20

DEFAULT 'crypto' exists only to backfill every existing row (all of
today's universe_membership is crypto) without a manual data migration
step; dropped immediately after so future inserts must specify it
explicitly -- same "no invented default that silently hides a real
decision" posture as next_strategy_id's explicit family validation.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "universe_membership",
        sa.Column("asset_class", sa.String(16), nullable=False, server_default="crypto"),
    )
    op.alter_column("universe_membership", "asset_class", server_default=None)


def downgrade() -> None:
    op.drop_column("universe_membership", "asset_class")
```

- [ ] **Step 2: Update the ORM model**

In `prometheus/data/models.py`, `UniverseMembership` (currently lines 61-69):

```python
class UniverseMembership(Base):
    __tablename__ = "universe_membership"
    __table_args__ = (sa.Index("ix_universe_membership_symbol", "symbol"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    exchange: Mapped[str] = mapped_column(sa.String(32))
    asset_class: Mapped[str] = mapped_column(sa.String(16))
    listed_at: Mapped[date] = mapped_column(sa.Date)
    delisted_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
```

(Only change: the new `asset_class: Mapped[str] = mapped_column(sa.String(16))` line, inserted after `exchange`.)

- [ ] **Step 3: Rewrite `data/universe.py`**

```python
"""Universe reconstruction — Law 2. Membership as of a date comes ONLY
from universe_membership's listed_at/delisted_at, never from today's
exchange listing. asset_class is required on every call -- a caller
that forgot to specify one would otherwise silently see both crypto and
ETF symbols mixed in one list.
"""
from __future__ import annotations

from datetime import date

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.models import UniverseMembership

_DEFAULT_UNIVERSE_YAML = "config/universe.yaml"

_UPSERT_MEMBERSHIP = text(
    """
    INSERT INTO universe_membership (symbol, exchange, asset_class, listed_at, delisted_at)
    VALUES (:symbol, :exchange, :asset_class, :listed_at, :delisted_at)
    ON CONFLICT ON CONSTRAINT uq_universe_membership_symbol_exchange_listed_at
    DO UPDATE SET delisted_at = EXCLUDED.delisted_at, asset_class = EXCLUDED.asset_class
    """
)


async def as_of(session: AsyncSession, as_of_date: date, asset_class: str) -> list[str]:
    stmt = select(UniverseMembership.symbol).where(
        UniverseMembership.asset_class == asset_class,
        UniverseMembership.listed_at <= as_of_date,
        (UniverseMembership.delisted_at.is_(None)) | (UniverseMembership.delisted_at > as_of_date),
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def sync_from_yaml(
    session: AsyncSession, path: str = _DEFAULT_UNIVERSE_YAML, *, asset_class: str
) -> int:
    """Upserts every symbol in `path` (delisted ones included -- as_of()
    needs those too, unlike ingestion.load_universe_symbols()'s current-
    ingest-list filter) into universe_membership, keyed on (symbol,
    exchange, listed_at). Idempotent: re-running against an unchanged file
    touches every row but changes nothing. Returns the number of rows
    upserted."""
    with open(path, encoding="utf-8") as f:
        rows = yaml.safe_load(f)["symbols"]
    for row in rows:
        await session.execute(
            _UPSERT_MEMBERSHIP,
            {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "asset_class": asset_class,
                "listed_at": row["listed_at"],
                "delisted_at": row.get("delisted_at"),
            },
        )
    return len(rows)
```

(`asset_class` is keyword-only on `sync_from_yaml` since `path` already has
a default and Python doesn't allow a non-default positional after one —
keyword-only reads clearly at every call site too: `sync_from_yaml(session, asset_class="crypto")`.)

- [ ] **Step 4: Update `ingestion.py`'s call site**

`prometheus/data/ingestion.py:236` currently reads (inside `backfill()`):
```python
        await sync_from_yaml(session)
```
Change to:
```python
        await sync_from_yaml(session, asset_class="crypto")
```

- [ ] **Step 5: Update `test_survivorship.py`'s existing calls and add the new isolation test**

```python
# tests/laws/test_survivorship.py -- full replacement
"""Law 2: no survivorship bias. Universe membership is reconstructed
from listing/delisting dates, never from "what's listed today". A
universe query for a past date must include symbols that have since
been delisted.

Requires a live Postgres with migrations applied and config/universe.yaml
seeded into universe_membership. Skipped (not xfail — missing
infrastructure, not missing code) when TEST_DATABASE_URL isn't set, same
pattern as tests/laws/test_history_append_only.py from PROMPT 0.

Seeding goes through data.universe.sync_from_yaml() -- not a hand-rolled
INSERT -- for two reasons: it's the real production path (PROMPT 2), and
its upsert-on-(symbol, exchange, listed_at) is what makes this fixture
safe to run repeatedly against a database another test (or this test
itself, on a prior run) already seeded, now that migration 0009's unique
constraint exists. A bare INSERT here would collide with it.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prometheus.data.universe import as_of, sync_from_yaml

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations applied)",
)

_UNIVERSE_YAML = "config/universe.yaml"


@pytest.fixture()
async def seeded_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine)
    async with factory() as session:
        await sync_from_yaml(session, _UNIVERSE_YAML, asset_class="crypto")
        await session.commit()
        yield session
    await engine.dispose()


async def test_universe_as_of_2021_includes_a_since_delisted_symbol(
    seeded_session: AsyncSession,
) -> None:
    symbols_2021 = set(await as_of(seeded_session, date(2021, 1, 1), "crypto"))
    symbols_today = set(await as_of(seeded_session, date.today(), "crypto"))

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


async def test_as_of_never_mixes_asset_classes(seeded_session: AsyncSession) -> None:
    """PROMPT 2 (multi-asset): an asset_class filter that silently did
    nothing would let an ETF symbol leak into a crypto strategy's
    universe (or vice versa) the moment a second asset class exists in
    the same table. Seeds one ETF row directly (no ETF adapter exists
    yet in this sub-project) to prove the filter itself works before
    anything real depends on it."""
    await sync_from_yaml(
        seeded_session, "tests/fixtures/universe_etf_sample.yaml", asset_class="etf"
    )
    await seeded_session.commit()

    crypto_symbols = set(await as_of(seeded_session, date.today(), "crypto"))
    etf_symbols = set(await as_of(seeded_session, date.today(), "etf"))

    assert "SPY" in etf_symbols
    assert "SPY" not in crypto_symbols
    assert "BTC/USDT" in crypto_symbols
    assert "BTC/USDT" not in etf_symbols
```

- [ ] **Step 6: Create the tiny fixture the new test needs**

```yaml
# tests/fixtures/universe_etf_sample.yaml
symbols:
  - symbol: SPY
    exchange: alpaca
    listed_at: 1993-01-22
    delisted_at: null
```

- [ ] **Step 7: Run migration and tests**

Run: `alembic upgrade head`
Expected: migration 0014 applies cleanly.

Run: `TEST_DATABASE_URL=<real-postgres-url> pytest tests/laws/test_survivorship.py -v`
Expected: both tests PASS. (Skips locally without `TEST_DATABASE_URL`, same as every other `db`-marked test in this repo — that's expected, not a failure.)

Run: `ruff check prometheus/data/universe.py prometheus/data/ingestion.py tests/laws/test_survivorship.py && mypy prometheus/data/universe.py prometheus/data/models.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/0014_universe_asset_class.py prometheus/data/models.py prometheus/data/universe.py prometheus/data/ingestion.py tests/laws/test_survivorship.py tests/fixtures/universe_etf_sample.yaml
git commit -m "feat(data): add asset_class to universe_membership

Law 2's as_of() needs to reconstruct one asset class's universe
without mixing in another's, ahead of the ETF adapter this enables.
asset_class is a required parameter on as_of()/sync_from_yaml(), not
optional-with-a-default, so a caller can never forget to specify one
and silently get both classes mixed."
```

---

### Task 2: Provider abstraction (`MarketDataProvider`, `RawBar`) + stock stub

**Files:**
- Create: `prometheus/data/providers/__init__.py` (empty)
- Create: `prometheus/data/providers/base.py`
- Create: `prometheus/data/providers/stocks.py`
- Test: `tests/test_providers_base.py`

**Interfaces:**
- Produces: `data.providers.base.RawBar` (frozen dataclass: `symbol, event_time, open, high, low, close, volume`)
- Produces: `data.providers.base.ProviderCapabilities` (TypedDict: `asset_classes, intervals, survivorship_safe, point_in_time, rate_limit`)
- Produces: `data.providers.base.MarketDataProvider` (ABC: `capabilities() -> ProviderCapabilities`, `async fetch_bars(symbols, start, end, interval) -> list[RawBar]`)
- Produces: `data.providers.stocks.StockProvider(MarketDataProvider)` — `fetch_bars()` raises `NotImplementedError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_providers_base.py
"""MarketDataProvider is an ABC with no real behavior of its own to
test beyond "the interface shape is what callers depend on" -- concrete
adapters (AlpacaProvider) get their own real behavioral tests.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar
from prometheus.data.providers.stocks import StockProvider


def test_raw_bar_is_frozen_and_has_no_available_at_field() -> None:
    """RawBar deliberately excludes available_at/source/revision --
    those are orchestration decisions (ingestion-lag policy), not
    provider concerns. A provider that tried to set available_at would
    be making a policy call it shouldn't be trusted to make."""
    bar = RawBar(
        symbol="SPY",
        event_time=datetime(2024, 1, 2, tzinfo=UTC),
        open=470.0,
        high=471.0,
        low=469.0,
        close=470.5,
        volume=1_000_000.0,
    )
    assert not hasattr(bar, "available_at")
    with pytest.raises(AttributeError):
        bar.open = 999.0  # type: ignore[misc]


def test_market_data_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        MarketDataProvider()  # type: ignore[abstract]


async def test_stock_provider_declares_itself_unimplemented() -> None:
    provider = StockProvider()
    with pytest.raises(NotImplementedError):
        await provider.fetch_bars(["AAPL"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC), "1d")


def test_stock_provider_capabilities_are_honest_about_being_unimplemented() -> None:
    caps: ProviderCapabilities = StockProvider().capabilities()
    assert caps["survivorship_safe"] is False
    assert caps["point_in_time"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_providers_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.providers'`

- [ ] **Step 3: Write `data/providers/base.py`**

```python
"""The provider-agnostic interface every market data source implements.
One schema (RawBar), many adapters (AlpacaProvider today; a future
CcxtProvider wraps today's ccxt-based crypto ingestion; StockProvider is
an intentional stub) so a new data source slots in without a rewrite.

Every adapter DECLARES whether it is survivorship-safe and point-in-time
via capabilities(). That flag is meant to propagate into data_version
and every backtest result downstream (prometheus.data.versioning) --
never invent a "probably fine" default for it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


@dataclass(frozen=True)
class RawBar:
    """One bar as a provider hands it over -- deliberately missing
    available_at/source/revision. Ingestion-lag policy (how long after
    event_time a bar becomes knowable) is an orchestration decision, the
    same way prometheus.data.ingestion's _INGESTION_LAG constant lives
    in the orchestration layer today, not inside any exchange client."""

    symbol: str
    event_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class ProviderCapabilities(TypedDict):
    asset_classes: list[str]
    intervals: list[str]
    survivorship_safe: bool
    point_in_time: bool
    rate_limit: str


class MarketDataProvider(ABC):
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]: ...
```

- [ ] **Step 4: Write `data/providers/stocks.py`**

```python
"""Single-stock data adapter -- deliberately unimplemented (PROMPT 2's
2.3e). Every genuinely free source for single-stock history is either
survivorship-biased or split-adjusted in place (yfinance, most free
scrapers): silently wiring one up would make every backtest on it look
better than reality without any way to tell which results were real,
which is exactly the failure this whole point-in-time layer exists to
prevent. Do NOT implement this against yfinance or an equivalent free
scrape under time pressure -- wait for a real survivorship-safe source
(Polygon, Sharadar, or Tiingo, roughly $30-100/mo) and revisit after the
system has proven the machinery produces trustworthy results at all.
"""
from __future__ import annotations

from datetime import datetime

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar


class StockProvider(MarketDataProvider):
    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["stock"],
            "intervals": [],
            "survivorship_safe": False,
            "point_in_time": False,
            "rate_limit": "n/a -- unimplemented",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        raise NotImplementedError(
            "Single-stock data needs a survivorship-safe paid provider "
            "(Polygon, Sharadar, or Tiingo) -- see this module's docstring. "
            "Never wire this up against yfinance or an equivalent free scrape."
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_providers_base.py -v`
Expected: 4 passed

- [ ] **Step 6: Lint and type-check**

Run: `ruff check prometheus/data/providers/ tests/test_providers_base.py && mypy prometheus/data/providers/`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add prometheus/data/providers/__init__.py prometheus/data/providers/base.py prometheus/data/providers/stocks.py tests/test_providers_base.py
git commit -m "feat(data): MarketDataProvider abstraction + unimplemented stock stub

One schema (RawBar), many adapters -- AlpacaProvider (next task) is the
first real one; a future CcxtProvider wraps today's crypto ingestion.
StockProvider stays an intentional NotImplementedError: every free
single-stock source is survivorship-biased or split-adjusted in place."
```

---

### Task 3: `AlpacaProvider`

**Files:**
- Create: `prometheus/data/providers/alpaca.py`
- Test: `tests/test_providers_alpaca.py`

**Interfaces:**
- Consumes: `data.providers.base.MarketDataProvider`, `RawBar`, `ProviderCapabilities` (Task 2)
- Produces: `data.providers.alpaca.AlpacaProvider(MarketDataProvider)`, reads `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` from `os.environ` inside `fetch_bars()`, not at import or `__init__` time

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_alpaca.py
"""AlpacaProvider.fetch_bars() against mocked httpx responses -- no live
network call, no real API key needed to run this suite. Response shapes
below match Alpaca's documented GET /v2/stocks/bars schema exactly
(fields t/o/h/l/c/v; n and vw are present in real responses but unused
here).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prometheus.data.providers.alpaca import AlpacaProvider
from prometheus.data.providers.base import RawBar

_ONE_PAGE_RESPONSE = {
    "bars": {
        "SPY": [
            {"t": "2024-01-02T05:00:00Z", "o": 470.0, "h": 471.5, "l": 469.0, "c": 470.5, "v": 1000000.0, "n": 5000, "vw": 470.2},
            {"t": "2024-01-03T05:00:00Z", "o": 470.5, "h": 472.0, "l": 470.0, "c": 471.0, "v": 1100000.0, "n": 5200, "vw": 471.1},
        ]
    },
    "next_page_token": None,
}

_PAGE_1_RESPONSE = {
    "bars": {"SPY": [{"t": "2024-01-02T05:00:00Z", "o": 470.0, "h": 471.5, "l": 469.0, "c": 470.5, "v": 1000000.0, "n": 1, "vw": 470.0}]},
    "next_page_token": "abc123",
}
_PAGE_2_RESPONSE = {
    "bars": {"SPY": [{"t": "2024-01-03T05:00:00Z", "o": 470.5, "h": 472.0, "l": 470.0, "c": 471.0, "v": 1100000.0, "n": 1, "vw": 471.0}]},
    "next_page_token": None,
}


def _mock_client(*responses: dict[str, object]) -> MagicMock:
    mock_response_objs = []
    for body in responses:
        resp = MagicMock()
        resp.json.return_value = body
        resp.raise_for_status = MagicMock()
        mock_response_objs.append(resp)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=mock_response_objs)
    return client


@patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"})
async def test_fetch_bars_parses_one_page_into_raw_bars() -> None:
    with patch("httpx.AsyncClient", return_value=_mock_client(_ONE_PAGE_RESPONSE)):
        provider = AlpacaProvider()
        bars = await provider.fetch_bars(
            ["SPY"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), "1d"
        )

    assert bars == [
        RawBar(symbol="SPY", event_time=datetime(2024, 1, 2, 5, 0, tzinfo=UTC), open=470.0, high=471.5, low=469.0, close=470.5, volume=1000000.0),
        RawBar(symbol="SPY", event_time=datetime(2024, 1, 3, 5, 0, tzinfo=UTC), open=470.5, high=472.0, low=470.0, close=471.0, volume=1100000.0),
    ]


@patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"})
async def test_fetch_bars_follows_pagination() -> None:
    mock = _mock_client(_PAGE_1_RESPONSE, _PAGE_2_RESPONSE)
    with patch("httpx.AsyncClient", return_value=mock):
        provider = AlpacaProvider()
        bars = await provider.fetch_bars(
            ["SPY"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), "1d"
        )

    assert len(bars) == 2
    assert mock.get.await_count == 2


@patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"})
async def test_fetch_bars_sends_auth_headers_and_raw_adjustment() -> None:
    mock = _mock_client(_ONE_PAGE_RESPONSE)
    with patch("httpx.AsyncClient", return_value=mock):
        provider = AlpacaProvider()
        await provider.fetch_bars(["SPY"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), "1d")

    _, kwargs = mock.get.await_args
    assert kwargs["headers"]["APCA-API-KEY-ID"] == "test-key"
    assert kwargs["headers"]["APCA-API-SECRET-KEY"] == "test-secret"
    assert kwargs["params"]["adjustment"] == "raw"


async def test_fetch_bars_raises_a_clear_error_without_credentials() -> None:
    with patch.dict(os.environ, {}, clear=True):
        provider = AlpacaProvider()
        with pytest.raises(KeyError):
            await provider.fetch_bars(["SPY"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), "1d")


def test_capabilities_are_true_for_a_real_audited_feed() -> None:
    caps = AlpacaProvider().capabilities()
    assert caps["survivorship_safe"] is True
    assert caps["point_in_time"] is True
    assert caps["asset_classes"] == ["etf"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers_alpaca.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.providers.alpaca'`

- [ ] **Step 3: Write `data/providers/alpaca.py`**

```python
"""Alpaca Market Data API adapter -- ETF/index daily bars. Legacy
header auth (APCA-API-KEY-ID/APCA-API-SECRET-KEY), not the OAuth2
client_credentials flow (that's Broker API only, a different product
for platforms managing multiple end-users' accounts -- confirmed
against Alpaca's own docs, not assumed). Free tier, real signup
required, but a documented and stable REST API, unlike the keyless
sources that turned out not to work (see this sub-project's design doc
for why Stooq was ruled out).
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

_BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
_TIMEFRAME_MAP = {"1d": "1Day"}
_PAGE_LIMIT = 10000


class AlpacaProvider(MarketDataProvider):
    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["etf"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            "point_in_time": True,
            "rate_limit": "200 req/min (free tier)",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        # Read at call time, not __init__/import time -- importing this
        # module must never require a real credential to be set, same
        # posture as worker._anthropic_client().
        headers = {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        }
        timeframe = _TIMEFRAME_MAP[interval]

        bars: list[RawBar] = []
        async with httpx.AsyncClient() as client:
            for symbol in symbols:
                page_token: str | None = None
                while True:
                    params: dict[str, object] = {
                        "symbols": symbol,
                        "timeframe": timeframe,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "adjustment": "raw",
                        "limit": _PAGE_LIMIT,
                    }
                    if page_token is not None:
                        params["page_token"] = page_token
                    response = await client.get(_BASE_URL, headers=headers, params=params)
                    response.raise_for_status()
                    body = response.json()
                    for raw in body["bars"].get(symbol, []):
                        bars.append(
                            RawBar(
                                symbol=symbol,
                                event_time=datetime.fromisoformat(raw["t"].replace("Z", "+00:00")),
                                open=float(raw["o"]),
                                high=float(raw["h"]),
                                low=float(raw["l"]),
                                close=float(raw["c"]),
                                volume=float(raw["v"]),
                            )
                        )
                    page_token = body.get("next_page_token")
                    if page_token is None:
                        break
        return bars
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_providers_alpaca.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint and type-check**

Run: `ruff check prometheus/data/providers/alpaca.py tests/test_providers_alpaca.py && mypy prometheus/data/providers/alpaca.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add prometheus/data/providers/alpaca.py tests/test_providers_alpaca.py
git commit -m "feat(data): AlpacaProvider -- ETF daily bars via Alpaca Market Data API

Legacy key/secret header auth, not OAuth2 client_credentials (that's
Broker API only -- verified against Alpaca's own docs after the user
surfaced that page, since it looked plausible but doesn't apply here).
adjustment=raw passed explicitly, never relied on as an implicit
default, for the same reason yfinance's split-adjusted-in-place
behavior is excluded elsewhere in this project."
```

---

### Task 4: `data/versioning.py` widening + `data/ingest_etf.py` orchestration

**Files:**
- Modify: `prometheus/data/versioning.py:45-61` (`record_data_version`'s type signature only, no logic change)
- Modify: `prometheus/data/quality.py` (`check_gaps()`/`run_quality_checks()` gain an optional `max_gap_hours` param)
- Create: `prometheus/data/ingest_etf.py`
- Create: `config/universe_etf.yaml`
- Test: `tests/test_ingest_etf.py`
- Test: `tests/test_quality.py` (if it exists — check first; add a case if so, create it if not)

**Interfaces:**
- Consumes: `data.providers.alpaca.AlpacaProvider` (Task 3), `data.universe.sync_from_yaml`/`as_of` (Task 1), `data.quality.run_quality_checks` (extended below), `data.versioning.record_data_version` (widened below), `experiments.violations.record_config_snapshot` (existing, unchanged)
- Produces: `data.ingest_etf.backfill_etf(days: int, symbols: list[str] | None = None, provider: MarketDataProvider | None = None, end: datetime | None = None) -> None`
- Produces: `data.quality.run_quality_checks(frame, timeframe, max_gap_hours: float | None = None) -> QualityReport`

- [ ] **Step 1: Widen `record_data_version`'s type (no behavior change)**

In `prometheus/data/versioning.py`, change only the type annotation on
line 50 (the `source_versions` parameter) — the function body is
unchanged, `JSONB` already stores arbitrary JSON:

```python
async def record_data_version(
    session: AsyncSession,
    frame: pl.DataFrame,
    date_range_start: date,
    date_range_end: date,
    source_versions: dict[str, dict[str, object]],
) -> DataVersion:
```

(Was `source_versions: dict[str, str]`. `DataVersion.source_versions`'s
own ORM annotation in `prometheus/data/models.py:80` widens the same way:
`Mapped[dict[str, dict[str, object]]] = mapped_column(JSONB)`.)

- [ ] **Step 2: Extend `check_gaps()`/`run_quality_checks()` for non-24/7 markets**

Found while writing this plan, not in the original design: `check_gaps()`
flags any gap bigger than one bar's expected spacing (24h for `"1d"`,
`_BAR_HOURS` in `prometheus/data/quality.py`). That's correct for
crypto's 24/7 market, but a normal Friday-to-Monday gap on a real ETF is
~65 hours and a 3-day holiday weekend is ~96 hours — calling this truly
unchanged against real Alpaca daily bars would quarantine every real
ingestion on its first weekend.

In `prometheus/data/quality.py`, change `check_gaps` (currently lines
29-37) and `run_quality_checks` (currently lines 130-137):

```python
def check_gaps(frame: pl.DataFrame, timeframe: str, max_gap_hours: float | None = None) -> list[str]:
    expected_hours = max_gap_hours if max_gap_hours is not None else _expected_bar_hours(timeframe)
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol).sort("event_time")
        deltas = sub["event_time"].diff().drop_nulls()
        gap_count = (deltas.dt.total_hours() > expected_hours).sum()
        if gap_count:
            issues.append(f"{symbol}: {gap_count} gap(s) larger than one {timeframe} bar")
    return issues
```

```python
def run_quality_checks(
    frame: pl.DataFrame, timeframe: str, max_gap_hours: float | None = None
) -> QualityReport:
    issues: list[str] = []
    issues += check_gaps(frame, timeframe, max_gap_hours=max_gap_hours)
    issues += check_duplicate_timestamps(frame)
    issues += check_price_validity(frame)
    issues += check_ohlc_relationships(frame)
    issues += check_volume_spikes(frame)
    issues += check_stale_bars(frame)
    return QualityReport(issues=issues)
```

Every existing crypto call site (`ingestion.py`'s `run_quality_checks(frame, timeframe)`)
passes nothing for the new parameter and keeps its exact current
behavior — `None` defaults to today's `_expected_bar_hours(timeframe)`.
`ingest_etf.py` (this task, below) passes `max_gap_hours=100.0`:
comfortably above a 3-day holiday weekend (~96h), while still catching a
genuinely broken 4+ day gap.

Add a regression test proving the default is unchanged and the override
works. Check whether `tests/test_quality.py` already exists first; if it
does, add these two functions to it, matching its existing style — if
not, create it with just these two:

```python
# tests/test_quality.py (new functions, or new file if none exists)
from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.data.quality import check_gaps


def _frame_with_gap(gap_hours: float) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        [
            {"symbol": "TEST", "event_time": start, "close": 100.0},
            {"symbol": "TEST", "event_time": start + timedelta(hours=gap_hours), "close": 101.0},
        ]
    )


def test_check_gaps_default_behavior_is_unchanged_for_a_weekend_sized_gap() -> None:
    """A 65-hour gap (a normal Friday-close-to-Monday-open span) must
    still flag as a gap under the *default* threshold -- proving this
    change doesn't silently loosen crypto's existing behavior."""
    frame = _frame_with_gap(65.0)
    assert check_gaps(frame, "1d") == ["TEST: 1 gap(s) larger than one 1d bar"]


def test_check_gaps_with_override_tolerates_a_weekend_gap() -> None:
    frame = _frame_with_gap(65.0)
    assert check_gaps(frame, "1d", max_gap_hours=100.0) == []


def test_check_gaps_with_override_still_catches_a_genuine_outage() -> None:
    frame = _frame_with_gap(150.0)
    assert check_gaps(frame, "1d", max_gap_hours=100.0) == [
        "TEST: 1 gap(s) larger than one 1d bar"
    ]
```

Run: `pytest tests/test_quality.py -v`
Expected: 3 passed (or however many total if the file already existed with other tests — all must still pass)

Run: `ruff check prometheus/data/quality.py tests/test_quality.py && mypy prometheus/data/quality.py`
Expected: clean

- [ ] **Step 3: Write the failing test for `ingest_etf`**

```python
# tests/test_ingest_etf.py
"""backfill_etf() against a real Postgres with a fake provider (never
live Alpaca) -- proves it writes through the *existing* quality/
versioning pipeline unchanged, the same convention test_population.py/
test_queue_semantics.py already use for db-marked tests.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from prometheus.data.ingest_etf import backfill_etf
from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0014 applied)",
    ),
]


class _FakeProvider(MarketDataProvider):
    """Returns realistic weekday-only daily bars (skips Saturdays and
    Sundays, like real equity/ETF trading) for one symbol -- the whole
    point of this fake is to include REAL weekend gaps, proving
    backfill_etf() tolerates them (via check_gaps' max_gap_hours
    override) instead of quarantining on them. A fake that generated one
    bar per calendar day (no gaps at all) would pass regardless of
    whether that override actually worked -- this one wouldn't."""

    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["etf"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            "point_in_time": True,
            "rate_limit": "n/a -- test fake",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        bars = []
        price = 400.0
        for symbol in symbols:
            current = start
            while current <= end:
                if current.weekday() < 5:  # Mon-Fri only
                    bars.append(
                        RawBar(
                            symbol=symbol, event_time=current,
                            open=price, high=price + 1, low=price - 1, close=price, volume=1_000_000.0,
                        )
                    )
                current += timedelta(days=1)
        return bars


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


async def test_backfill_etf_writes_real_bars_through_the_existing_pipeline(
    engine: AsyncEngine,
) -> None:
    # end is fixed well before config/holdout.yaml's real holdout_start
    # (2026-09-16) -- this test's job is ingestion/quality/versioning
    # mechanics, not holdout-splitting (already covered by
    # tests/laws/test_holdout_sacred.py), and it must never write fake
    # test bars into the shared Law-3-protected holdout schema.
    await backfill_etf(
        days=200, symbols=["SPY"], provider=_FakeProvider(), end=datetime(2026, 6, 1, tzinfo=UTC)
    )

    factory = async_sessionmaker(engine)
    async with factory() as session:
        status = (
            await session.execute(
                text(
                    "SELECT status FROM raw_ingest WHERE symbol = 'SPY' AND source = 'alpaca' "
                    "ORDER BY id DESC LIMIT 1"
                )
            )
        ).scalar_one()
    # The real point of this test: realistic weekend-gapped data must
    # NOT be quarantined -- proving the max_gap_hours override actually
    # took effect, not just that some data landed somewhere.
    assert status == "normalized"

    async with factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM ohlcv_bars WHERE symbol = 'SPY' AND source = 'alpaca'")
            )
        ).scalar_one()
    # ~5/7 of 200 calendar days, give or take boundary effects -- a loose
    # bound proving substantial real weekday data landed, not lost.
    assert 135 <= count <= 145

    async with factory() as session:
        version_count = (
            await session.execute(
                text("SELECT count(*) FROM data_versions WHERE source_versions ? 'alpaca'")
            )
        ).scalar_one()
    assert version_count >= 1
```

- [ ] **Step 4: Run test to verify it fails**

Run: `TEST_DATABASE_URL=<real-postgres-url> pytest tests/test_ingest_etf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prometheus.data.ingest_etf'`

- [ ] **Step 5: Create `config/universe_etf.yaml`**

```yaml
# ETF/index universe -- PROMPT 2 (multi-asset), the "honest equity path".
# listed_at is each ETF's real inception date (stockanalysis.com,
# spot-checked live for 10/28 rather than assumed from memory), not
# invented -- Law 2's as_of() reconstruction is meaningless against
# fabricated dates.
symbols:
  - symbol: SPY
    exchange: alpaca
    listed_at: 1993-01-22
    delisted_at: null
  - symbol: QQQ
    exchange: alpaca
    listed_at: 1999-03-10
    delisted_at: null
  - symbol: IWM
    exchange: alpaca
    listed_at: 2000-05-22
    delisted_at: null
  - symbol: DIA
    exchange: alpaca
    listed_at: 1998-01-14
    delisted_at: null
  - symbol: XLK
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLF
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLE
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLV
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLI
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLY
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLP
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLU
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLB
    exchange: alpaca
    listed_at: 1998-12-16
    delisted_at: null
  - symbol: XLRE
    exchange: alpaca
    listed_at: 2015-10-07
    delisted_at: null
  - symbol: XLC
    exchange: alpaca
    listed_at: 2018-06-18
    delisted_at: null
  - symbol: TLT
    exchange: alpaca
    listed_at: 2002-07-22
    delisted_at: null
  - symbol: IEF
    exchange: alpaca
    listed_at: 2002-07-22
    delisted_at: null
  - symbol: HYG
    exchange: alpaca
    listed_at: 2007-04-04
    delisted_at: null
  - symbol: LQD
    exchange: alpaca
    listed_at: 2002-07-22
    delisted_at: null
  - symbol: GLD
    exchange: alpaca
    listed_at: 2004-11-18
    delisted_at: null
  - symbol: SLV
    exchange: alpaca
    listed_at: 2006-04-21
    delisted_at: null
  - symbol: USO
    exchange: alpaca
    listed_at: 2006-04-10
    delisted_at: null
  - symbol: UNG
    exchange: alpaca
    listed_at: 2007-04-18
    delisted_at: null
  - symbol: UUP
    exchange: alpaca
    listed_at: 2007-02-20
    delisted_at: null
  - symbol: FXE
    exchange: alpaca
    listed_at: 2005-12-09
    delisted_at: null
  - symbol: EEM
    exchange: alpaca
    listed_at: 2003-04-07
    delisted_at: null
  - symbol: EFA
    exchange: alpaca
    listed_at: 2001-08-14
    delisted_at: null
  - symbol: VNQ
    exchange: alpaca
    listed_at: 2004-09-23
    delisted_at: null
```

- [ ] **Step 6: Write `data/ingest_etf.py`**

```python
"""ETF/index daily-bar ingestion via AlpacaProvider -- PROMPT 2's
"honest equity path". Deliberately isolated from ingestion.py's
crypto/ccxt path (this sub-project's design doc, Approach B): reuses
the *existing* quality-check, holdout-split, and versioning machinery
(quality.run_quality_checks's max_gap_hours override accounts for
non-24/7 markets -- see this task's Step 2), but does not touch
ingestion.py itself. A future sub-project unifies both paths behind
MarketDataProvider once crypto migrates onto it too -- the small
duplication here (the holdout-split insert loop) is deliberately
short-lived, not a permanent fork.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.core.db import get_session
from prometheus.data.ingestion import _INSERT_BAR, _INSERT_HOLDOUT_BAR, _INSERT_RAW, _UPDATE_RAW_STATUS
from prometheus.data.providers.alpaca import AlpacaProvider
from prometheus.data.providers.base import MarketDataProvider
from prometheus.data.quality import run_quality_checks
from prometheus.data.universe import load_universe_symbols_for_asset_class, sync_from_yaml
from prometheus.data.versioning import record_data_version
from prometheus.experiments.violations import record_config_snapshot
from prometheus.validation.holdout import load_holdout_config

_UNIVERSE_ETF_YAML = "config/universe_etf.yaml"
_TIMEFRAME = "1d"
_INGESTION_LAG = timedelta(minutes=5)
_SOURCE = "alpaca"

_HOLDOUT_CONFIG, _ = load_holdout_config()


async def backfill_etf(
    days: int,
    symbols: list[str] | None = None,
    provider: MarketDataProvider | None = None,
    end: datetime | None = None,
) -> None:
    """`end` defaults to now -- overridable so a test can pin a fixed
    window instead of always reaching up to the live holdout boundary
    (config/holdout.yaml's holdout_start), which would otherwise write
    fake test bars into the shared Law-3-protected holdout schema."""
    provider = provider or AlpacaProvider()
    now = end or datetime.now(UTC)
    since = now - timedelta(days=days)
    holdout_cutoff = datetime.combine(_HOLDOUT_CONFIG.holdout_start, datetime.min.time(), UTC)

    async with get_session() as session:
        await sync_from_yaml(session, _UNIVERSE_ETF_YAML, asset_class="etf")
        await record_config_snapshot(session, _UNIVERSE_ETF_YAML)
        await session.commit()

        resolved_symbols = symbols or await load_universe_symbols_for_asset_class(session, "etf")

        for symbol in resolved_symbols:
            raw_bars = await provider.fetch_bars([symbol], since, now, _TIMEFRAME)
            raw_id = (
                await session.execute(
                    _INSERT_RAW,
                    {
                        "source": _SOURCE,
                        "symbol": symbol,
                        "timeframe": _TIMEFRAME,
                        "payload": {"rows": [b.__dict__ | {"event_time": b.event_time.isoformat()} for b in raw_bars]},
                    },
                )
            ).scalar_one()

            if not raw_bars:
                await session.execute(
                    _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
                )
                await session.commit()
                continue

            bars = [
                {
                    "symbol": b.symbol,
                    "timeframe": _TIMEFRAME,
                    "event_time": b.event_time,
                    "available_at": b.event_time + _INGESTION_LAG,
                    "source": _SOURCE,
                    "revision": 1,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in raw_bars
            ]
            frame = pl.DataFrame(bars)
            # 100h: comfortably above a 3-day holiday weekend (~96h) on a
            # real equity/ETF calendar, still catches a genuinely broken
            # 4+ day outage. See this task's Step 2 for the full reasoning.
            report = run_quality_checks(frame, _TIMEFRAME, max_gap_hours=100.0)

            if not report.passed:
                await session.execute(
                    _UPDATE_RAW_STATUS,
                    {"status": "quarantined", "quality_issues": {"issues": report.issues}, "id": raw_id},
                )
                await session.commit()
                continue

            for bar in bars:
                if bar["event_time"] >= holdout_cutoff:
                    await session.execute(_INSERT_HOLDOUT_BAR, bar)
                else:
                    await session.execute(_INSERT_BAR, bar)
            await session.execute(
                _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
            )
            await session.commit()

            await record_data_version(
                session,
                frame,
                date_range_start=since.date(),
                date_range_end=now.date(),
                source_versions={
                    _SOURCE: {
                        "version": "v2",
                        **provider.capabilities(),
                    }
                },
            )
            await session.commit()
```

- [ ] **Step 7: Add the one small helper `ingest_etf.py` needs from `universe.py`**

`load_universe_symbols_for_asset_class` doesn't exist yet — it's the ETF
equivalent of `ingestion.load_universe_symbols()` (which reads directly
from the YAML file, filtering delisted rows), but for `ingest_etf.py` we
want the *upserted* set from `universe_membership` filtered by
`asset_class`, so a symbol delisted after the YAML was last edited is
still excluded correctly. Add to `prometheus/data/universe.py` (end of
file, after `sync_from_yaml`):

```python
async def load_universe_symbols_for_asset_class(session: AsyncSession, asset_class: str) -> list[str]:
    """Currently-active symbols for one asset class, from
    universe_membership (not the YAML directly) -- the same
    delisted_at-aware filter as_of() uses, evaluated at today's date."""
    return await as_of(session, date.today(), asset_class)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `TEST_DATABASE_URL=<real-postgres-url> pytest tests/test_ingest_etf.py -v`
Expected: PASS

Run: `pytest tests/test_providers_base.py tests/test_providers_alpaca.py tests/test_quality.py -v` (regression check)
Expected: still all PASS

- [ ] **Step 9: Lint and type-check**

Run: `ruff check prometheus/data/ingest_etf.py prometheus/data/universe.py prometheus/data/versioning.py prometheus/data/quality.py tests/test_ingest_etf.py && mypy prometheus/data/ingest_etf.py prometheus/data/versioning.py prometheus/data/universe.py prometheus/data/quality.py`
Expected: clean

- [ ] **Step 10: Commit**

```bash
git add prometheus/data/versioning.py prometheus/data/models.py prometheus/data/quality.py prometheus/data/ingest_etf.py prometheus/data/universe.py config/universe_etf.yaml tests/test_ingest_etf.py tests/test_quality.py
git commit -m "feat(data): backfill_etf() -- ETF ingestion via AlpacaProvider

Reuses the existing quality-check/holdout-split/versioning pipeline,
with one small backward-compatible extension (check_gaps' max_gap_hours
override -- crypto's 24/7-market gap threshold would otherwise
quarantine every real ETF ingestion on its first weekend). ingestion.py
(crypto path) is untouched this sub-project by design (see design
doc's Approach B). source_versions widens to carry
each provider's capability flags, not just a version string, so a
strategy trained on non-point-in-time data can be labelled as such."
```

---

### Task 5: CLI entry point + end-to-end manual verification

**Files:**
- Modify: `prometheus/data/ingest_etf.py` (add `if __name__ == "__main__"` CLI block, mirroring `ingestion.py`'s own `_parse_args`/`__main__` block)

**Interfaces:**
- Consumes: `data.ingest_etf.backfill_etf` (Task 4)
- Produces: `python -m prometheus.data.ingest_etf --days N` CLI

- [ ] **Step 1: Check `ingestion.py`'s existing CLI shape to mirror it**

`prometheus/data/ingestion.py` already has a `_parse_args`/`__main__` block
(referenced in the design doc's verification section as the existing
pattern). Read it before writing this step's code, then mirror its
`argparse` shape exactly (same flag names/style) for `ingest_etf.py`,
substituting `--symbol`/`--family` (crypto-specific, not applicable here)
for nothing — `ingest_etf.py`'s only real CLI knob is `--days`:

```python
# Appended to the end of prometheus/data/ingest_etf.py
import argparse


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill ETF/index daily bars via Alpaca.")
    parser.add_argument("--days", type=int, default=2000)
    return parser.parse_args(argv)


def main() -> None:
    import asyncio

    args = _parse_args()
    asyncio.run(backfill_etf(days=args.days))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lint and type-check**

Run: `ruff check prometheus/data/ingest_etf.py && mypy prometheus/data/ingest_etf.py`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add prometheus/data/ingest_etf.py
git commit -m "feat(data): CLI entry point for backfill_etf"
```

- [ ] **Step 4: Manual end-to-end verification (needs real Alpaca keys — hand off to the user)**

This step cannot be run by an agent without real credentials. Once the
user has signed up for Alpaca and set `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`:

```bash
alembic upgrade head
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python -m prometheus.data.ingest_etf --days 2000
```

Expected: no errors; `SELECT count(*), min(event_time), max(event_time) FROM ohlcv_bars WHERE source = 'alpaca'`
against the real database shows real rows for all 28 symbols (fewer for
XLRE/XLC, whose 2015/2018 inception means less available history than
`--days 2000` requests — that's correct, not a bug).

---

## Self-Review Notes

- **Spec coverage:** every "New code"/"Extended" bullet in the spec has a
  task: provider ABC + stub (Task 2), Alpaca adapter (Task 3),
  `asset_class` column + `universe.py` extension (Task 1),
  `versioning.py` widening + `ingest_etf.py` (Task 4), CLI (Task 5), the
  one new law test (folded into Task 1, where the signature change
  already touches that file). `docs/DEPENDENCIES.md`: correctly no task,
  since the spec calls for no new entry.
- **Type consistency check:** `RawBar` (Task 2) is used identically in
  Task 3's tests, Task 4's fake provider, and `ingest_etf.py` itself.
  `MarketDataProvider.fetch_bars` signature
  `(symbols: list[str], start: datetime, end: datetime, interval: str) -> list[RawBar]`
  matches across the ABC (Task 2), `AlpacaProvider` (Task 3),
  `StockProvider` (Task 2), and `_FakeProvider` (Task 4) exactly.
  `sync_from_yaml`'s new `asset_class` keyword-only parameter is used
  consistently at both real call sites (`ingestion.py`'s `"crypto"`,
  `ingest_etf.py`'s `"etf"`) and in every test.
- **Two real issues found while drafting Task 4, not present in the
  original spec, both fixed in this plan and backported into the spec
  doc:**
  1. `check_gaps()`'s 24-hour expected-bar-spacing assumption is correct
     for crypto's 24/7 market but would quarantine *every* real ETF
     ingestion on its first weekend gap (~65h, or ~96h over a holiday
     weekend). Fixed with a backward-compatible `max_gap_hours` override
     (Task 4, Step 2) — every existing crypto call site is unaffected.
  2. `backfill_etf()`'s default window (`days` back from `datetime.now()`)
     would reach into `config/holdout.yaml`'s real `holdout_start`
     (2026-09-16, only ~4 days before this plan was written) — a naive
     test would have written fake bars into the shared, Law-3-protected
     holdout schema. Fixed by giving `backfill_etf()` an optional `end`
     override (Task 4, Step 6) so the test can pin a window entirely in
     the past; the real CLI path (Task 5) is correctly unaffected and
     still lets today's genuine holdout boundary apply.

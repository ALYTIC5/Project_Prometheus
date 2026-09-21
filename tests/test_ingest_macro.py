"""backfill_macro() against a real Postgres with a fake provider (never
live FRED) -- proves it writes through the *existing* quality/
versioning pipeline unchanged, the same convention test_ingest_etf.py
already uses for db-marked tests.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from prometheus.data.ingest_macro import backfill_macro
from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0014 applied)",
    ),
]


class _FakeFredProvider(MarketDataProvider):
    """Returns realistic weekday-only, genuinely FLAT-OHLC daily bars
    (open=high=low=close, like a real FRED index-level series) -- the
    whole point of this fake is to include REAL flat-OHLC rows, proving
    backfill_macro() tolerates them (via skip_stale_check=True) instead
    of quarantining on them, same "the fake must include the exact
    real-world shape being tested" reasoning test_ingest_etf.py's own
    weekend-gap fake already uses."""

    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["macro"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            "point_in_time": True,
            "rate_limit": "n/a -- test fake",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        bars = []
        value = 15.0
        for symbol in symbols:
            current = start
            while current <= end:
                if current.weekday() < 5:  # Mon-Fri only
                    bars.append(
                        RawBar(
                            symbol=symbol,
                            event_time=current,
                            open=value,
                            high=value,
                            low=value,
                            close=value,
                            volume=0.0,
                        )
                    )
                current += timedelta(days=1)
        return bars


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    old_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        yield eng
    finally:
        await eng.dispose()
        if old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_database_url


async def test_backfill_macro_writes_real_bars_through_the_existing_pipeline(
    engine: AsyncEngine,
) -> None:
    # end is fixed well before config/holdout.yaml's real holdout_start
    # (2026-09-16), same reasoning test_ingest_etf.py's own fixed end
    # gives -- this test's job is ingestion/quality/versioning mechanics,
    # never writing fake test bars into the Law-3-protected holdout schema.
    await backfill_macro(
        days=200, symbols=["FRED:VIXCLS"], provider=_FakeFredProvider(),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )

    factory = async_sessionmaker(engine)
    async with factory() as session:
        status = (
            await session.execute(
                text(
                    "SELECT status FROM raw_ingest WHERE symbol = 'FRED:VIXCLS' "
                    "AND source = 'fred' ORDER BY id DESC LIMIT 1"
                )
            )
        ).scalar_one()
    # The real point of this test: genuinely flat-OHLC data must NOT be
    # quarantined -- proving skip_stale_check=True actually took effect,
    # not just that some data landed somewhere.
    assert status == "normalized"

    async with factory() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ohlcv_bars WHERE symbol = 'FRED:VIXCLS' "
                    "AND source = 'fred'"
                )
            )
        ).scalar_one()
    # ~5/7 of 200 calendar days, give or take boundary effects.
    assert 135 <= count <= 145

    async with factory() as session:
        version_count = (
            await session.execute(
                text("SELECT count(*) FROM data_versions WHERE source_versions ? 'fred'")
            )
        ).scalar_one()
    assert version_count >= 1

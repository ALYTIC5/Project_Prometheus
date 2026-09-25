"""Universe membership accessor tests -- point-in-time universe
reconstruction without repeated DB queries."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prometheus.data.models import UniverseMembership
from prometheus.data.universe import membership_windows

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0009 applied)",
    ),
]


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.db
async def test_membership_windows_returns_listed_and_delisted_dates(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # Test-only symbols: the shared CI database may already hold the real
    # XLC/XLK rows (committed by the ETF-ingest tests), and a duplicate
    # (symbol, exchange, listed_at) insert fails the unique constraint.
    async with factory() as session:
        session.add_all([
            UniverseMembership(
                symbol="TEST_XLC", exchange="alpaca", asset_class="etf",
                listed_at=date(2018, 6, 18), delisted_at=None,
            ),
            UniverseMembership(
                symbol="TEST_XLK", exchange="alpaca", asset_class="etf",
                listed_at=date(1998, 12, 16), delisted_at=None,
            ),
        ])
        await session.flush()

        windows = await membership_windows(session, "etf", ["TEST_XLC", "TEST_XLK", "TEST_GLD"])

        assert windows["TEST_XLC"] == (date(2018, 6, 18), None)
        assert windows["TEST_XLK"] == (date(1998, 12, 16), None)
        assert "TEST_GLD" not in windows  # never registered under "etf" in this test

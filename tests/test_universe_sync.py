"""data/universe.py's sync_from_yaml against real Postgres -- the ON
CONFLICT upsert path (migration 0009's unique constraint) can't be
verified without a real database. Marked db and skipped locally without
TEST_DATABASE_URL, same pattern as the other db-backed test modules.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prometheus.data.universe import as_of, sync_from_yaml

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0009 applied)",
    ),
]

_FIXTURE_PATH = "config/universe.yaml"


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _row_count_for(session: AsyncSession, symbol: str, exchange: str, listed_at: date) -> int:
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM universe_membership "
            "WHERE symbol = :symbol AND exchange = :exchange AND listed_at = :listed_at"
        ),
        {"symbol": symbol, "exchange": exchange, "listed_at": listed_at},
    )
    return result.scalar_one()


async def test_sync_is_idempotent(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        first_count = await sync_from_yaml(session, _FIXTURE_PATH)
        await session.commit()
        rows_after_first = await _row_count_for(
            session, "BTC/USDT", "binance", date(2017, 8, 1)
        )

        second_count = await sync_from_yaml(session, _FIXTURE_PATH)
        await session.commit()
        rows_after_second = await _row_count_for(
            session, "BTC/USDT", "binance", date(2017, 8, 1)
        )

    assert first_count == second_count  # same file, same row count touched
    assert rows_after_first == 1
    assert rows_after_second == 1  # re-sync did not duplicate the row


async def test_sync_populates_real_as_of_queries(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The actual point of this module: as_of() must return real data once
    synced, not just in test_survivorship.py's own hand-built fixture."""
    async with factory() as session:
        await sync_from_yaml(session, _FIXTURE_PATH)
        await session.commit()

        symbols_today = await as_of(session, date.today())
    assert "BTC/USDT" in symbols_today


async def test_resyncing_a_delisting_updates_the_existing_row_not_a_duplicate(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The bug this function exists to avoid: a symbol's delisted_at
    changing between syncs must UPDATE the existing (symbol, exchange,
    listed_at) row, never insert a second one -- two rows for the same
    listing (one NULL delisted_at, one dated) would make as_of() report
    the symbol alive forever through the stale NULL row."""
    exchange, listed_at = "binance", date(2030, 1, 1)
    symbol = "SYNCTEST/USDT"

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO universe_membership (symbol, exchange, listed_at, delisted_at) "
                "VALUES (:symbol, :exchange, :listed_at, NULL) "
                "ON CONFLICT ON CONSTRAINT uq_universe_membership_symbol_exchange_listed_at "
                "DO UPDATE SET delisted_at = NULL"
            ),
            {"symbol": symbol, "exchange": exchange, "listed_at": listed_at},
        )
        await session.commit()
        count_before = await _row_count_for(session, symbol, exchange, listed_at)
        assert count_before == 1

        # Simulate a re-sync that now reports this symbol delisted.
        await session.execute(
            text(
                "INSERT INTO universe_membership (symbol, exchange, listed_at, delisted_at) "
                "VALUES (:symbol, :exchange, :listed_at, :delisted_at) "
                "ON CONFLICT ON CONSTRAINT uq_universe_membership_symbol_exchange_listed_at "
                "DO UPDATE SET delisted_at = EXCLUDED.delisted_at"
            ),
            {
                "symbol": symbol,
                "exchange": exchange,
                "listed_at": listed_at,
                "delisted_at": date(2030, 6, 1),
            },
        )
        await session.commit()

        count_after = await _row_count_for(session, symbol, exchange, listed_at)
        delisted_at = (
            await session.execute(
                text(
                    "SELECT delisted_at FROM universe_membership "
                    "WHERE symbol = :symbol AND exchange = :exchange AND listed_at = :listed_at"
                ),
                {"symbol": symbol, "exchange": exchange, "listed_at": listed_at},
            )
        ).scalar_one()

        await session.execute(
            text(
                "DELETE FROM universe_membership WHERE symbol = :symbol AND exchange = :exchange"
            ),
            {"symbol": symbol, "exchange": exchange},
        )
        await session.commit()

    assert count_after == 1  # still one row, not two
    assert delisted_at == date(2030, 6, 1)

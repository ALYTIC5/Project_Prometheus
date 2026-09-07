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

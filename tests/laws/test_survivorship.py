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

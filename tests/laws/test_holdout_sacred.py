"""Law 3: the holdout is sacred. Real implementation:
prometheus/validation/holdout.py, alembic/versions/0010_holdout_and_validation.py.

Requires a live Postgres with migrations 0001-0010 applied, PLUS the
restricted-role env vars migration 0010 needs (HOLDOUT_DB_ROLE,
HOLDOUT_DB_PASSWORD, HOLDOUT_DATABASE_URL) -- skipped (not xfail; this is
missing infrastructure, not missing code) when either TEST_DATABASE_URL
or HOLDOUT_DATABASE_URL isn't set. CI's laws job provides both.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prometheus.strategy.spec import StrategySpec
from prometheus.validation.holdout import HoldoutAccessDenied, access_holdout

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("HOLDOUT_DATABASE_URL"),
    reason=(
        "requires TEST_DATABASE_URL (migrations 0001-0010 applied) and "
        "HOLDOUT_DATABASE_URL (migration 0010's restricted role)"
    ),
)


@pytest.fixture()
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()

    # access_holdout() opens core.db.get_holdout_session(), which caches
    # its engine in a module-global (same lazy-singleton pattern as
    # get_engine()). pytest-asyncio gives each test function its OWN
    # event loop by default (asyncio_default_fixture_loop_scope =
    # "function"), but a module-global engine created in one test's loop
    # is not valid in the next test's loop -- letting it leak across
    # tests crashed asyncpg's connection teardown with "Event loop is
    # closed" (a real failure, caught by actually running these tests,
    # not a flaky one to retry past). Reset the global after every test
    # that might have created it.
    import prometheus.core.db as db_module

    if db_module._holdout_engine is not None:
        await db_module._holdout_engine.dispose()
        db_module._holdout_engine = None
        db_module._holdout_session_factory = None


def _spec() -> StrategySpec:
    # A unique symbol per call so repeated test runs never collide on a
    # fingerprint some earlier run already burned -- holdout_access_log
    # is append-only (Law 6), there is no way to clean up between runs.
    return StrategySpec(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}/USDT",
        timeframe="1d",
        fast_window=5,
        slow_window=20,
        expected_horizon=20,
    )


async def test_first_holdout_access_is_granted_and_logged(session: AsyncSession) -> None:
    spec = _spec()
    frame = await access_holdout(session, spec, experiment_id=None)
    await session.commit()
    assert frame is not None  # empty (no holdout bars for a throwaway test symbol) but real

    count = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM holdout_access_log "
                "WHERE strategy_fingerprint = :fp AND granted = true"
            ),
            {"fp": spec.config_hash()},
        )
    ).scalar_one()
    assert count == 1


async def test_second_holdout_access_raises(session: AsyncSession) -> None:
    spec = _spec()
    await access_holdout(session, spec, experiment_id=None)
    await session.commit()

    with pytest.raises(HoldoutAccessDenied):
        await access_holdout(session, spec, experiment_id=None)
    # access_holdout() stages the denial's audit row but never commits
    # (a helper committing a caller's transaction is not its call to
    # make -- same rule core.config.load_research_policy documents) --
    # the raise happens before any rollback, so the row is still staged
    # here and committing (not rolling back) is what a real caller
    # actually wants: the audit trail must survive the denial.
    await session.commit()

    denied_count = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM holdout_access_log "
                "WHERE strategy_fingerprint = :fp AND granted = false"
            ),
            {"fp": spec.config_hash()},
        )
    ).scalar_one()
    assert denied_count == 1


def test_holdout_role_cannot_select_main_schema() -> None:
    """migration 0010's actual point: a connection authenticated as the
    restricted HOLDOUT_DB_ROLE gets a real Postgres permission error
    reading a main-schema table it was never granted anything on."""
    url = os.environ["HOLDOUT_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql+psycopg://"
    )
    engine = create_engine(url)
    try:
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text("SELECT 1 FROM experiments LIMIT 1"))
    finally:
        engine.dispose()


def test_holdout_role_can_select_holdout_schema() -> None:
    """The positive case: the same restricted role CAN read what it was
    actually granted -- proves the role isn't simply broken/unusable."""
    url = os.environ["HOLDOUT_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql+psycopg://"
    )
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT COUNT(*) FROM holdout.ohlcv_bars"))
    finally:
        engine.dispose()

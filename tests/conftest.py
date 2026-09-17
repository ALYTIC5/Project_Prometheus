"""Session-wide test fixtures. Values here are arbitrary test sentinels,
not production risk limits — those come from real deployment env vars.
"""
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from prometheus.core import db as core_db

# Distinct, easy-to-spot-in-a-diff values so no one mistakes these for
# real limits.
#
# Assigned unconditionally, not via setdefault: a developer with real risk
# limits exported in their shell would otherwise silently run the law tests
# against those values instead of these sentinels, and the tests would still
# pass — which is exactly the kind of "green for the wrong reason" that
# tests/laws/ exists to prevent.
os.environ["MAX_POSITION_PCT"] = "11"
os.environ["MAX_GROSS_EXPOSURE_PCT"] = "22"
os.environ["MAX_LEVERAGE"] = "3"
os.environ["MAX_DAILY_LOSS_PCT"] = "4"
os.environ["MAX_DRAWDOWN_PCT"] = "15"
os.environ["KILL_SWITCH"] = "false"


@pytest.fixture(autouse=True)
async def _fresh_core_engine() -> AsyncIterator[None]:
    """core.ids.next_job_id()/next_experiment_id()/next_strategy_id()/
    next_paper_order_id() all go through core.db.get_engine()'s
    module-global, process-lifetime engine -- a design that assumes one
    long-lived event loop (the real API/worker process), not
    pytest-asyncio's per-test-function loop. Left cached across tests, an
    engine created inside an earlier test's now-closed loop raises
    "Event loop is closed" / "attached to a different loop" on its next
    use, and can leave an id_counters increment half-done, producing
    downstream duplicate-key collisions in whatever table that id was for
    -- all three symptoms traced to this one cause via CI's real-Postgres
    db-tests job (no local Postgres in this dev environment to catch it
    sooner). Originally solved locally in test_queue_semantics.py; hoisted
    here so every db-marked test gets it, not just the one file that
    happened to need it first. A no-op for tests that never call
    get_engine() -- resetting an unused module global costs nothing."""
    core_db._engine = None
    core_db._session_factory = None
    yield
    if core_db._engine is not None:
        await core_db._engine.dispose()
        core_db._engine = None
        core_db._session_factory = None


@pytest.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    """A real-Postgres session, isolated per test by a savepoint-joined
    transaction that is always rolled back at teardown -- tests can INSERT/
    UPDATE freely without leaving rows behind for the next test or a later
    run (SQLAlchemy's documented "join a Session into an external
    transaction" pattern for test suites).

    Skips (never fails) when TEST_DATABASE_URL isn't set -- the same
    posture every other db-marked test in this suite already uses
    (tests/test_paper_ids.py, tests/test_ablation_placebo.py).

    A fresh engine per test, not a session-scoped one: pyproject.toml sets
    asyncio_default_fixture_loop_scope = "function", so every test gets its
    own event loop, and an asyncpg connection pool created under one loop
    cannot be reused from another -- the same reason
    test_ablation_placebo.py's own `factory` fixture creates a new engine
    per test rather than sharing one across the session.

    DATABASE_URL is also set to TEST_DATABASE_URL for the fixture's
    duration: prometheus.core.ids.next_paper_order_id() (used by
    prometheus.paper.execution.decide_and_submit) calls
    prometheus.core.db.get_engine(), which reads DATABASE_URL from the
    environment -- same setup tests/test_paper_ids.py's own
    _setup_database_url fixture already performs.
    """
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("requires TEST_DATABASE_URL (a real Postgres)")

    old_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()
        if old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_database_url

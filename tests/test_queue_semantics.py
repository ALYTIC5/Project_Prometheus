"""prometheus/experiments/queue.py against real Postgres -- SKIP LOCKED
concurrency, backoff, and dead-lettering can't be verified any other way.

Marked `db` (a third CI job runs these against a real Postgres service --
see .github/workflows/ci.yml) and skipped locally without
TEST_DATABASE_URL, same as tests/laws/test_history_append_only.py. Not
under tests/laws/: these are correctness tests for deliberately mutable
machinery, not the one gate CLAUDE.md says may never be weakened.

`jobs` is NOT trigger-protected (migration 0007), so an autouse fixture
empties it before every test -- unlike the experiment fixtures elsewhere
in this repo, which must accumulate forever under Law 6's append-only
trigger and so are never cleaned up at all.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import prometheus.core.db as core_db
from prometheus.core.config import QueueSettings
from prometheus.experiments.queue import (
    JobOutcome,
    claim,
    enqueue,
    fail,
    heartbeat,
    reap_stale_claims,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0007 applied)",
    ),
]

# Fast, arbitrary test values -- not a validation threshold, same posture
# tests/conftest.py's risk-limit sentinels take.
_TEST_QUEUE_SETTINGS = QueueSettings(
    JOB_HEARTBEAT_INTERVAL_SECONDS=1.0,
    JOB_HEARTBEAT_TIMEOUT_SECONDS=5.0,
    JOB_BACKOFF_BASE_SECONDS=0.01,
    JOB_BACKOFF_MAX_SECONDS=0.02,
)


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _fresh_core_engine() -> AsyncIterator[None]:
    """core.ids.next_job_id() (used by enqueue()) goes through
    core.db.get_engine()'s module-global, process-lifetime engine -- a
    design that assumes one long-lived event loop (the real API process),
    not pytest-asyncio's per-test-function loop. Left cached across tests
    in this file, a test's engine, created inside a previous test's now-
    closed loop, raises "Event loop is closed" on its next use. Resetting
    the cache here (not touching DATABASE_URL/TEST_DATABASE_URL, which
    happen to point at the same database in this suite) forces a fresh
    engine bound to the current test's loop instead."""
    core_db._engine = None
    core_db._session_factory = None
    yield
    if core_db._engine is not None:
        await core_db._engine.dispose()
        core_db._engine = None
        core_db._session_factory = None


@pytest.fixture(autouse=True)
async def _empty_jobs_table(engine: AsyncEngine) -> None:
    """`jobs` is a queue, not a history log -- unlike the experiments
    fixtures elsewhere in this repo, it is fair game to reset before every
    test. Without this, `claim()` in one test can pick up a pending row
    left behind by a previous test (or a previous failed run) instead of
    the job that test just enqueued, since two rows with equal priority/
    expected_information_value/run_at are perfectly valid and the claim
    order between them is then whichever id sorts first."""
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM jobs_dead_letter"))
        await conn.execute(text("DELETE FROM jobs"))


async def _enqueue_test_job(
    session: AsyncSession, *, idempotency_key: str | None = None, max_attempts: int = 1
) -> str:
    return await enqueue(
        session,
        kind="test_job",
        payload={},
        idempotency_key=idempotency_key or f"test-{uuid.uuid4().hex}",
        priority=0,
        expected_information_value=0.0,
        estimated_cost=0.0,
        max_attempts=max_attempts,
        agent_role="engineer",
        current_stage="forge",
        next_stage="arena",
    )


async def test_enqueue_is_idempotent_by_key(factory: async_sessionmaker[AsyncSession]) -> None:
    key = f"idem-{uuid.uuid4().hex}"
    async with factory() as session:
        first_id = await _enqueue_test_job(session, idempotency_key=key)
        second_id = await _enqueue_test_job(session, idempotency_key=key)
        await session.commit()
    assert first_id == second_id


async def test_claim_skips_locked_row_and_returns_the_other_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as setup_session:
        job_a_id = await _enqueue_test_job(setup_session)
        job_b_id = await _enqueue_test_job(setup_session)
        await setup_session.commit()

    session_a = factory()
    session_b = factory()
    try:
        claimed_a = await claim(session_a, worker_id="worker-a")
        # session_a's transaction is still open -- claimed_a's row is
        # locked, uncommitted. If SKIP LOCKED were broken (a plain SELECT
        # ... FOR UPDATE with no SKIP), the next line would block forever
        # instead of returning promptly.
        assert claimed_a is not None
        assert claimed_a.id in (job_a_id, job_b_id)

        claimed_b = await claim(session_b, worker_id="worker-b")
        assert claimed_b is not None
        assert claimed_b.id != claimed_a.id
        assert claimed_b.id in (job_a_id, job_b_id)
    finally:
        await session_a.commit()
        await session_a.close()
        await session_b.commit()
        await session_b.close()


async def test_claim_returns_none_when_the_only_pending_job_is_locked(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as setup_session:
        job_id = await _enqueue_test_job(setup_session)
        await setup_session.commit()

    session_a = factory()
    session_b = factory()
    try:
        claimed_a = await claim(session_a, worker_id="worker-a")
        assert claimed_a is not None and claimed_a.id == job_id

        # Nothing else pending, and the only row is locked -- SKIP LOCKED
        # must return None promptly, never block waiting for the lock.
        claimed_b = await claim(session_b, worker_id="worker-b")
        assert claimed_b is None
    finally:
        await session_a.commit()
        await session_a.close()
        await session_b.commit()
        await session_b.close()


async def test_heartbeat_false_once_reaped_and_reclaimed(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        job_id = await _enqueue_test_job(session)
        await session.commit()

        job = await claim(session, worker_id="worker-original")
        await session.commit()
        assert job is not None and job.id == job_id

        # stale_after_seconds=0: any elapsed time since claim() set
        # heartbeat_at reaps it -- no clock manipulation needed.
        reaped = await reap_stale_claims(session, stale_after_seconds=0)
        await session.commit()
        assert job_id in reaped

        still_owns = await heartbeat(
            session, job_id=job_id, worker_id="worker-original", progress_pct=0.5
        )
        await session.commit()
        assert still_owns is False  # this worker no longer owns the job


async def test_fail_retries_then_dead_letters_after_max_attempts(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        job_id = await _enqueue_test_job(session, max_attempts=2)
        await session.commit()

        job = await claim(session, worker_id="w")  # attempts: 0 -> 1
        await session.commit()
        assert job is not None

        outcome = await fail(
            session, job_id=job_id, worker_id="w", error="boom", settings=_TEST_QUEUE_SETTINGS
        )
        await session.commit()
        assert outcome == JobOutcome.RETRY_SCHEDULED

        # The retry's backoff window (JOB_BACKOFF_BASE_SECONDS=0.01) has
        # to actually elapse -- run_at is genuinely in the future, and
        # claim() correctly won't pick up a job before its run_at arrives.
        await asyncio.sleep(0.05)

        job = await claim(session, worker_id="w")  # attempts: 1 -> 2 == max_attempts
        await session.commit()
        assert job is not None and job.id == job_id

        outcome = await fail(
            session, job_id=job_id, worker_id="w", error="boom again", settings=_TEST_QUEUE_SETTINGS
        )
        await session.commit()
        assert outcome == JobOutcome.DEAD_LETTERED

        dead = (
            await session.execute(
                text("SELECT attempts, last_error FROM jobs_dead_letter WHERE job_id = :id"),
                {"id": job_id},
            )
        ).first()
        assert dead is not None
        assert dead.attempts == 2
        assert dead.last_error == "boom again"

        remaining = await session.execute(
            text("SELECT id FROM jobs WHERE id = :id"), {"id": job_id}
        )
        assert remaining.first() is None  # dead-lettering removes the jobs row

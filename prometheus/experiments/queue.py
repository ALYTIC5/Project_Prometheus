"""The Postgres SKIP LOCKED job queue -- CLAUDE.md: no Redis, use
SELECT ... FOR UPDATE SKIP LOCKED as the job queue.

No function here commits (same rule prometheus.core.config.load_research_
policy states: committing someone else's transaction is not a helper's
decision). claim() is the one exception that matters operationally: its
UPDATE takes a row lock inside the caller's transaction, so the caller
MUST commit immediately after claim() returns and before doing any actual
work -- otherwise the whole job runs with that row locked, and every other
worker's claim() blocks behind it instead of skipping past it.

Every mutator after claim() (heartbeat/succeed/fail) filters
`WHERE claimed_by = :worker_id`, so a worker that gets reaped by
reap_stale_claims() and then wakes up and keeps working cannot stomp
whatever claimed the job next -- its UPDATE simply matches zero rows.
heartbeat() returning False is that worker's signal to abandon the job.
This, not any lock held for the job's duration, is what makes a job safe
to interrupt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.config import QueueSettings
from prometheus.core.ids import next_job_id

_queue_settings: QueueSettings | None = None


def get_queue_settings() -> QueueSettings:
    """Lazy, like core.db.get_engine() -- queue env is only required once a
    caller actually claims/heartbeats/fails a job, not at import time."""
    global _queue_settings
    if _queue_settings is None:
        _queue_settings = QueueSettings()
    return _queue_settings


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    agent_role: str
    current_stage: str
    next_stage: str
    experiment_id: str | None


class JobOutcome(str, Enum):
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DEAD_LETTERED = "DEAD_LETTERED"
    NOT_CLAIMED = "NOT_CLAIMED"  # this worker no longer owns the job; no-op


# asyncpg needs an explicit JSONB bind type for a raw text() query --
# unlike the ORM path (core.db.Job etc.), a bare :payload bound to a dict
# has no column type to adapt against and asyncpg raises DataError.
# bindparams(type_=JSONB) is what carries that type through.
_INSERT_JOB = text(
    """
    INSERT INTO jobs (
        id, kind, payload, idempotency_key, priority, expected_information_value,
        estimated_cost, max_attempts, run_at, agent_role, current_stage, next_stage,
        experiment_id
    )
    VALUES (
        :id, :kind, :payload, :idempotency_key, :priority, :expected_information_value,
        :estimated_cost, :max_attempts, COALESCE(:run_at, now()), :agent_role,
        :current_stage, :next_stage, :experiment_id
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
    """
).bindparams(bindparam("payload", type_=JSONB))
_SELECT_BY_IDEMPOTENCY_KEY = text("SELECT id FROM jobs WHERE idempotency_key = :idempotency_key")


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    priority: int,
    expected_information_value: float,
    estimated_cost: float,
    max_attempts: int,
    agent_role: str,
    current_stage: str,
    next_stage: str,
    experiment_id: str | None = None,
    run_at: datetime | None = None,
) -> str:
    """Returns the job id -- a fresh one, or the existing job's id if
    `idempotency_key` already matched a row (re-enqueuing the identical
    work is a no-op, not a duplicate). The documented convention for
    `idempotency_key` is sha256(kind || strategy_id || config_hash ||
    data_version_hash || code_sha || seed) -- CLAUDE.md's own
    reproducibility tuple, so "same inputs" and "same job" are the same
    predicate. Not enforced here; callers own it.
    """
    job_id = await next_job_id()
    result = await session.execute(
        _INSERT_JOB,
        {
            "id": job_id,
            "kind": kind,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "priority": priority,
            "expected_information_value": expected_information_value,
            "estimated_cost": estimated_cost,
            "max_attempts": max_attempts,
            "run_at": run_at,
            "agent_role": agent_role,
            "current_stage": current_stage,
            "next_stage": next_stage,
            "experiment_id": experiment_id,
        },
    )
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        return str(inserted_id)
    existing = await session.execute(
        _SELECT_BY_IDEMPOTENCY_KEY, {"idempotency_key": idempotency_key}
    )
    return str(existing.scalar_one())


_CLAIM = text(
    """
    WITH claimed AS (
        SELECT id FROM jobs
        WHERE status = 'pending' AND run_at <= now()
        ORDER BY priority DESC, expected_information_value DESC, run_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE jobs j
       SET status = 'claimed', claimed_by = :worker_id, heartbeat_at = now(),
           attempts = j.attempts + 1
      FROM claimed c
     WHERE j.id = c.id
    RETURNING j.id, j.kind, j.payload, j.attempts, j.max_attempts, j.agent_role,
              j.current_stage, j.next_stage, j.experiment_id
    """
)


async def claim(session: AsyncSession, *, worker_id: str) -> Job | None:
    """Claims and returns the single highest-priority runnable job, or
    None if there isn't one. See this module's docstring: commit
    immediately after this returns, before doing any work."""
    row = (await session.execute(_CLAIM, {"worker_id": worker_id})).first()
    if row is None:
        return None
    return Job(
        id=row.id,
        kind=row.kind,
        payload=row.payload,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        agent_role=row.agent_role,
        current_stage=row.current_stage,
        next_stage=row.next_stage,
        experiment_id=row.experiment_id,
    )


_HEARTBEAT = text(
    """
    UPDATE jobs SET heartbeat_at = now(), progress_pct = :progress_pct
     WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING id
    """
)


async def heartbeat(
    session: AsyncSession, *, job_id: str, worker_id: str, progress_pct: float
) -> bool:
    """False means this worker no longer owns the job (reaped and
    reclaimed by someone else, or already resolved) -- the caller's
    signal to abandon whatever it was doing."""
    result = await session.execute(
        _HEARTBEAT, {"job_id": job_id, "worker_id": worker_id, "progress_pct": progress_pct}
    )
    return result.scalar_one_or_none() is not None


_SUCCEED = text(
    """
    UPDATE jobs
       SET status = 'succeeded', heartbeat_at = now(), progress_pct = 1.0,
           experiment_id = COALESCE(:experiment_id, experiment_id)
     WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING id
    """
)


async def succeed(
    session: AsyncSession, *, job_id: str, worker_id: str, experiment_id: str | None = None
) -> bool:
    """False means this worker no longer owned the job -- the result it
    produced should still be recorded (it already was, by the caller,
    via runner.run_one's own INSERTs), but the queue no longer credits
    this worker's claim, and nothing here overwrites whoever's claim it
    is now."""
    result = await session.execute(
        _SUCCEED, {"job_id": job_id, "worker_id": worker_id, "experiment_id": experiment_id}
    )
    return result.scalar_one_or_none() is not None


_SELECT_FOR_FAIL = text(
    "SELECT attempts, max_attempts, kind, payload, idempotency_key, experiment_id "
    "FROM jobs WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'"
)
_RETRY = text(
    """
    UPDATE jobs
       SET status = 'pending', claimed_by = NULL, heartbeat_at = NULL,
           run_at = now() + make_interval(secs => LEAST(:base * power(2, attempts - 1), :max)),
           last_error = :error
     WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'
    """
)
_DEAD_LETTER_INSERT = text(
    """
    INSERT INTO jobs_dead_letter (job_id, kind, payload, idempotency_key, attempts,
                                   experiment_id, last_error)
    SELECT id, kind, payload, idempotency_key, attempts, experiment_id, :error
      FROM jobs WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'
    """
)
_DEAD_LETTER_DELETE = text(
    "DELETE FROM jobs WHERE id = :job_id AND claimed_by = :worker_id AND status = 'claimed'"
)


async def fail(
    session: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    error: str,
    settings: QueueSettings | None = None,
) -> JobOutcome:
    """Deterministic exponential backoff, no jitter -- a spread constant
    needs its own justification, and one scheduled worker cannot cause a
    thundering herd against itself. Dead-letters (moves the row out of
    `jobs` entirely) once attempts have reached max_attempts; this frees
    the idempotency_key, so a fixed bug can be re-enqueued under the same
    key without colliding with its own dead-letter history."""
    settings = settings or get_queue_settings()
    row = (
        await session.execute(_SELECT_FOR_FAIL, {"job_id": job_id, "worker_id": worker_id})
    ).first()
    if row is None:
        return JobOutcome.NOT_CLAIMED
    if row.attempts >= row.max_attempts:
        await session.execute(
            _DEAD_LETTER_INSERT, {"job_id": job_id, "worker_id": worker_id, "error": error}
        )
        await session.execute(_DEAD_LETTER_DELETE, {"job_id": job_id, "worker_id": worker_id})
        return JobOutcome.DEAD_LETTERED
    await session.execute(
        _RETRY,
        {
            "job_id": job_id,
            "worker_id": worker_id,
            "error": error,
            "base": settings.JOB_BACKOFF_BASE_SECONDS,
            "max": settings.JOB_BACKOFF_MAX_SECONDS,
        },
    )
    return JobOutcome.RETRY_SCHEDULED


_REAP = text(
    """
    UPDATE jobs
       SET status = 'pending', claimed_by = NULL, heartbeat_at = NULL, run_at = now(),
           last_error = 'reclaimed: heartbeat stale'
     WHERE status = 'claimed'
       AND heartbeat_at < now() - make_interval(secs => :stale_after_seconds)
    RETURNING id
    """
)


async def reap_stale_claims(session: AsyncSession, *, stale_after_seconds: float) -> list[str]:
    """Returns the ids reclaimed. A crashed worker never sends another
    heartbeat, so its claim ages past `stale_after_seconds` and the job
    becomes runnable again -- this is the mechanism, not a timer on the
    worker side, because the worker that crashed cannot run its own
    cleanup code."""
    result = await session.execute(_REAP, {"stale_after_seconds": stale_after_seconds})
    return [str(row.id) for row in result]


_PENDING_DEPTH_BY_STAGE = text(
    "SELECT current_stage, COUNT(*) AS n FROM jobs WHERE status = 'pending' GROUP BY current_stage"
)


async def pending_depth_by_stage(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(_PENDING_DEPTH_BY_STAGE)
    return {row.current_stage: int(row.n) for row in result}


_IN_FLIGHT = text(
    "SELECT id, agent_role, current_stage, next_stage, progress_pct, experiment_id "
    "FROM jobs WHERE status = 'claimed'"
)


async def in_flight_jobs(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(_IN_FLIGHT)
    return [
        {
            "id": row.id,
            "agent_role": row.agent_role,
            "current_stage": row.current_stage,
            "next_stage": row.next_stage,
            "progress_pct": row.progress_pct,
            "experiment_id": row.experiment_id,
        }
        for row in result
    ]

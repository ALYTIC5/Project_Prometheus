"""Pipeline status API endpoint -- surfaces worker.py's own worker_cadence
table so the dashboard can show "what's the worker doing and when did it
last run" per concern (ingest/research/paper/llm_ingestion), instead of
that state being invisible outside a direct DB query. Reads the shared
interval constants from core/cadence.py, the same ones worker.py's
is_due()/mark_run() use -- this route can never report a different
"due" answer than the worker itself computes.

Step 4's minimal monitoring (2026-09-24): `recent_failures` surfaces
core/health.py's worker_health tally (real ERROR-level exceptions,
grouped by concern+exception_type, over the last _FAILURE_WINDOW_HOURS)
and `job_health` computes a real job failure rate from the existing
`jobs`/`jobs_dead_letter` tables -- no new job-level counting invented;
jobs_dead_letter already IS the permanent record of a job that exhausted
its retries (migration 0007). `unhealthy` is true when that rate exceeds
_UNHEALTHY_FAILURE_RATE, for the dashboard's red banner.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.cadence import CADENCE_SLACK_FACTOR, CONCERN_INTERVALS
from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_SELECT_CADENCE = text("SELECT concern, last_run_at FROM worker_cadence")

# How far back "recent" looks for both the failure tally and the job
# health rate -- wide enough to span a few worker cycles (15min cron) so
# a single unlucky tick isn't misread as sustained trouble, narrow enough
# that a fixed bug's failures age out of the banner instead of haunting
# the dashboard forever.
_FAILURE_WINDOW_HOURS = 2

_SELECT_RECENT_FAILURES = text(
    """
    SELECT concern, exception_type, SUM(failure_count) AS failure_count,
           MAX(sample_message) AS sample_message, MAX(created_at) AS last_seen_at
      FROM worker_health
     WHERE created_at >= :since
     GROUP BY concern, exception_type
     ORDER BY failure_count DESC
    """
)

# jobs.status has no 'failed' resting state (migration 0007): a job that
# exhausts its retries is moved to jobs_dead_letter, never left pending
# forever -- so "recently completed" is exactly succeeded (heartbeat_at
# stamped at completion, same as on claim) plus dead-lettered (died_at)
# in the window, with nothing double-counted or silently excluded.
_SELECT_JOB_HEALTH = text(
    """
    SELECT
        (SELECT COUNT(*) FROM jobs
          WHERE status = 'succeeded' AND heartbeat_at >= :since) AS succeeded,
        (SELECT COUNT(*) FROM jobs_dead_letter WHERE died_at >= :since) AS dead_lettered
    """
)

# 20% -- the exact figure PROMPTS.md's own Step 4 spec names for this
# banner ("A cycle where >20% of jobs failed renders as a red banner"),
# not a value this route invents.
_UNHEALTHY_FAILURE_RATE = 0.20


@router.get("/")
async def get_pipeline_status() -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=_FAILURE_WINDOW_HOURS)

    async with get_session_factory()() as session:
        rows = {r.concern: r.last_run_at for r in (await session.execute(_SELECT_CADENCE)).all()}
        failure_rows = (
            await session.execute(_SELECT_RECENT_FAILURES, {"since": since})
        ).all()
        job_health_row = (
            await session.execute(_SELECT_JOB_HEALTH, {"since": since})
        ).one()

    concerns: list[dict[str, Any]] = []
    for concern, interval_seconds in CONCERN_INTERVALS.items():
        last_run_at = rows.get(concern)
        due_threshold_seconds = interval_seconds * CADENCE_SLACK_FACTOR
        is_due = (
            last_run_at is None
            or (now - last_run_at).total_seconds() >= due_threshold_seconds
        )
        next_due_at = (
            None
            if last_run_at is None
            else last_run_at + timedelta(seconds=due_threshold_seconds)
        )
        concerns.append(
            {
                "concern": concern,
                "interval_seconds": interval_seconds,
                "last_run_at": last_run_at.isoformat() if last_run_at else None,
                "next_due_at": next_due_at.isoformat() if next_due_at else None,
                "is_due": is_due,
            }
        )

    recent_failures = [
        {
            "concern": r.concern,
            "exception_type": r.exception_type,
            "failure_count": r.failure_count,
            "sample_message": r.sample_message,
            "last_seen_at": r.last_seen_at.isoformat(),
        }
        for r in failure_rows
    ]

    succeeded = job_health_row.succeeded or 0
    dead_lettered = job_health_row.dead_lettered or 0
    total = succeeded + dead_lettered
    # None on zero completed jobs this window -- honestly absent, not a
    # fabricated 0% (nothing ran, not "nothing failed").
    failure_rate = (dead_lettered / total) if total else None

    return {
        "concerns": concerns,
        "recent_failures": recent_failures,
        "job_health": {
            "window_hours": _FAILURE_WINDOW_HOURS,
            "succeeded": succeeded,
            "dead_lettered": dead_lettered,
            "failure_rate": failure_rate,
            "unhealthy": failure_rate is not None and failure_rate > _UNHEALTHY_FAILURE_RATE,
        },
    }

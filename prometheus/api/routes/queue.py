"""Queue API endpoint -- a read-only surface over experiments.queue's jobs
table for the dashboard's QUEUE section. Plain-text-SQL style matching
experiments.py/buildings.py, not a wrapper around experiments.queue's own
functions (those take a session and return dataclasses/dicts shaped for
the queue's own internal use, e.g. in_flight_jobs' dict keys match
world/entities.py's Agent fields, not what a dashboard table wants).

"failed_pending_count" is the honest proxy for "failed jobs": there is no
`failed` status in the jobs table (see migration 0007's docstring) -- a
failed job is either retried back to `pending` with a future `run_at`, or
moved to `jobs_dead_letter`. A pending row with attempts > 0 has failed at
least once and is waiting to retry.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/queue", tags=["queue"])

_PENDING_BY_KIND = text(
    "SELECT kind, COUNT(*) AS n FROM jobs WHERE status = 'pending' GROUP BY kind"
)
_IN_FLIGHT = text(
    "SELECT id, kind, agent_role, current_stage, next_stage, progress_pct, experiment_id "
    "FROM jobs WHERE status = 'claimed' ORDER BY heartbeat_at DESC"
)
_DEAD_LETTER_COUNT = text("SELECT COUNT(*) FROM jobs_dead_letter")
_FAILED_PENDING_COUNT = text(
    "SELECT COUNT(*) FROM jobs WHERE status = 'pending' AND attempts > 0"
)


@router.get("/")
async def get_queue_status() -> dict[str, Any]:
    async with get_session_factory()() as session:
        pending_by_kind = {
            row.kind: row.n for row in await session.execute(_PENDING_BY_KIND)
        }
        in_flight = [
            {
                "id": row.id,
                "kind": row.kind,
                "agent_role": row.agent_role,
                "current_stage": row.current_stage,
                "next_stage": row.next_stage,
                "progress_pct": row.progress_pct,
                "experiment_id": row.experiment_id,
            }
            for row in await session.execute(_IN_FLIGHT)
        ]
        dead_letter_count = (await session.execute(_DEAD_LETTER_COUNT)).scalar_one()
        failed_pending_count = (await session.execute(_FAILED_PENDING_COUNT)).scalar_one()

    return {
        "pending_by_kind": pending_by_kind,
        "in_flight": in_flight,
        "dead_letter_count": dead_letter_count,
        "failed_pending_count": failed_pending_count,
    }

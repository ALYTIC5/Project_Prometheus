"""Pipeline status API endpoint -- surfaces worker.py's own worker_cadence
table so the dashboard can show "what's the worker doing and when did it
last run" per concern (ingest/research/paper/llm_ingestion), instead of
that state being invisible outside a direct DB query. Reads the shared
interval constants from core/cadence.py, the same ones worker.py's
is_due()/mark_run() use -- this route can never report a different
"due" answer than the worker itself computes.
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


@router.get("/")
async def get_pipeline_status() -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = {r.concern: r.last_run_at for r in (await session.execute(_SELECT_CADENCE)).all()}

    now = datetime.now(UTC)
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
    return {"concerns": concerns}

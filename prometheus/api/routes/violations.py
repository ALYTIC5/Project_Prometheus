"""Research violations API -- read-only surface for
prometheus.experiments.violations' detectors, matching experiments.py's
plain-text-SQL style.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/violations", tags=["violations"])

_SELECT_RECORDED = text(
    """
    SELECT id, violation_type, experiment_id, detail, detected_at
      FROM research_violations
     ORDER BY detected_at DESC
     LIMIT 200
    """
)


@router.get("/")
async def list_violations() -> dict[str, Any]:
    """Previously-recorded findings (research_violations rows) -- not a
    live re-scan. Call experiments.violations.record_violations() with a
    detector's output to add to this list."""
    async with get_session_factory()() as session:
        result = await session.execute(_SELECT_RECORDED)
        rows = [
            {
                "id": row.id,
                "violation_type": row.violation_type,
                "experiment_id": row.experiment_id,
                "detail": row.detail,
                "detected_at": row.detected_at.isoformat(),
            }
            for row in result
        ]
    return {"violations": rows, "total": len(rows)}

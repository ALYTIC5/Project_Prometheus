"""Experiments API endpoint -- an experiment plus its real results/decisions
rows, joined by experiment_id (there is no FK-based ORM relationship here,
matching this file's plain-text-SQL style rather than the ORM style
core/config.py uses for PolicyVersion).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/experiments", tags=["experiments"])

_SELECT_ALL = text(
    "SELECT id, status, payload, created_at FROM experiments ORDER BY created_at DESC LIMIT 200"
)
_SELECT_ONE = text("SELECT id, status, payload, created_at FROM experiments WHERE id = :id")
_SELECT_RESULTS = text(
    "SELECT payload, created_at FROM results WHERE experiment_id = :id ORDER BY created_at DESC"
)
_SELECT_DECISIONS = text(
    "SELECT decision, created_at FROM decisions WHERE experiment_id = :id ORDER BY created_at DESC"
)


@router.get("/")
async def list_experiments() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await session.execute(_SELECT_ALL)
        rows = [
            {
                "id": r.id,
                "status": r.status,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            }
            for r in result
        ]
    return {"experiments": rows, "total": len(rows)}


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        exp = (await session.execute(_SELECT_ONE, {"id": experiment_id})).first()
        if exp is None:
            raise HTTPException(status_code=404, detail=f"Unknown experiment: {experiment_id}")
        results = [
            {"payload": r.payload, "created_at": r.created_at.isoformat()}
            for r in await session.execute(_SELECT_RESULTS, {"id": experiment_id})
        ]
        decisions = [
            {"decision": d.decision, "created_at": d.created_at.isoformat()}
            for d in await session.execute(_SELECT_DECISIONS, {"id": experiment_id})
        ]
    return {
        "id": exp.id,
        "status": exp.status,
        "payload": exp.payload,
        "created_at": exp.created_at.isoformat(),
        "results": results,
        "decisions": decisions,
    }

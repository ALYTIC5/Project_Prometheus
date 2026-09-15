"""Strategies API endpoint. Real rows from the `strategies` table only --
this route exists once prometheus.experiments.runner has actually written
some.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Row

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/strategies", tags=["strategies"])

_SELECT_ALL = text(
    "SELECT id, family, spec, status, created_at FROM strategies ORDER BY created_at DESC LIMIT 500"
)
_SELECT_ONE = text("SELECT id, family, spec, status, created_at FROM strategies WHERE id = :id")


def _row_to_dict(row: Row[Any]) -> dict[str, Any]:
    return {
        "id": row.id,
        "family": row.family,
        "spec": row.spec,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/")
async def list_strategies() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await session.execute(_SELECT_ALL)
        rows = [_row_to_dict(r) for r in result]
    return {"strategies": rows, "total": len(rows)}


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        row = (await session.execute(_SELECT_ONE, {"id": strategy_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    return _row_to_dict(row)

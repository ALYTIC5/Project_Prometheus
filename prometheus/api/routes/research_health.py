"""Research Health API -- the honesty indicators of the self-improvement
engine. Aggregates only: canary identities never leave the evaluator
schema, not even to the dashboard."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/research-health", tags=["research-health"])

_CANARY_STATS = text(
    """
    SELECT
      (SELECT count(*) FROM evaluator.canary_registry) AS registered,
      (SELECT count(DISTINCT config_hash) FROM evaluator.canary_strategies) AS evaluated,
      (SELECT count(DISTINCT config_hash) FROM evaluator.canary_breaches) AS breached,
      (SELECT max(created_at) FROM evaluator.canary_breaches) AS last_breach_at,
      (SELECT event FROM evaluator.promotion_halts ORDER BY id DESC LIMIT 1) AS latest_halt_event
    """
)


@router.get("/canaries")
async def canaries() -> dict[str, Any]:
    async with get_session_factory()() as session:
        row = (await session.execute(_CANARY_STATS)).one()
    evaluated = int(row.evaluated)
    breached = int(row.breached)
    return {
        "canaries_registered": int(row.registered),
        "canaries_evaluated": evaluated,
        "breaches": breached,
        "false_pass_rate": (breached / evaluated) if evaluated else None,
        "last_breach_at": row.last_breach_at.isoformat() if row.last_breach_at else None,
        "promotions_halted": row.latest_halt_event == "HALT",
    }

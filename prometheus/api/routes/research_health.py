"""Research Health API -- the honesty indicators of the self-improvement
engine. Aggregates only: canary identities never leave the evaluator
schema, not even to the dashboard."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory
from prometheus.validation.discovery_gate import ALPHA, W0, lord_threshold, wealth

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


_GATE_HISTORY = text(
    "SELECT test_index, alpha_threshold, discovery, created_at "
    "FROM evaluator.alpha_wealth_ledger ORDER BY test_index"
)


@router.get("/discovery-gate")
async def discovery_gate() -> dict[str, Any]:
    """The LORD++ fuel gauge (Law 10). Aggregates only."""
    async with get_session_factory()() as session:
        rows = (await session.execute(_GATE_HISTORY)).all()
    discoveries = [row.test_index for row in rows if row.discovery]
    return {
        "alpha": ALPHA,
        "w0": W0,
        "tests": len(rows),
        "discoveries": len(discoveries),
        "current_wealth": wealth([row.alpha_threshold for row in rows], len(discoveries)),
        "next_threshold": lord_threshold(len(rows) + 1, discoveries),
        "last_test_at": rows[-1].created_at.isoformat() if rows else None,
    }


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

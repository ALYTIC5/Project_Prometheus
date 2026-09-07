"""Health check endpoints.

/health/ is the liveness probe and deliberately touches nothing — it must
stay up even when Postgres is down. /health/ready is the readiness probe and
does hit the database, because a readiness answer that ignores real state is
not a readiness answer.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from prometheus.core.db import get_session_factory
from prometheus.world.construction import BUILDING_ORDER, CONSTRUCTION_MANIFEST
from prometheus.world.entities import ConstructionPhase
from prometheus.world.projection import get_construction_phases

router = APIRouter(prefix="/health", tags=["health"])

_start_time = time.monotonic()


@router.get("/")
def health_check() -> dict[str, Any]:
    """Liveness probe — always returns 200."""
    uptime = time.monotonic() - _start_time
    return {
        "status": "ok",
        "uptime_seconds": round(uptime, 1),
        "service": "prometheus-world",
    }


@router.get("/ready")
async def readiness_check() -> dict[str, Any]:
    """Readiness probe — returns real system status from the database."""
    async with get_session_factory()() as session:
        phases = await get_construction_phases(session)

    return {
        "ready": True,
        "build_progress": _count_phases(phases),
        "buildings": _building_summary(phases),
    }


def _count_phases(phases: dict[str, ConstructionPhase]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bid in BUILDING_ORDER:
        phase = phases.get(bid, ConstructionPhase.PLANNED).value.lower()
        counts[phase] = counts.get(phase, 0) + 1
    return counts


def _building_summary(phases: dict[str, ConstructionPhase]) -> list[dict[str, Any]]:
    return [
        {
            "id": bid,
            "kind": CONSTRUCTION_MANIFEST.get(bid, {}).get("kind", bid),
            "phase": phases.get(bid, ConstructionPhase.PLANNED).value.lower(),
            "prompt": CONSTRUCTION_MANIFEST.get(bid, {}).get("prompt"),
            "description": CONSTRUCTION_MANIFEST.get(bid, {}).get("description", ""),
        }
        for bid in BUILDING_ORDER
    ]

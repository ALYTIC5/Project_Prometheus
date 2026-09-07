"""Buildings API endpoint — construction manifest for the world view.

Construction phase is never hardcoded here. It comes from the same
`determine_phase` the world projection uses, against real row counts, so
/buildings and /world/state can never disagree about what is built.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from prometheus.core.db import get_session_factory
from prometheus.world.construction import (
    BUILDING_COLORS,
    BUILDING_LOCATIONS,
    BUILDING_ORDER,
    CONSTRUCTION_MANIFEST,
)
from prometheus.world.entities import ConstructionPhase
from prometheus.world.projection import get_construction_phases

router = APIRouter(prefix="/buildings", tags=["buildings"])


def _building_payload(building_id: str, phase: ConstructionPhase) -> dict[str, Any]:
    manifest = CONSTRUCTION_MANIFEST.get(building_id, {})
    return {
        "id": building_id,
        "kind": manifest.get("kind", building_id),
        "description": manifest.get("description", ""),
        "prompt": manifest.get("prompt"),
        "phase": phase.value.lower(),
        "location": BUILDING_LOCATIONS.get(building_id, {}),
        "color": BUILDING_COLORS.get(building_id, "#CCCCCC"),
        "agent_roles": manifest.get("agent_roles", []),
        "activates_on": manifest.get("activates_on", []),
    }


@router.get("/")
async def get_buildings() -> dict[str, Any]:
    """Get all buildings with their real construction status."""
    async with get_session_factory()() as session:
        phases = await get_construction_phases(session)

    buildings = [
        _building_payload(bid, phases.get(bid, ConstructionPhase.PLANNED))
        for bid in BUILDING_ORDER
    ]
    return {"buildings": buildings, "total": len(buildings)}


@router.get("/{building_id}")
async def get_building(building_id: str) -> dict[str, Any]:
    """Get details for a specific building."""
    if building_id not in CONSTRUCTION_MANIFEST:
        raise HTTPException(status_code=404, detail=f"Unknown building: {building_id}")

    async with get_session_factory()() as session:
        phases = await get_construction_phases(session)

    return _building_payload(building_id, phases.get(building_id, ConstructionPhase.PLANNED))

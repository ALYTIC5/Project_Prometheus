"""World state API endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from prometheus.core.db import get_session_factory
from prometheus.world.entities import WorldState
from prometheus.world.projection import LAWS, build_world_state, get_benchmark_curve

router = APIRouter(prefix="/world", tags=["world"])

_active_connections: dict[str, WebSocket] = {}
_world_state_cache: WorldState | None = None
_cache_time: float = 0.0
_CACHE_TTL = 5.0


@router.get("/state", response_model=WorldState)
async def get_world_state() -> WorldState:
    """Get the complete world state as a JSON object."""
    global _world_state_cache, _cache_time

    current_time = datetime.now(UTC).timestamp()
    if _world_state_cache is not None and (current_time - _cache_time) < _CACHE_TTL:
        return _world_state_cache

    async with get_session_factory()() as session:
        state = await build_world_state(session)

    _world_state_cache = state
    _cache_time = current_time
    return state


@router.get("/drilldown/{entity_type}/{entity_id}", response_model=dict[str, Any])
async def get_entity_drilldown(entity_type: str, entity_id: str) -> dict[str, Any]:
    """Get detailed metrics behind any clickable object in the world view."""
    if entity_type == "building":
        from prometheus.world.construction import get_building_info

        return get_building_info(entity_id)

    if entity_type == "law":
        for law in LAWS:
            if str(law.law_id) == entity_id:
                return {
                    "law_id": law.law_id,
                    "name": law.name,
                    "compliant": law.compliant,
                    "last_violation": law.last_violation,
                    "summary": law.summary,
                }

    if entity_type == "benchmark":
        async with get_session_factory()() as session:
            curve = await get_benchmark_curve(session)
        current_value = curve[-1]["equity"] if curve else 1000.0
        return {
            "title": "Buy-and-Hold Benchmark",
            "description": "The €1,000 buy-and-hold test that all strategies beat or fail",
            "initial_value": 1000.0,
            "current_value": current_value,
            "return_pct": (current_value - 1000.0) / 1000.0 * 100,
            # Nothing computes benchmark risk metrics yet — backtest/benchmark.py
            # (PROMPT 2) produces them. Reporting a fabricated number here would
            # be worse than reporting nothing.
            "sharpe": 0.0,
            "max_drawdown": 0.0,
        }

    return {"error": f"Unknown entity type: {entity_type}", "id": entity_id}


@router.websocket("/deltas")
async def world_deltas(websocket: WebSocket) -> None:
    """WebSocket that pushes world state deltas on change."""
    await websocket.accept()
    client_id = f"client-{id(websocket)}"
    _active_connections[client_id] = websocket

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _active_connections.pop(client_id, None)


async def broadcast_world_update() -> None:
    """Broadcast a full world state update to all websocket clients."""
    global _world_state_cache

    async with get_session_factory()() as session:
        state = await build_world_state(session)
    delta = jsonable_encoder(state)

    connections_to_remove = []
    for client_id, ws in _active_connections.items():
        try:
            await ws.send_text(json.dumps({"type": "world_update", "data": delta}))
        except Exception:
            connections_to_remove.append(client_id)

    for client_id in connections_to_remove:
        _active_connections.pop(client_id, None)


@router.get("/tick", response_model=dict[str, Any])
async def get_world_tick() -> dict[str, Any]:
    """Get just the current tick count and timestamp."""
    state = await get_world_state()
    return {
        "tick": state.tick,
        "generated_at": state.generated_at.isoformat(),
        "data_version": state.source_data_version,
    }


def start_background_updater() -> None:
    """Start the background task that updates websockets."""

    async def update_loop() -> None:
        while True:
            await asyncio.sleep(5.0)
            await broadcast_world_update()

    _bg_task = asyncio.create_task(update_loop())  # noqa: RUF006

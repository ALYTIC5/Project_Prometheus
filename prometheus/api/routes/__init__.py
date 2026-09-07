"""API routes package."""

from prometheus.api.routes.buildings import router as buildings_router
from prometheus.api.routes.health import router as health_router
from prometheus.api.routes.scoreboard import router as scoreboard_router
from prometheus.api.routes.world import router as world_router

__all__ = ["buildings_router", "health_router", "scoreboard_router", "world_router"]

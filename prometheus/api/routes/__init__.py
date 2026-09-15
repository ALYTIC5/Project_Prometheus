"""API routes package."""

from prometheus.api.routes.buildings import router as buildings_router
from prometheus.api.routes.experiments import router as experiments_router
from prometheus.api.routes.health import router as health_router
from prometheus.api.routes.scoreboard import router as scoreboard_router
from prometheus.api.routes.strategies import router as strategies_router
from prometheus.api.routes.world import router as world_router

__all__ = [
    "buildings_router",
    "experiments_router",
    "health_router",
    "scoreboard_router",
    "strategies_router",
    "world_router",
]

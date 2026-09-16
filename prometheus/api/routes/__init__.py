"""API routes package."""

from prometheus.api.routes.buildings import router as buildings_router
from prometheus.api.routes.experiments import router as experiments_router
from prometheus.api.routes.health import router as health_router
from prometheus.api.routes.queue import router as queue_router
from prometheus.api.routes.scoreboard import router as scoreboard_router
from prometheus.api.routes.strategies import router as strategies_router
from prometheus.api.routes.violations import router as violations_router
from prometheus.api.routes.world import router as world_router

__all__ = [
    "buildings_router",
    "experiments_router",
    "health_router",
    "queue_router",
    "scoreboard_router",
    "strategies_router",
    "violations_router",
    "world_router",
]

"""FastAPI application entry point.

Serves the API and (optionally) the static Next.js frontend from the
same container. The frontend is a separate Next.js project that gets
statically exported and served by FastAPI's StaticFiles mount in
production.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from prometheus.api.routes import (
    buildings_router,
    experiments_router,
    health_router,
    queue_router,
    scoreboard_router,
    strategies_router,
    violations_router,
    world_router,
)
from prometheus.api.routes.world import start_background_updater

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "out"


def resolve_static_path(path: str, root: Path) -> Path | None:
    """Resolve a request path against a Next.js static export directory.

    Next writes a non-root app-router page as `<path>.html` (no trailing
    slash by default), which sits ALONGSIDE any same-named directory copied
    from public/ (e.g. the `/sprites` page exports to `sprites.html`, while
    `public/sprites/*.png` exports to the `sprites/` directory) -- checking
    only the bare path first would resolve to that directory and silently
    fall through to the SPA shell instead of the real page. Exact-file match
    still wins first, so a real static asset under a route-shaped path is
    never shadowed by this.
    """
    candidates = [root / path, root / f"{path}.html", root / path / "index.html"]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan: startup and shutdown hooks.

    Starts the background task that pushes world-state deltas over the
    /world/deltas WebSocket, and cancels it cleanly on shutdown.
    """
    updater_task = start_background_updater()
    try:
        yield
    finally:
        updater_task.cancel()
        await asyncio.gather(updater_task, return_exceptions=True)


app = FastAPI(
    title="Project Prometheus — World API",
    description=(
        "The world state projection. A pure function of database state. "
        "The frontend renders WorldState and holds no business logic."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # Wildcard origin + credentials is a real misconfiguration, and nothing
    # here is credentialed. Public read-only API.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(world_router)
app.include_router(scoreboard_router)
app.include_router(buildings_router)
app.include_router(strategies_router)
app.include_router(experiments_router)
app.include_router(violations_router)
app.include_router(queue_router)


@app.get("/api/info", tags=["meta"])
def api_info() -> dict[str, Any]:
    """API metadata.

    Describes the API surface only. Live build progress belongs to
    /world/state's `build_progress`, which is DB-backed; duplicating it here
    without a DB call could only ever produce a stale lie.
    """
    return {
        "name": "Project Prometheus",
        "version": "0.1.0",
        "endpoints": {
            "world_state": "/world/state",
            "scoreboard": "/scoreboard/",
            "buildings": "/buildings/",
            "drilldown": "/world/drilldown/{type}/{id}",
            "health": "/health/",
            "ready": "/health/ready",
        },
    }


@app.get("/api", tags=["meta"])
def api_root() -> dict[str, Any]:
    """API root."""
    return {
        "name": "Project Prometheus",
        "version": "0.1.0",
        "endpoints": [
            "/api/info",
            "/world/state",
            "/world/drilldown/{type}/{id}",
            "/world/deltas (WebSocket)",
            "/scoreboard/",
            "/buildings/",
            "/buildings/{id}",
            "/health/",
            "/health/ready",
        ],
    }


if FRONTEND_DIST.exists():
    static_path = FRONTEND_DIST / "_next"
    if static_path.exists():
        app.mount("/_next", StaticFiles(directory=str(static_path)), name="next_static")

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    @app.get("/{path:path}")
    async def serve_static(path: str) -> Any:
        resolved = resolve_static_path(path, FRONTEND_DIST)
        if resolved is not None:
            return FileResponse(str(resolved))
        index_path = FRONTEND_DIST / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse(
            status_code=404,
            content={"error": "Frontend not built. Run `npm run build` in /frontend/"},
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "prometheus.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

"""POST /admin/worker/force and the worker_now tool's overlap guard."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import prometheus.core.db as core_db
from prometheus.main import app
from tools.ops.worker_now import active_execution


def test_active_execution_detects_a_running_worker() -> None:
    assert active_execution([{"status": "EXITED"}, {"status": "CRASHED"}]) is None
    running = {"status": "RUNNING", "createdAt": "x"}
    assert active_execution([running, {"status": "EXITED"}]) is running


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))
    core_db._engine = None
    core_db._session_factory = None
    with TestClient(app) as test_client:
        yield test_client


@_needs_db
@pytest.mark.db
def test_disabled_without_a_configured_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    response = client.post("/admin/worker/force", json={"concerns": ["research"]})
    assert response.status_code == 503


@_needs_db
@pytest.mark.db
def test_rejects_a_wrong_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "right")
    for headers in ({}, {"X-Admin-Token": "wrong"}):
        response = client.post(
            "/admin/worker/force", json={"concerns": ["research"]}, headers=headers
        )
        assert response.status_code == 401


@_needs_db
@pytest.mark.db
def test_rejects_unknown_concerns(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "right")
    response = client.post(
        "/admin/worker/force",
        json={"concerns": ["research", "drop_tables"]},
        headers={"X-Admin-Token": "right"},
    )
    assert response.status_code == 422


@_needs_db
@pytest.mark.db
def test_makes_named_concerns_due(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "right")
    response = client.post(
        "/admin/worker/force",
        json={"concerns": ["research", "llm_ingestion"]},
        headers={"X-Admin-Token": "right"},
    )
    assert response.status_code == 200
    assert response.json() == {"due_now": ["llm_ingestion", "research"]}

    async def ages() -> dict[str, float]:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT concern, extract(epoch FROM now() - last_run_at) AS age "
                        "FROM worker_cadence WHERE concern IN ('research', 'llm_ingestion')"
                    )
                )
            ).all()
        await engine.dispose()
        return {row.concern: float(row.age) for row in rows}

    assert all(age > 20 * 86400 for age in asyncio.run(ages()).values())

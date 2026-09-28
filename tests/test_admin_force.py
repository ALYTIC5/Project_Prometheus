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


def test_force_without_now_only_marks_due_and_never_starts_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manually started run is replaced by the next scheduled tick, so by
    default worker_now only back-dates concerns and lets cron run them."""
    from tools.ops import worker_now

    started: list[str] = []
    monkeypatch.setattr(worker_now, "recent_executions", lambda: [])
    monkeypatch.setattr(worker_now, "force_due", lambda concerns: concerns)
    monkeypatch.setattr(worker_now, "railway_graphql", lambda document: started.append(document))
    assert worker_now.main(["run", "--force", "research"]) == 0
    assert started == []
    assert worker_now.main(["run", "--force", "research", "--now"]) == 0
    assert started == [worker_now._RUN_NOW]


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
def test_clear_halt_needs_a_token_a_reason_and_a_halt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "right")
    headers = {"X-Admin-Token": "right"}
    url = "/admin/promotion-halt/clear"
    reason = "gate verified: 70 ledger tests, no breach since"

    async def halt() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO evaluator.promotion_halts (event, reason) VALUES ('HALT', 't')")
            )
        await engine.dispose()

    asyncio.run(halt())
    assert client.post(url, json={"reason": reason}).status_code == 401
    assert client.post(url, json={"reason": "ok"}, headers=headers).status_code == 422
    assert client.post(url, json={"reason": reason}, headers=headers).json() == {
        "promotions_halted": False
    }
    assert client.post(url, json={"reason": reason}, headers=headers).status_code == 409


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

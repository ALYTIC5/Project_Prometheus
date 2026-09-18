"""Smoke tests for PROMPT S's route additions -- buildings.row_count,
experiments.hypothesis/parent_experiment_id, the new /queue/ route, and
world.py's benchmark drilldown curve field. No existing test file drives
the app through a real HTTP client, so this is the first; kept to the
plain-request-shape assertions these routes actually promise, not a full
API contract suite.

Marked db and skipped locally without TEST_DATABASE_URL, same as the
other db-backed test modules -- TestClient triggers the app's lifespan,
which needs a real DATABASE_URL-reachable Postgres with migrations applied.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import prometheus.core.db as core_db
from prometheus.main import app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0008 applied)",
    ),
]


@pytest.fixture(autouse=True)
def _fresh_core_engine() -> Iterator[None]:
    """core.db.get_engine()'s module-global engine is created inside
    whichever event loop is running on first use and cached for the
    process. TestClient spins its own event loop per instantiation, so a
    second test in this file reusing the cached engine raises "Event loop
    is closed" on its first query. Reset it before each test, same fix as
    tests/test_queue_semantics.py's identical problem."""
    core_db._engine = None
    core_db._session_factory = None
    yield


def test_buildings_response_carries_row_count() -> None:
    with TestClient(app) as client:
        response = client.get("/buildings/")
    assert response.status_code == 200
    buildings = response.json()["buildings"]
    assert buildings, "construction manifest must not be empty"
    for building in buildings:
        assert isinstance(building["row_count"], int)
        assert building["row_count"] >= 0


def test_experiments_response_carries_lineage_fields() -> None:
    with TestClient(app) as client:
        response = client.get("/experiments/")
    assert response.status_code == 200
    body = response.json()
    assert "experiments" in body
    # Empty table is a valid, honest state -- the field must be present on
    # the shape whether or not any rows exist yet.
    for experiment in body["experiments"]:
        assert "hypothesis" in experiment
        assert "parent_experiment_id" in experiment


def test_queue_status_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/queue/")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "pending_by_kind",
        "in_flight",
        "dead_letter_count",
        "failed_pending_count",
    }
    assert isinstance(body["dead_letter_count"], int)
    assert isinstance(body["failed_pending_count"], int)


def test_strategies_response_carries_validation_and_lineage_fields() -> None:
    with TestClient(app) as client:
        response = client.get("/strategies/")
    assert response.status_code == 200
    body = response.json()
    assert "strategies" in body
    # Empty table is a valid, honest state -- the field must be present on
    # the shape whether or not any rows exist yet, same posture as
    # test_experiments_response_carries_lineage_fields above.
    for strategy in body["strategies"]:
        for field in (
            "verdict", "score", "pbo", "deflated_sharpe",
            "excess_return", "excess_sharpe", "reason_codes",
            "generation", "parent",
        ):
            assert field in strategy
        assert isinstance(strategy["generation"], int)
        assert strategy["generation"] >= 0


def test_benchmark_drilldown_carries_curve() -> None:
    with TestClient(app) as client:
        response = client.get("/world/drilldown/benchmark/current")
    assert response.status_code == 200
    body = response.json()
    assert "curve" in body
    assert isinstance(body["curve"], list)

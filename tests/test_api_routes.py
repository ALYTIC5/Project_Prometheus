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

import asyncio
import json
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import prometheus.core.db as core_db
from prometheus.main import app
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

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
        # From the latest results row -- null on the insufficient_data
        # path (a Decision with no Result), an honest gap not an error.
        assert "total_return_pct" in experiment
        assert "benchmark_return_pct" in experiment
        assert experiment["total_return_pct"] is None or isinstance(
            experiment["total_return_pct"], int | float
        )


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
    # family/symbol read straight off the job's own payload (the spec every
    # run_backtest job already carries) -- present on the shape even when
    # nothing is in flight right now.
    for job in body["in_flight"]:
        assert "family" in job
        assert "symbol" in job


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
            "generation", "parent", "mutation_label", "asset_class",
        ):
            assert field in strategy
        assert isinstance(strategy["generation"], int)
        assert strategy["generation"] >= 0
        # asset_class is resolved from universe_membership, not the spec
        # itself -- None is the honest state for a symbol with no
        # universe_membership row (a spec built before that symbol was
        # ever synced), not an invented default.
        assert strategy["asset_class"] is None or isinstance(strategy["asset_class"], str)


def test_strategies_endpoint_survives_a_rotation_spec_row() -> None:
    """C1 (final-review fix wave): `experiments.runner.run_one` inserts
    RotationSpec rows into the same `strategies` table as StrategySpec
    rows. This route used to parse every row with
    `StrategySpec.model_validate()`, which raises ValidationError on a
    rotation spec (no `symbol`; `extra="forbid"`) -- so ONE rotation
    strategy anywhere in the table made GET /strategies/ return 500 for
    every row, not just that one. Inserted idempotently with a fixed id
    so repeated CI runs neither collide nor accumulate."""
    spec = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLK", "XLF", "XLE"),
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    strategy_id = "SECTOR_MOMENTUM_ROTATION-9001"
    asyncio.run(_insert_rotation_strategy(strategy_id, spec))
    # TestClient runs its own event loop; the module global engine the
    # insert above created belongs to the loop asyncio.run just closed.
    core_db._engine = None
    core_db._session_factory = None

    with TestClient(app) as client:
        response = client.get("/strategies/")
        assert response.status_code == 200
        one = client.get(f"/strategies/{strategy_id}")

    assert one.status_code == 200
    body = one.json()
    assert body["family"] == ROTATION_FAMILY_SECTOR_MOMENTUM
    assert list(body["spec"]["universe"]) == ["XLK", "XLF", "XLE"]


_INSERT_ROTATION_STRATEGY = text(
    """
    INSERT INTO strategies (id, family, spec, status)
    VALUES (:id, :family, CAST(:spec AS JSONB), 'PROMISING')
    ON CONFLICT (id) DO NOTHING
    """
)


async def _insert_rotation_strategy(strategy_id: str, spec: RotationSpec) -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                _INSERT_ROTATION_STRATEGY,
                {
                    "id": strategy_id,
                    "family": spec.family,
                    "spec": json.dumps(spec.model_dump()),
                },
            )
    finally:
        await engine.dispose()


def test_benchmark_drilldown_carries_curve() -> None:
    with TestClient(app) as client:
        response = client.get("/world/drilldown/benchmark/current")
    assert response.status_code == 200
    body = response.json()
    assert "curve" in body
    assert isinstance(body["curve"], list)


def test_pipeline_status_reports_all_five_concerns() -> None:
    with TestClient(app) as client:
        response = client.get("/pipeline/")
    assert response.status_code == 200
    concerns = response.json()["concerns"]
    assert {c["concern"] for c in concerns} == {
        "ingest", "research", "paper", "llm_ingestion", "ablation",
    }
    for concern in concerns:
        assert isinstance(concern["interval_seconds"], int | float)
        assert isinstance(concern["is_due"], bool)
        # Empty worker_cadence (never run) is a valid, honest state -- the
        # field must be present and null, not a crash, same posture as
        # test_experiments_response_carries_lineage_fields above.
        assert "last_run_at" in concern
        assert "next_due_at" in concern


def test_research_papers_response_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/research-papers/")
    assert response.status_code == 200
    body = response.json()
    assert "papers" in body
    # Empty table is a valid, honest state (no papers ingested yet).
    for paper in body["papers"]:
        for field in ("id", "arxiv_id", "title", "abstract", "ingested_at", "extracted"):
            assert field in paper
    assert body["page"] == 1
    assert body["total"] >= len(body["papers"])


def test_research_papers_paging_is_bounded() -> None:
    with TestClient(app) as client:
        assert client.get("/research-papers/?page_size=500").status_code == 422
        assert client.get("/research-papers/?page=0").status_code == 422


def test_research_summary_response_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/research-papers/summary")
    assert response.status_code == 200
    body = response.json()
    for field in (
        "papers", "papers_extracted", "papers_skipped_off_topic", "claims",
        "testable_claims", "links",
        "hypotheses_from_claims", "links_by_relation",
    ):
        assert field in body


def test_research_learned_response_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/research-papers/learned")
    assert response.status_code == 200
    for item in response.json()["learned"]:
        assert {"claim", "paper", "strategy", "hypothesis_text"} <= set(item)


def test_research_health_canaries_exposes_aggregates_only() -> None:
    with TestClient(app) as client:
        response = client.get("/research-health/canaries")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "canaries_registered", "canaries_evaluated", "breaches", "false_pass_rate",
        "last_breach_at", "promotions_halted",
    }


def test_research_paper_detail_404s_for_unknown_paper() -> None:
    with TestClient(app) as client:
        response = client.get("/research-papers/999999999")
    assert response.status_code == 404


def test_paper_trading_response_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/paper/")
    assert response.status_code == 200
    body = response.json()
    assert "champions" in body
    assert isinstance(body["total"], int)
    # No strategy has ever reached CHAMPION status (every validated
    # strategy so far is REJECT) -- an empty list is the honest, expected
    # state today, not a bug. Shape asserted for whenever one exists.
    for champion in body["champions"]:
        for field in (
            "strategy_id",
            "family",
            "symbol",
            "equity_curve",
            "recent_orders",
            "recent_findings",
        ):
            assert field in champion
        for point in champion["equity_curve"]:
            assert "date" in point
            assert "equity" in point


def test_clusters_response_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/clusters/")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["total"], int)
    # No batch has clustered yet in a fresh/small corpus is a valid,
    # honest state -- an empty list, not a bug. Shape asserted for
    # whenever a real cluster (>1 member) exists.
    for cluster in body["clusters"]:
        assert "cluster_key" in cluster
        assert "mean_pairwise_correlation" in cluster
        assert len(cluster["members"]) > 1
        for member in cluster["members"]:
            for field in (
                "strategy_id",
                "family",
                "config_hash",
                "is_representative",
                "score",
                "verdict",
            ):
                assert field in member

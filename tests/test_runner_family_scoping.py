"""Regression test for the bug documented in
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md:
enqueue_grid/validate_grid were hardcoded to a single family in
production (worker.py's _run_research() always passed family="MOMENTUM"),
so no other strategy family could ever be enqueued or reach 'VALIDATED'
status. enqueue_baseline_grid/validate_baseline_grid must source their
specs from generate_baseline_grid (every classic-template family), not
the MOMENTUM-only generate_grid.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from prometheus.experiments.runner import enqueue_baseline_grid, validate_baseline_grid


async def test_enqueue_baseline_grid_calls_generate_baseline_grid() -> None:
    with (
        patch(
            "prometheus.experiments.runner.generate_baseline_grid", return_value=[]
        ) as mock_generate,
        patch(
            "prometheus.experiments.runner.enqueue_specs", new=AsyncMock(return_value=[])
        ) as mock_enqueue_specs,
    ):
        await enqueue_baseline_grid(
            "BTC/USDT", "1d", 800,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )
    mock_generate.assert_called_once_with("BTC/USDT", "1d")
    mock_enqueue_specs.assert_called_once()


async def test_validate_baseline_grid_calls_generate_baseline_grid() -> None:
    with (
        patch(
            "prometheus.experiments.runner.generate_baseline_grid", return_value=[]
        ) as mock_generate,
        patch(
            "prometheus.experiments.runner.validate_specs", new=AsyncMock(return_value=[])
        ) as mock_validate_specs,
    ):
        await validate_baseline_grid(AsyncMock(), "BTC/USDT", "1d", 800)
    mock_generate.assert_called_once_with("BTC/USDT", "1d")
    mock_validate_specs.assert_called_once()


@pytest.mark.db
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0007 applied)",
)
async def test_enqueue_specs_enqueues_a_non_momentum_spec() -> None:
    from prometheus.experiments.runner import enqueue_specs
    from prometheus.strategy.spec import StrategySpec

    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

    spec = StrategySpec(
        family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
        lookback_window=20, band_multiplier=2.0, expected_horizon=20,
    )
    job_ids = await enqueue_specs(
        "BTC/USDT", "1d", [spec], 800,
        priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
    )
    assert len(job_ids) == 1

"""Regression test for the bug documented in
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md:
enqueue_grid/validate_grid were hardcoded to a single family in
production (worker.py's _run_research() always passed family="MOMENTUM"),
so no other strategy family could ever be enqueued or reach 'VALIDATED'
status. enqueue_baseline_grid/validate_baseline_grid must source their
specs from generate_baseline_grid (every classic-template family), not
the MOMENTUM-only generate_grid.

Also covers Task 8 (cross-sectional rotation plan): run_one/enqueue_specs/
_run_job generalized to accept RotationSpec alongside StrategySpec -- the
same "one family type silently excluded from the real pipeline" failure
mode this file already exists to catch, now for a whole spec TYPE rather
than one family string.
"""
from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from prometheus.experiments.runner import enqueue_baseline_grid, validate_baseline_grid


class _FakeSessionCtx:
    """Stands in for get_session()'s real `async with`-compatible return
    value -- a plain MagicMock/AsyncMock does not support __aenter__/
    __aexit__ without extra configuration, so a tiny real async context
    manager is less fragile than trying to coax that out of a mock."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


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


async def test_enqueue_specs_tags_spec_kind_by_isinstance() -> None:
    """Task 8: enqueue_specs's job payload must carry "spec_kind" so
    _run_job knows which model to deserialize with -- "rotation" for a
    RotationSpec, "strategy" for a StrategySpec, decided purely by
    isinstance, not by inspecting the spec's own fields."""
    from prometheus.experiments.runner import enqueue_specs
    from prometheus.research.rotation_generate import generate_dual_momentum_grid
    from prometheus.strategy.spec import StrategySpec

    strategy_spec = StrategySpec(
        family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
        lookback_window=20, band_multiplier=2.0, expected_horizon=20,
    )
    rotation_spec = generate_dual_momentum_grid()[0]

    captured_payloads = []

    async def _fake_enqueue(session, **kwargs):
        captured_payloads.append(kwargs["payload"])
        return "job-id"

    fake_session = AsyncMock()

    with (
        patch(
            "prometheus.experiments.runner.get_session",
            return_value=_FakeSessionCtx(fake_session),
        ),
        patch("prometheus.experiments.runner.enqueue", new=AsyncMock(side_effect=_fake_enqueue)),
    ):
        await enqueue_specs(
            "", "", [strategy_spec, rotation_spec], 800,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )

    assert captured_payloads[0]["spec_kind"] == "strategy"
    assert captured_payloads[1]["spec_kind"] == "rotation"


async def test_run_job_defaults_missing_spec_kind_to_strategy() -> None:
    """A job enqueued before this change has no "spec_kind" key at all --
    _run_job must still deserialize it as a StrategySpec, not crash or
    silently misroute it to RotationSpec.model_validate."""
    from prometheus.experiments.queue import Job
    from prometheus.experiments.runner import _RUN_BACKTEST_KIND, _run_job
    from prometheus.strategy.spec import StrategySpec

    strategy_spec = StrategySpec(
        family="BOLLINGER", symbol="BTC/USDT", timeframe="1d",
        lookback_window=20, band_multiplier=2.0, expected_horizon=20,
    )
    job = Job(
        id="job-1",
        kind=_RUN_BACKTEST_KIND,
        payload={"spec": strategy_spec.model_dump(), "days": 800},  # no spec_kind key
        attempts=0,
        max_attempts=3,
        agent_role="engineer",
        current_stage="forge",
        next_stage="arena",
        experiment_id=None,
    )

    with (
        patch(
            "prometheus.experiments.runner.get_session",
            return_value=_FakeSessionCtx(AsyncMock()),
        ),
        patch(
            "prometheus.experiments.runner.run_one", new=AsyncMock(return_value="exp-1")
        ) as mock_run_one,
    ):
        result = await _run_job(job)

    assert result == "exp-1"
    called_spec = mock_run_one.call_args.args[1]
    assert isinstance(called_spec, StrategySpec)
    assert called_spec.config_hash() == strategy_spec.config_hash()


async def test_run_job_dispatches_rotation_spec_kind() -> None:
    """The "rotation" branch: _run_job must deserialize job.payload["spec"]
    with RotationSpec.model_validate, not StrategySpec.model_validate,
    when spec_kind == "rotation"."""
    from prometheus.experiments.queue import Job
    from prometheus.experiments.runner import _RUN_BACKTEST_KIND, _run_job
    from prometheus.research.rotation_generate import generate_dual_momentum_grid
    from prometheus.strategy.rotation_spec import RotationSpec

    rotation_spec = generate_dual_momentum_grid()[0]
    job = Job(
        id="job-2",
        kind=_RUN_BACKTEST_KIND,
        payload={
            "spec": rotation_spec.model_dump(),
            "spec_kind": "rotation",
            "days": 800,
        },
        attempts=0,
        max_attempts=3,
        agent_role="engineer",
        current_stage="forge",
        next_stage="arena",
        experiment_id=None,
    )

    with (
        patch(
            "prometheus.experiments.runner.get_session",
            return_value=_FakeSessionCtx(AsyncMock()),
        ),
        patch(
            "prometheus.experiments.runner.run_one", new=AsyncMock(return_value="exp-2")
        ) as mock_run_one,
    ):
        result = await _run_job(job)

    assert result == "exp-2"
    called_spec = mock_run_one.call_args.args[1]
    assert isinstance(called_spec, RotationSpec)
    assert called_spec.config_hash() == rotation_spec.config_hash()


async def test_enqueue_rotation_grid_calls_generate_grid_fn_and_enqueue_specs() -> None:
    """enqueue_rotation_grid is a thin wrapper: it calls the given
    zero-arg grid generator (not enqueue_grid's per-call symbol/timeframe
    interface -- a RotationSpec's universe is fixed by its own grid
    generator) and forwards the result straight to enqueue_specs."""
    from prometheus.experiments.runner import enqueue_rotation_grid
    from prometheus.research.rotation_generate import generate_dual_momentum_grid

    with patch(
        "prometheus.experiments.runner.enqueue_specs", new=AsyncMock(return_value=["job-3"])
    ) as mock_enqueue_specs:
        job_ids = await enqueue_rotation_grid(
            generate_dual_momentum_grid, 800,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )

    assert job_ids == ["job-3"]
    mock_enqueue_specs.assert_called_once()
    call_args = mock_enqueue_specs.call_args.args
    assert call_args[0] == ""
    assert call_args[1] == ""
    assert call_args[2] == generate_dual_momentum_grid()
    assert call_args[3] == 800


@pytest.mark.db
async def test_run_one_accepts_rotation_spec(db_session) -> None:
    """Task 8's own acceptance bar: run_one's 4 isinstance(spec,
    StrategySpec) generalizations must route a RotationSpec end-to-end
    through load_point_in_time -> membership_windows ->
    run_portfolio_backtest -> real Experiment/Result/Decision rows,
    against real Postgres -- not a mocked backtest.

    Synthetic, uniquely-suffixed symbols (not real SPY/EFA/TLT): same
    precedent tests/test_ablation_placebo.py's own random suffix already
    establishes, avoiding a collision with any real historical data
    already ingested for those symbols under ohlcv_bars' (symbol,
    timeframe, event_time, revision) uniqueness constraint, and keeping
    this test safe to re-run without a DB reset. A short lookback_days
    (20, not DUAL_MOMENTUM_GEM's production 252) keeps the seeded bar
    count small -- this test exercises run_one's dispatch, not the
    production grid's exact parameters."""
    from prometheus.data.models import OhlcvBar as OhlcvBarModel
    from prometheus.data.models import UniverseMembership
    from prometheus.experiments.runner import run_one
    from prometheus.strategy.rotation_spec import ROTATION_FAMILY_DUAL_MOMENTUM_GEM, RotationSpec

    run_id = uuid.uuid4().hex[:8]
    universe = (f"EQA{run_id}", f"EQB{run_id}", f"DEF{run_id}")  # last = defensive leg
    start = datetime(2023, 1, 1, tzinfo=UTC)
    n_bars = 60
    lookback_days = 20

    for i, symbol in enumerate(universe):
        rng = random.Random(100 + i)
        price = 100.0
        for day in range(n_bars):
            price *= 1 + rng.uniform(-0.01, 0.01)
            event_time = start + timedelta(days=day)
            db_session.add(
                OhlcvBarModel(
                    symbol=symbol, timeframe="1d", event_time=event_time,
                    available_at=event_time + timedelta(minutes=5),
                    source="test-fixture", revision=1,
                    open=price, high=price * 1.01, low=price * 0.99, close=price,
                    volume=1000.0,
                )
            )
        db_session.add(
            UniverseMembership(
                symbol=symbol, exchange="test", asset_class="etf",
                listed_at=start.date(), delisted_at=None,
            )
        )
    await db_session.flush()

    spec = RotationSpec(
        family=ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
        universe=universe,
        timeframe="1d",
        lookback_days=lookback_days,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )

    end = start + timedelta(days=n_bars)
    experiment_id = await run_one(db_session, spec, start, end)

    assert experiment_id is not None

    row = (
        await db_session.execute(
            text("SELECT config_hash, seed FROM experiments WHERE id = :id"),
            {"id": experiment_id},
        )
    ).mappings().first()
    assert row is not None
    assert row["config_hash"] == spec.config_hash()

    decision_row = (
        await db_session.execute(
            text("SELECT decision FROM decisions WHERE experiment_id = :id"),
            {"id": experiment_id},
        )
    ).mappings().first()
    assert decision_row is not None
    assert decision_row["decision"]["decision"] in ("ACCEPT", "REJECT")

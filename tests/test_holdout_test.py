"""The one-shot vault test (Law 3, 2026-09-28): scored on vault bars only,
one-sided p < 0.05 against buy-and-hold, once per spec, recorded in the
evaluator schema; and the gate's discoveries wait for it (AWAITING_HOLDOUT)."""
from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.runner import _apply_discovery_gate
from prometheus.research.hypotheses import register_hypothesis
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.decision import DecisionResult, Verdict
from prometheus.validation.discovery_gate import ExcessReturnPValue
from prometheus.validation.holdout import HoldoutAccessDenied, load_holdout_config
from prometheus.validation.holdout_test import (
    holdout_passed_for_spec,
    run_holdout_test,
    vault_is_open,
    vault_slice,
)
from tests.holdout_helpers import record_holdout_verdict

HOLDOUT_START = load_holdout_config()[0].holdout_start


def test_vault_opens_six_months_after_the_holdout_starts() -> None:
    config, _ = load_holdout_config()
    assert config.vault_opens == date(2027, 3, 16)
    assert not vault_is_open(date(2026, 9, 28))
    assert vault_is_open(date(2027, 3, 16))


def test_vault_slice_keeps_one_base_point_before_the_vault() -> None:
    curve = [(f"2026-09-{d:02d}T00:05:00+00:00", float(d)) for d in range(10, 20)]
    sliced = vault_slice(curve, date(2026, 9, 16))
    assert sliced[0] == (date(2026, 9, 15), 15.0)
    assert [d for d, _ in sliced[1:]] == [date(2026, 9, d) for d in range(16, 20)]


def _curves(*, vault_edge: float, seed: int) -> Any:
    """Daily benchmark/strategy curves around HOLDOUT_START. Before the
    vault the strategy loses badly (proves only vault returns are scored);
    inside it earns `vault_edge` per day over the benchmark, plus noise."""
    rng = random.Random(seed)
    start = HOLDOUT_START - timedelta(days=90)
    bench, strat = 1000.0, 1000.0
    bench_curve: list[tuple[date, float]] = []
    strat_curve: list[tuple[str, float]] = []
    for i in range(200):
        day = start + timedelta(days=i)
        r = rng.gauss(0, 0.02)
        bench *= 1 + r
        edge = vault_edge if day >= HOLDOUT_START else -0.01
        strat *= 1 + r + edge + rng.gauss(0, 0.002)
        bench_curve.append((day, bench))
        strat_curve.append((f"{day.isoformat()}T00:05:00+00:00", strat))
    return SimpleNamespace(
        equity_curve=tuple(strat_curve), benchmark=SimpleNamespace(equity_curve=bench_curve)
    )


def _spec() -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM", symbol=f"V{uuid.uuid4().hex[:8]}/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5,
    )


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("HOLDOUT_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL and HOLDOUT_DATABASE_URL",
)
_NOW = datetime.combine(HOLDOUT_START + timedelta(days=110), datetime.min.time(), UTC)


async def _test(session: AsyncSession, spec: StrategySpec, result: Any) -> Any:
    with patch("prometheus.validation.holdout_test.run_backtest", return_value=result):
        return await run_holdout_test(
            session, strategy_id="S-test", spec=spec, experiment_id=None,
            warmup_days=30, now=_NOW,
        )


@_needs_db
@pytest.mark.db
async def test_a_real_edge_on_vault_bars_passes_once(db_session: AsyncSession) -> None:
    spec = _spec()
    verdict = await _test(db_session, spec, _curves(vault_edge=0.004, seed=1))
    assert verdict.passed and verdict.p_value is not None and verdict.p_value < 0.05
    assert verdict.window_start is not None and verdict.window_start < HOLDOUT_START
    assert await holdout_passed_for_spec(db_session, spec.config_hash())
    # One shot, ever.
    with pytest.raises(HoldoutAccessDenied):
        await _test(db_session, spec, _curves(vault_edge=0.004, seed=1))


@_needs_db
@pytest.mark.db
async def test_no_edge_on_vault_bars_fails_and_is_final(db_session: AsyncSession) -> None:
    spec = _spec()
    verdict = await _test(db_session, spec, _curves(vault_edge=0.0, seed=2))
    assert not verdict.passed
    assert not await holdout_passed_for_spec(db_session, spec.config_hash())
    row = (
        await db_session.execute(
            text("SELECT passed FROM evaluator.holdout_verdicts WHERE config_hash = :h"),
            {"h": spec.config_hash()},
        )
    ).one()
    assert row.passed is False


@_needs_db
@pytest.mark.db
async def test_gate_discoveries_wait_for_the_vault(db_session: AsyncSession) -> None:
    spec = _spec()
    await register_hypothesis(db_session, spec)
    passing = ExcessReturnPValue(p_value=1e-12, n_observations=250, sharpe_per_period=0.3)
    result = SimpleNamespace(equity_curve=None, benchmark=SimpleNamespace(equity_curve=None))
    promote = DecisionResult(Verdict.PROMOTE, 1.0, [])
    with patch("prometheus.experiments.runner.excess_return_pvalue", return_value=passing):
        decision, payload = await _apply_discovery_gate(
            db_session, spec=spec, result=result, decision=promote, cluster_info=None
        )
        assert payload is not None and payload["discovery"] is True
        assert decision.verdict is Verdict.PROMISING
        assert "AWAITING_HOLDOUT" in decision.reason_codes

        await record_holdout_verdict(db_session, spec.config_hash())
        decision, _ = await _apply_discovery_gate(
            db_session, spec=spec, result=result, decision=promote, cluster_info=None
        )
    assert decision.verdict is Verdict.PROMOTE

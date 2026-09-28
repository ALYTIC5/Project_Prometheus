"""One-time re-test of pre-gate promotions (2026-09-28): every CHAMPION /
VALIDATED faces the discovery gate once and goes to PROMISING; discoveries
become paper-tradable as AWAITING_HOLDOUT, failures do not; a canary that
reaches a discovery is a breach."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.regate import regate_pre_gate_promotions
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.discovery_gate import ExcessReturnPValue, run_gate_test
from prometheus.validation.promotion import paper_eligible_strategies
from prometheus.validation.status import promotions_halted
from prometheus.worker import _REGATE_MARKER

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
    ),
]

_PASS = ExcessReturnPValue(p_value=1e-12, n_observations=250, sharpe_per_period=0.3)
_FAIL = ExcessReturnPValue(p_value=0.9, n_observations=250, sharpe_per_period=-0.1)


def test_marker_fits_worker_cadence_column() -> None:
    assert len(_REGATE_MARKER) <= 16


async def _promoted(
    session: AsyncSession, status: str, gate: ExcessReturnPValue | None, *, canary: bool = False
) -> str:
    spec = StrategySpec(
        family="MOMENTUM", symbol=f"G{uuid.uuid4().hex[:8]}/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5,
    )
    strategy_id = f"G{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:i, 'MOMENTUM', CAST(:s AS jsonb), :st)"
        ),
        {"i": strategy_id, "s": spec.model_dump_json(), "st": status},
    )
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}'::jsonb, :i, :h)"
        ),
        {"e": f"E{uuid.uuid4().hex[:12]}", "i": strategy_id, "h": spec.config_hash()},
    )
    if gate is not None:
        await run_gate_test(session, spec.config_hash(), gate)
    if canary:
        await session.execute(
            text(
                "INSERT INTO evaluator.canary_strategies (strategy_id, config_hash) "
                "VALUES (:i, :h)"
            ),
            {"i": strategy_id, "h": spec.config_hash()},
        )
    return strategy_id


async def _status(session: AsyncSession, strategy_id: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT status FROM strategies WHERE id = :i"), {"i": strategy_id}
            )
        ).scalar_one()
    )


async def test_every_pre_gate_promotion_is_retested_and_demoted(
    db_session: AsyncSession,
) -> None:
    discovered = await _promoted(db_session, "CHAMPION", _PASS)
    failed = await _promoted(db_session, "CHAMPION", _FAIL)
    old_validated = await _promoted(db_session, "VALIDATED", _PASS)
    # No bars exist for this symbol: it cannot be re-tested at all.
    untestable = await _promoted(db_session, "CHAMPION", None)

    report = await regate_pre_gate_promotions(db_session, lookback_days=800)

    assert {discovered, old_validated} <= set(report.discoveries)
    assert failed in report.failed and untestable in report.untestable
    for strategy_id in (discovered, failed, old_validated, untestable):
        assert await _status(db_session, strategy_id) == "PROMISING"
    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM strategies WHERE status IN ('CHAMPION', 'VALIDATED')")
        )
    ).scalar_one()
    assert remaining == 0

    eligible = {row.id: row.label for row in await paper_eligible_strategies(db_session)}
    assert eligible.get(discovered) == "AWAITING_HOLDOUT"
    assert eligible.get(old_validated) == "AWAITING_HOLDOUT"
    assert failed not in eligible and untestable not in eligible


async def test_a_canary_reaching_a_discovery_is_a_breach(db_session: AsyncSession) -> None:
    canary = await _promoted(db_session, "CHAMPION", _PASS, canary=True)
    await regate_pre_gate_promotions(db_session, lookback_days=800)
    breaches = (
        await db_session.execute(
            text("SELECT count(*) FROM evaluator.canary_breaches WHERE strategy_id = :i"),
            {"i": canary},
        )
    ).scalar_one()
    assert breaches == 1
    assert await promotions_halted(db_session)
    assert canary not in {row.id for row in await paper_eligible_strategies(db_session)}

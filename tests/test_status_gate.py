"""validation.status.set_status: canaries can never be promoted past
PROMISING, a breach halts every promotion, and only a human clears it."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.validation.status import clear_promotion_halt, promotions_halted, set_status
from tests.holdout_helpers import record_holdout_verdict

pytestmark = pytest.mark.db


async def _strategy(session: AsyncSession, status: str = "PROMISING") -> str:
    strategy_id = f"MOMENTUM-T{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, 'MOMENTUM', '{}'::jsonb, :status)"
        ),
        {"id": strategy_id, "status": status},
    )
    return strategy_id


async def _status(session: AsyncSession, strategy_id: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT status FROM strategies WHERE id = :id"), {"id": strategy_id}
            )
        ).scalar_one()
    )


async def _make_canary(session: AsyncSession, strategy_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO evaluator.canary_strategies (strategy_id, config_hash) "
            "VALUES (:id, :h)"
        ),
        {"id": strategy_id, "h": uuid.uuid4().hex},
    )


async def _with_discovery(
    session: AsyncSession, strategy_id: str, *, vault_passed: bool = True
) -> None:
    """Law 10: a VALIDATED promotion needs a discovery for the strategy's
    latest experiment config_hash in the alpha-wealth ledger -- and (Law 3,
    2026-09-28) a passed one-shot vault test."""
    config_hash = uuid.uuid4().hex
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}'::jsonb, :s, :h)"
        ),
        {"e": f"E{uuid.uuid4().hex[:12]}", "s": strategy_id, "h": config_hash},
    )
    await session.execute(
        text(
            "INSERT INTO evaluator.alpha_wealth_ledger (test_index, config_hash, p_value, "
            "alpha_threshold, discovery, wealth_before, wealth_after, n_observations, "
            "excess_sharpe_per_period) "
            "SELECT coalesce(max(test_index), 0) + 1, :h, 0.0001, 0.001, true, 0.025, 0.049, "
            "250, 0.1 FROM evaluator.alpha_wealth_ledger"
        ),
        {"h": config_hash},
    )
    if vault_passed:
        await record_holdout_verdict(session, config_hash, strategy_id=strategy_id)


async def test_ordinary_promotion_with_a_discovery_is_written(db_session: AsyncSession) -> None:
    strategy_id = await _strategy(db_session)
    await _with_discovery(db_session, strategy_id)
    assert await set_status(db_session, strategy_id, "VALIDATED", reason="test")
    assert await _status(db_session, strategy_id) == "VALIDATED"


async def test_a_discovery_without_a_vault_pass_is_refused(db_session: AsyncSession) -> None:
    strategy_id = await _strategy(db_session)
    await _with_discovery(db_session, strategy_id, vault_passed=False)
    assert not await set_status(db_session, strategy_id, "VALIDATED", reason="test")
    assert not await set_status(db_session, strategy_id, "CHAMPION", reason="test")
    assert await _status(db_session, strategy_id) == "PROMISING"
    violations = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM research_violations "
                "WHERE violation_type = 'VALIDATED_WITHOUT_HOLDOUT' AND detail->>'strategy_id' = :s"
            ),
            {"s": strategy_id},
        )
    ).scalar_one()
    assert violations == 2


async def test_promotion_without_a_discovery_is_refused(db_session: AsyncSession) -> None:
    strategy_id = await _strategy(db_session)
    assert not await set_status(db_session, strategy_id, "VALIDATED", reason="test")
    assert await _status(db_session, strategy_id) == "PROMISING"
    violations = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM research_violations "
                "WHERE violation_type = 'VALIDATED_WITHOUT_DISCOVERY' "
                "AND detail->>'strategy_id' = :id"
            ),
            {"id": strategy_id},
        )
    ).scalar_one()
    assert violations == 1


async def test_canary_promotion_is_a_breach_and_halts_promotions(
    db_session: AsyncSession,
) -> None:
    canary = await _strategy(db_session)
    await _make_canary(db_session, canary)

    written = await set_status(db_session, canary, "VALIDATED", reason="verdict PROMOTE")

    assert written is False
    assert await _status(db_session, canary) == "PROMISING"
    breach = (
        await db_session.execute(
            text(
                "SELECT attempted_status FROM evaluator.canary_breaches WHERE strategy_id = :id"
            ),
            {"id": canary},
        )
    ).scalar_one()
    assert breach == "VALIDATED"
    assert await promotions_halted(db_session)
    violation = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM research_violations WHERE violation_type = 'CANARY_BREACH' "
                "AND detail->>'strategy_id' = :id"
            ),
            {"id": canary},
        )
    ).scalar_one()
    assert violation == 1


async def test_same_rank_rewrite_is_not_a_promotion(db_session: AsyncSession) -> None:
    """A VALIDATED canary re-validated (it slipped in before its registry
    row existed) is not a new promotion, so it is not re-counted as one."""
    canary = await _strategy(db_session, status="VALIDATED")
    await _make_canary(db_session, canary)
    assert await set_status(db_session, canary, "VALIDATED", reason="revalidated")
    assert not await promotions_halted(db_session)


async def test_canary_can_still_be_rejected(db_session: AsyncSession) -> None:
    canary = await _strategy(db_session)
    await _make_canary(db_session, canary)
    assert await set_status(db_session, canary, "REJECTED", reason="test")
    assert not await promotions_halted(db_session)


async def test_halt_blocks_every_promotion_but_not_demotion_until_cleared(
    db_session: AsyncSession,
) -> None:
    canary = await _strategy(db_session)
    await _make_canary(db_session, canary)
    await set_status(db_session, canary, "CHAMPION", reason="test")

    honest = await _strategy(db_session)
    await _with_discovery(db_session, honest)
    assert not await set_status(db_session, honest, "VALIDATED", reason="test")
    assert await _status(db_session, honest) == "PROMISING"

    champion = await _strategy(db_session, status="CHAMPION")
    assert await set_status(db_session, champion, "VALIDATED", reason="demotion")
    assert await _status(db_session, champion) == "VALIDATED"

    await clear_promotion_halt(db_session, reason="breach investigated")
    assert not await promotions_halted(db_session)
    assert await set_status(db_session, honest, "VALIDATED", reason="test")


async def test_promotion_halt_log_is_append_only(db_session: AsyncSession) -> None:
    canary = await _strategy(db_session)
    await _make_canary(db_session, canary)
    await set_status(db_session, canary, "VALIDATED", reason="test")
    with pytest.raises(Exception, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text("DELETE FROM evaluator.promotion_halts"))

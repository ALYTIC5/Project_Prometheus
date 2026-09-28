"""Law 3, 2026-09-28: no strategy becomes VALIDATED or CHAMPION without one
passed vault test, the verdicts are append-only, and research code cannot
see them (Law 9)."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.validation.discovery_gate import ExcessReturnPValue, run_gate_test
from prometheus.validation.status import set_status
from tests.holdout_helpers import record_holdout_verdict

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)

_PASS = ExcessReturnPValue(p_value=1e-9, n_observations=250, sharpe_per_period=0.3)


async def _discovered(session: AsyncSession) -> tuple[str, str]:
    strategy_id = f"L{uuid.uuid4().hex[:12]}"
    config_hash = uuid.uuid4().hex
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:i, 'MOMENTUM', '{}'::jsonb, 'PROMISING')"
        ),
        {"i": strategy_id},
    )
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}'::jsonb, :i, :h)"
        ),
        {"e": f"E{uuid.uuid4().hex[:12]}", "i": strategy_id, "h": config_hash},
    )
    assert (await run_gate_test(session, config_hash, _PASS)).discovery
    return strategy_id, config_hash


@pytest.mark.parametrize("status", ["VALIDATED", "CHAMPION"])
async def test_no_promotion_without_a_passed_vault_test(
    db_session: AsyncSession, status: str
) -> None:
    strategy_id, config_hash = await _discovered(db_session)
    assert not await set_status(db_session, strategy_id, status, reason="law 3 test")
    await record_holdout_verdict(db_session, config_hash, strategy_id=strategy_id, passed=False)
    assert not await set_status(db_session, strategy_id, status, reason="law 3 test")


async def test_a_passed_vault_test_opens_the_path(db_session: AsyncSession) -> None:
    strategy_id, config_hash = await _discovered(db_session)
    await record_holdout_verdict(db_session, config_hash, strategy_id=strategy_id)
    assert await set_status(db_session, strategy_id, "VALIDATED", reason="law 3 test")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE evaluator.holdout_verdicts SET passed = true",
        "DELETE FROM evaluator.holdout_verdicts",
        "TRUNCATE evaluator.holdout_verdicts",
    ],
)
async def test_vault_verdicts_are_append_only(db_session: AsyncSession, statement: str) -> None:
    _, config_hash = await _discovered(db_session)
    await record_holdout_verdict(db_session, config_hash, passed=False)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


@pytest.mark.skipif(
    not os.environ.get("RESEARCH_DATABASE_URL"), reason="requires RESEARCH_DATABASE_URL"
)
def test_research_role_cannot_see_vault_verdicts() -> None:
    engine = create_engine(
        os.environ["RESEARCH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )
    try:
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text("SELECT 1 FROM evaluator.holdout_verdicts LIMIT 1"))
    finally:
        engine.dispose()

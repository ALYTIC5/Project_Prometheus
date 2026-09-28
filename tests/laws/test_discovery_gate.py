"""Law 10: every discovery spends alpha-wealth. No path to VALIDATED
bypasses the online-FDR gate, and the ledger is append-only.

Needs TEST_DATABASE_URL (migrations through 0026) and, for the research-role
checks, RESEARCH_DATABASE_URL (migration 0024).
"""
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
_FAIL = ExcessReturnPValue(p_value=0.9, n_observations=250, sharpe_per_period=-0.1)


async def _strategy_with_spec(session: AsyncSession) -> tuple[str, str]:
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
    return strategy_id, config_hash


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE evaluator.alpha_wealth_ledger SET discovery = true",
        "DELETE FROM evaluator.alpha_wealth_ledger",
        "TRUNCATE evaluator.alpha_wealth_ledger",
    ],
)
async def test_ledger_is_append_only(db_session: AsyncSession, statement: str) -> None:
    _, config_hash = await _strategy_with_spec(db_session)
    await run_gate_test(db_session, config_hash, _FAIL)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_validated_requires_a_discovery(db_session: AsyncSession) -> None:
    strategy_id, config_hash = await _strategy_with_spec(db_session)
    assert not await set_status(db_session, strategy_id, "VALIDATED", reason="law 10 test")

    test = await run_gate_test(db_session, config_hash, _FAIL)
    assert not test.discovery
    assert not await set_status(db_session, strategy_id, "VALIDATED", reason="law 10 test")


async def test_a_discovery_opens_the_path_and_spends_wealth(db_session: AsyncSession) -> None:
    strategy_id, config_hash = await _strategy_with_spec(db_session)
    test = await run_gate_test(db_session, config_hash, _PASS)
    assert test.discovery
    assert test.alpha_threshold > 0
    # Law 3 (2026-09-28): a discovery still needs its one vault test.
    assert not await set_status(db_session, strategy_id, "VALIDATED", reason="law 10 test")
    await record_holdout_verdict(db_session, config_hash, strategy_id=strategy_id)
    assert await set_status(db_session, strategy_id, "VALIDATED", reason="law 10 test")


async def test_a_spec_is_tested_once_ever(db_session: AsyncSession) -> None:
    _, config_hash = await _strategy_with_spec(db_session)
    first = await run_gate_test(db_session, config_hash, _FAIL)
    second = await run_gate_test(db_session, config_hash, _PASS)
    assert not first.reused and second.reused
    assert second.test_index == first.test_index
    assert not second.discovery  # a better second p-value buys nothing


_needs_research_role = pytest.mark.skipif(
    not os.environ.get("RESEARCH_DATABASE_URL"), reason="requires RESEARCH_DATABASE_URL"
)


@_needs_research_role
@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1 FROM evaluator.alpha_wealth_ledger LIMIT 1",
        "INSERT INTO evaluator.alpha_wealth_ledger (test_index, config_hash, p_value, "
        "alpha_threshold, discovery, wealth_before, wealth_after, n_observations, "
        "excess_sharpe_per_period) VALUES (999999, 'x', 0, 1, true, 1, 1, 1, 1)",
    ],
)
def test_research_role_cannot_touch_the_ledger(statement: str) -> None:
    engine = create_engine(
        os.environ["RESEARCH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )
    try:
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text(statement))
    finally:
        engine.dispose()

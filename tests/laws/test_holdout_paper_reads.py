"""Law 3 x paper trading (user decision 2026-09-25, docs/DECISIONS.md).

holdout_start is forward-looking, so paper trading must read the vault to
see a current price. Every such read is logged (detail.kind = "PAPER") and
does NOT consume the strategy's one validation access -- but a real
validation access still burns it exactly as before.

Same infrastructure requirements as test_holdout_sacred.py.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prometheus.strategy.spec import StrategySpec
from prometheus.validation.holdout import (
    HoldoutAccessDenied,
    access_holdout,
    access_holdout_for_paper,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("HOLDOUT_DATABASE_URL"),
    reason=(
        "requires TEST_DATABASE_URL (migrations 0001-0010 applied) and "
        "HOLDOUT_DATABASE_URL (migration 0010's restricted role)"
    ),
)


@pytest.fixture()
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()

    import prometheus.core.db as db_module

    if db_module._holdout_engine is not None:
        await db_module._holdout_engine.dispose()
        db_module._holdout_engine = None
        db_module._holdout_session_factory = None


def _spec() -> StrategySpec:
    return StrategySpec(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}/USDT",
        timeframe="1d",
        fast_window=5,
        slow_window=20,
        expected_horizon=20,
    )


async def _paper_log_count(session: AsyncSession, fp: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM holdout_access_log WHERE strategy_fingerprint = :fp "
                    "AND granted = true AND detail->>'kind' = 'PAPER'"
                ),
                {"fp": fp},
            )
        ).scalar_one()
    )


async def test_every_paper_read_is_logged(session: AsyncSession) -> None:
    spec = _spec()
    await access_holdout_for_paper(session, spec, "TEST-STRATEGY")
    await access_holdout_for_paper(session, spec, "TEST-STRATEGY")
    await session.commit()
    assert await _paper_log_count(session, spec.config_hash()) == 2


async def test_paper_reads_do_not_consume_the_validation_access(session: AsyncSession) -> None:
    spec = _spec()
    await access_holdout_for_paper(session, spec, "TEST-STRATEGY")
    await session.commit()
    await access_holdout(session, spec, experiment_id=None)  # must not raise
    await session.commit()


async def test_validation_access_is_still_once_after_paper_reads(session: AsyncSession) -> None:
    spec = _spec()
    await access_holdout_for_paper(session, spec, "TEST-STRATEGY")
    await access_holdout(session, spec, experiment_id=None)
    await session.commit()
    with pytest.raises(HoldoutAccessDenied):
        await access_holdout(session, spec, experiment_id=None)
    await session.commit()

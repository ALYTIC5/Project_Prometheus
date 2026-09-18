"""tests/test_ablation_llm_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.ablation import register_llm_component
from prometheus.strategy.spec import StrategySpec

pytestmark = pytest.mark.db


async def _seed_llm_strategy(session: AsyncSession, *, strategy_id: str, symbol: str) -> None:
    spec = StrategySpec(
        family="MOMENTUM", symbol=symbol, timeframe="1d",
        fast_window=5, slow_window=20, expected_horizon=5,
        source="llm_hypothesis", description="seeded for ablation test",
    )
    # Spec JSON embedded literally in the query text, not bound as a
    # parameter -- matches this codebase's own established pattern for
    # seeding strategies.spec (a JSONB column) in tests
    # (tests/test_paper_divergence.py's _seed_strategy), avoiding a
    # driver-level jsonb-cast-from-bound-string question entirely. Safe
    # here: spec.model_dump_json()'s content is fully controlled test
    # fixture data, not external input.
    await session.execute(
        text(
            f"INSERT INTO strategies (id, family, spec, status) "
            f"VALUES (:id, :family, '{spec.model_dump_json()}', 'pending')"
        ),
        {"id": strategy_id, "family": spec.family},
    )
    await session.commit()


async def test_register_llm_component_produces_a_real_verdict(
    db_session: AsyncSession,
) -> None:
    await _seed_llm_strategy(db_session, strategy_id="MOMENTUM-900", symbol="BTC/USDT")
    result = await register_llm_component(
        db_session,
        symbols=["BTC/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.component == "llm_generation"
    assert result.verdict in {"UNPROVEN", "VALUABLE", "NEUTRAL", "HARMFUL"}


async def test_register_llm_component_with_no_llm_strategies_is_unproven(
    db_session: AsyncSession,
) -> None:
    result = await register_llm_component(
        db_session,
        symbols=["ETH/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.verdict == "UNPROVEN"
    assert result.n_experiments == 0

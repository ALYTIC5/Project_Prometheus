"""tests/test_ablation_llm_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # Spec bound as a real JSONB parameter, not embedded literally in the
    # query text -- text() scans the WHOLE string for `:identifier`
    # bind-marker syntax regardless of quoting, so a real spec's JSON
    # (full of "field":value colons) gets misparsed as bind params
    # ("fast_window":5 looks like a `:5` placeholder). The `'{}'` literal
    # in tests/test_paper_divergence.py's _seed_strategy has no colons,
    # which is why that precedent looked safe but doesn't generalize.
    # Same bindparam(type_=JSONB) pattern this file's own
    # register_llm_component/ablation.py module already uses elsewhere
    # (e.g. _UPSERT_REGISTRY's families_affected column).
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, :family, :spec, 'pending')"
        ).bindparams(bindparam("spec", type_=JSONB)),
        {"id": strategy_id, "family": spec.family, "spec": spec.model_dump()},
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

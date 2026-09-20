"""tests/test_ablation_ml_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.ablation import register_ml_component

pytestmark = pytest.mark.db


async def test_register_ml_component_produces_a_real_verdict(db_session: AsyncSession) -> None:
    result = await register_ml_component(
        db_session,
        symbols=["BTC/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.component == "random_forest"
    assert result.verdict in {"UNPROVEN", "VALUABLE", "NEUTRAL", "HARMFUL"}


async def test_register_ml_component_with_no_bars_is_unproven(db_session: AsyncSession) -> None:
    result = await register_ml_component(
        db_session,
        symbols=["NOSUCH/PAIR"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.verdict == "UNPROVEN"
    assert result.n_experiments == 0

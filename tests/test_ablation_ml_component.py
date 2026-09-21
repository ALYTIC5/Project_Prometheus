"""tests/test_ablation_ml_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.ablation import (
    register_gradient_boosting_component,
    register_logistic_regression_component,
    register_ml_component,
    register_svm_component,
)

pytestmark = pytest.mark.db

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 6, 1, tzinfo=UTC)

_REGISTER_FNS = {
    "random_forest": register_ml_component,
    "gradient_boosting": register_gradient_boosting_component,
    "logistic_regression": register_logistic_regression_component,
    "svm": register_svm_component,
}


@pytest.mark.parametrize("component,register_fn", list(_REGISTER_FNS.items()))
async def test_register_component_produces_a_real_verdict(
    db_session: AsyncSession, component, register_fn
) -> None:
    result = await register_fn(
        db_session, symbols=["BTC/USDT"], timeframe="1d", start=_START, end=_END, version="v1",
    )
    assert result.component == component
    assert result.verdict in {"UNPROVEN", "VALUABLE", "NEUTRAL", "HARMFUL"}


@pytest.mark.parametrize("component,register_fn", list(_REGISTER_FNS.items()))
async def test_register_component_with_no_bars_is_unproven(
    db_session: AsyncSession, component, register_fn
) -> None:
    result = await register_fn(
        db_session, symbols=["NOSUCH/PAIR"], timeframe="1d", start=_START, end=_END, version="v1",
    )
    assert result.verdict == "UNPROVEN"
    assert result.n_experiments == 0

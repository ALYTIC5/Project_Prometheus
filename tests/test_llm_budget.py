"""tests/test_llm_budget.py"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import LLMUsage
from prometheus.research.llm import budget as budget_module
from prometheus.research.llm.budget import (
    BudgetSettings,
    current_tier,
    estimate_cost,
    model_for_tier,
)

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _budget_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """M5 (final-review fix wave): monkeypatch.setenv, not a bare
    os.environ assignment -- the old version left LLM_MONTHLY_BUDGET_USD
    set for every test that ran after this file, in any module. And
    budget._budget_settings is a module-global singleton built once on
    first use, so without resetting it each test silently reused
    whichever BudgetSettings the FIRST test in the session happened to
    construct, making the env var above decorative after test #1."""
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "100.0")
    monkeypatch.setattr(budget_module, "_budget_settings", None)


async def _log_usage(session: AsyncSession, cost: float) -> None:
    session.add(
        LLMUsage(
            model="claude-sonnet-5",
            input_tokens=1000,
            output_tokens=500,
            est_cost_usd=cost,
            purpose="hypothesis_generation",
        )
    )
    await session.flush()


async def test_current_tier_is_full_under_80_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 79.0)
    assert await current_tier(db_session) == "full"


async def test_current_tier_is_cheap_between_80_and_100_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 85.0)
    assert await current_tier(db_session) == "cheap"


async def test_current_tier_is_halted_at_or_over_100_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 100.0)
    assert await current_tier(db_session) == "halted"


def test_model_for_tier_maps_full_to_sonnet_and_cheap_to_haiku() -> None:
    assert model_for_tier("full") == "claude-sonnet-5"
    assert model_for_tier("cheap") == "claude-haiku-4-5"
    with pytest.raises(ValueError):
        model_for_tier("halted")  # type: ignore[arg-type]


def test_estimate_cost_uses_cited_per_model_rates() -> None:
    # Sonnet: $2/1M input, $10/1M output (see this plan's Global Constraints)
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(2.0 + 10.0)


def test_estimate_cost_raises_value_error_on_unknown_model() -> None:
    """M4 (final-review fix wave): an unpriced model must surface as
    ValueError, matching model_for_tier's own error contract, not leak a
    raw KeyError from the private pricing dict."""
    with pytest.raises(ValueError, match="no pricing data for model"):
        estimate_cost("claude-not-a-real-model", input_tokens=10, output_tokens=10)


def test_budget_env_fixture_uses_a_fresh_settings_singleton() -> None:
    """M5: the autouse fixture must actually reset budget._budget_settings,
    so each test constructs BudgetSettings from the env it just set rather
    than reusing the first test's instance."""
    assert budget_module._budget_settings is None
    assert budget_module.get_budget_settings().LLM_MONTHLY_BUDGET_USD == 100.0


def test_budget_settings_raises_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MONTHLY_BUDGET_USD", raising=False)
    with pytest.raises(ValidationError):
        BudgetSettings()

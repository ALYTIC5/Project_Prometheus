"""prometheus/research/llm/budget.py -- PROMPT 9's monthly LLM spend cap.

Not instantiated at import time (same lazy pattern as
experiments.queue.get_queue_settings/QueueSettings): most processes never
touch the LLM path, so requiring LLM_MONTHLY_BUDGET_USD to be set for
every import of prometheus.research.llm would break every environment
that hasn't opted into this feature yet.

Tier boundaries (80%/100%) are PROMPTS.md's own literal words ("At 80%
switch to a cheaper model; at 100% LLM generation halts"), not invented
here. Per-model pricing is Anthropic's own published rate card (cited in
this plan's Global Constraints) -- re-verify against Anthropic's live
pricing page if this ever needs updating; token prices are not a fixed
constant like z=1.96, they change with the market.
"""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Tier = Literal["full", "cheap", "halted"]

_MODEL_FOR_TIER: dict[str, str] = {
    "full": "claude-sonnet-5",
    "cheap": "claude-haiku-4-5",
}

# (usd_per_1k_input, usd_per_1k_output) -- Anthropic's published per-model
# rate card, 2026-09-18. See this plan's Global Constraints for the
# per-million-token figures this is derived from.
_PRICING_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (0.002, 0.010),
    "claude-haiku-4-5": (0.001, 0.005),
}

_FULL_TIER_CEILING = 0.8
_CHEAP_TIER_CEILING = 1.0

_SELECT_MONTH_TO_DATE_SPEND = text(
    """
    SELECT COALESCE(SUM(est_cost_usd), 0) AS total
      FROM llm_usage
     WHERE created_at >= date_trunc('month', now())
    """
)


class BudgetSettings(BaseSettings):
    """Env-only, frozen -- same fail-fast-on-missing posture as
    core.config.RiskLimits (a silently-defaulted budget is worse than a
    crash for a cost-control feature)."""

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    LLM_MONTHLY_BUDGET_USD: float


_budget_settings: BudgetSettings | None = None


def get_budget_settings() -> BudgetSettings:
    """Lazy, like experiments.queue.get_queue_settings -- LLM env is only
    required once a caller actually checks/spends budget, not at
    import time."""
    global _budget_settings
    if _budget_settings is None:
        _budget_settings = BudgetSettings()
    return _budget_settings


async def current_tier(session: AsyncSession) -> Tier:
    settings = get_budget_settings()
    spend = float((await session.execute(_SELECT_MONTH_TO_DATE_SPEND)).scalar_one())
    fraction = spend / settings.LLM_MONTHLY_BUDGET_USD
    if fraction >= _CHEAP_TIER_CEILING:
        return "halted"
    if fraction >= _FULL_TIER_CEILING:
        return "cheap"
    return "full"


def model_for_tier(tier: Tier) -> str:
    try:
        return _MODEL_FOR_TIER[tier]
    except KeyError:
        raise ValueError(f"no model for tier {tier!r} (LLM generation is halted)") from None


def estimate_cost(model: str, *, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = _PRICING_PER_1K_TOKENS[model]
    return (input_tokens / 1000) * input_rate + (output_tokens / 1000) * output_rate

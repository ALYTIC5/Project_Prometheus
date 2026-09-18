"""prometheus/research/llm/hypothesis.py -- PROMPT 9's LLM hypothesis
generator. NO function here takes a database session -- Law 3 requires
this module to be structurally incapable of opening
validation.holdout.access_holdout() or evaluating its own output
(tests/test_llm_hypothesis_holdout_safety.py enforces both properties by
static inspection, not by trusting a mock to catch every path).

Reuses the 3 EXISTING StrategySpec families (MOMENTUM/BOLLINGER/
VOL_BREAKOUT) -- no new DSL. A malformed LLM response fails
StrategySpec's own model_validator and raises; it is never silently
coerced into an invalid spec.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from prometheus.research.llm.budget import estimate_cost
from prometheus.strategy.spec import FAMILIES, StrategySpec

_SYSTEM_PROMPT = f"""You are a quantitative strategy research assistant.
Given research paper excerpts, propose ONE new trading strategy hypothesis
using EXACTLY one of these families: {", ".join(FAMILIES)}.

Respond with ONLY a JSON object with these exact keys:
- "family": one of {list(FAMILIES)}
- family-specific parameter fields (MOMENTUM: fast_window, slow_window;
  BOLLINGER: lookback_window, band_multiplier; VOL_BREAKOUT: breakout_window,
  exit_window)
- "expected_horizon": integer, bars ahead this signal is claimed to matter
- "hypothesis_text": a one-paragraph explanation grounded in the provided papers
- "expected_effect": what measurable effect you expect (e.g. "higher Sharpe",
  "lower drawdown") and why

No other text, no markdown fences, just the JSON object."""


@dataclass(frozen=True)
class PaperContext:
    paper_id: int
    key_sections: str


@dataclass(frozen=True)
class LLMHypothesis:
    spec: StrategySpec
    hypothesis_text: str
    expected_effect: str
    paper_ids: list[int]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class _AnthropicClientProtocol(Protocol):
    """Structural type for the Anthropic client -- lets tests pass a
    MagicMock without importing the real anthropic package's own types,
    and keeps this module's public signature honest about what it
    actually needs (a `.messages.create(...)` call), not the whole SDK."""

    messages: Any


def _build_user_prompt(symbol: str, timeframe: str, paper_context: list[PaperContext]) -> str:
    excerpts = "\n\n".join(
        f"[Paper {p.paper_id}]\n{p.key_sections}" for p in paper_context
    )
    return (
        f"Symbol: {symbol}\nTimeframe: {timeframe}\n\n"
        f"Research excerpts:\n{excerpts}"
    )


async def generate_hypothesis(
    client: _AnthropicClientProtocol,
    model: str,
    symbol: str,
    timeframe: str,
    paper_context: list[PaperContext],
) -> LLMHypothesis:
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": _build_user_prompt(symbol, timeframe, paper_context),
            }
        ],
    )
    raw_text = message.content[0].text
    parsed = json.loads(raw_text)

    family = parsed["family"]
    param_fields = {
        "MOMENTUM": ("fast_window", "slow_window"),
        "BOLLINGER": ("lookback_window", "band_multiplier"),
        "VOL_BREAKOUT": ("breakout_window", "exit_window"),
    }[family]
    params = {field: parsed[field] for field in param_fields}

    # StrategySpec's own model_validator raises ValueError on an invalid
    # combination (e.g. slow_window <= fast_window) -- deliberately not
    # caught here, so a malformed LLM response surfaces as a real error
    # to the caller rather than being silently dropped or coerced.
    spec = StrategySpec(
        family=family,
        symbol=symbol,
        timeframe=timeframe,
        expected_horizon=parsed["expected_horizon"],
        source="llm_hypothesis",
        description=parsed["hypothesis_text"],
        **params,
    )

    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    return LLMHypothesis(
        spec=spec,
        hypothesis_text=parsed["hypothesis_text"],
        expected_effect=parsed["expected_effect"],
        paper_ids=[p.paper_id for p in paper_context],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(model, input_tokens=input_tokens, output_tokens=output_tokens),
    )

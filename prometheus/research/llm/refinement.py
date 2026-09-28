"""prometheus/research/llm/refinement.py -- failure-driven refinement.

The loop's missing step: read WHY a strategy failed and propose a better
version. One failed-but-scored strategy's validation evidence (verdict,
reason codes, ICIR, IC by horizon, excess return/Sharpe vs buy-and-hold,
PBO, deflated Sharpe) goes to the model, which returns a revised parameter
point of the SAME family -- a refinement keeps the parent's mechanism, so
what it tests is "these parameters, better", not a different idea.

Like hypothesis.py this module takes no database session and imports
nothing that can reach the holdout (tests/test_llm_refinement.py checks
both statically). The evidence it reads comes from the canary-free
breedable_evidence view (migration 0028), never from validation tables.

Whether this beats random mutation is an open question answered by the
`llm_refinement` ablation (experiments/ablation.py), not assumed here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from prometheus.research.llm.budget import estimate_cost
from prometheus.research.llm.hypothesis import (
    LLMHypothesis,
    LLMResponseError,
    _AnthropicClientProtocol,
    parse_prior,
    response_text,
)
from prometheus.strategy.spec import StrategySpec

REFINEMENT_SOURCE = "llm_refinement"
_MAX_TOKENS = 1024

_SYSTEM_PROMPT = """You are a quantitative strategy research assistant.
You are given ONE trading strategy that failed validation, with the exact
evidence of why. Propose ONE revised parameter set for the SAME strategy
family that addresses the failure. Keep the family's mechanism; change only
its parameters.

How to read the evidence:
- Every strategy is judged against buy-and-hold of the same asset after
  costs. excess_return / excess_sharpe <= 0 means it lost to simply holding.
- icir = mean / std of the signal's information coefficient across
  walk-forward folds: how CONSISTENTLY the signal predicts returns. Higher
  and steadier beats a large but erratic IC.
- ic_by_horizon: IC at 1..100 bars ahead. A signal whose IC collapses after
  a few bars is noise that fees will eat; prefer parameters whose power
  lasts at the horizon the strategy trades.
- pbo = probability of backtest overfitting (above 0.5: more likely
  overfit than not). deflated_sharpe = probability the Sharpe is real after
  the number of trials.
- reason_codes: the validator's own verdict reasons.

Respond with ONLY a JSON object with these exact keys:
- every parameter field listed for the strategy (same names, new values)
- "expected_horizon": integer, bars ahead the revised signal should matter
- "hypothesis_text": one paragraph: which failure you address and how
- "expected_effect": the measurable change you expect and why
- "prior_probability": a number strictly between 0 and 1 -- your probability
  that the REVISED strategy beats buy-and-hold after costs, out of sample,
  strongly enough to pass a strict multiple-testing gate. Most refinements
  of a failed strategy still fail; be calibrated, not hopeful.

No other text, no markdown fences, just the JSON object."""


@dataclass(frozen=True)
class FailureEvidence:
    """One row of breedable_evidence, as the refinement prompt sees it."""

    verdict: str
    reason_codes: list[str]
    icir: float | None
    ic_by_horizon: dict[str, float | None] | None
    excess_return: float | None
    excess_sharpe: float | None
    pbo: float | None
    deflated_sharpe: float | None


def build_user_prompt(parent: StrategySpec, evidence: FailureEvidence) -> str:
    return (
        f"Family: {parent.family}\n"
        f"Symbol: {parent.symbol}  Timeframe: {parent.timeframe}\n"
        f"Current parameters: {json.dumps(parent.parameters, sort_keys=True)}\n"
        f"Parameter fields to return: {sorted(parent.parameters)}\n"
        f"Claimed horizon: {parent.expected_horizon}\n\n"
        "Validation evidence:\n"
        + json.dumps(
            {
                "verdict": evidence.verdict,
                "reason_codes": evidence.reason_codes,
                "icir": evidence.icir,
                "ic_by_horizon": evidence.ic_by_horizon,
                "excess_return": evidence.excess_return,
                "excess_sharpe": evidence.excess_sharpe,
                "pbo": evidence.pbo,
                "deflated_sharpe": evidence.deflated_sharpe,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _parse_refinement(parsed: dict[str, Any], parent: StrategySpec) -> tuple[StrategySpec, float]:
    params = {field: parsed[field] for field in parent.parameters}
    child = parent.with_updates(
        **params,
        expected_horizon=parsed["expected_horizon"],
        parent_id=parent.config_hash(),
        source=REFINEMENT_SOURCE,
        description=str(parsed["hypothesis_text"]),
    )
    if child.config_hash() == parent.config_hash():
        raise ValueError("refinement returned the parent's own parameters")
    return child, parse_prior(parsed["prior_probability"])


async def generate_refinement(
    client: _AnthropicClientProtocol,
    model: str,
    parent: StrategySpec,
    evidence: FailureEvidence,
) -> LLMHypothesis:
    """Same billing contract as generate_hypothesis: every failure after the
    call returns is an LLMResponseError carrying the billed usage."""
    message = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        thinking={"type": "disabled"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(parent, evidence)}],
    )
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    try:
        parsed = json.loads(response_text(message))
        child, prior = _parse_refinement(parsed, parent)
        hypothesis_text = str(parsed["hypothesis_text"])
        expected_effect = str(parsed["expected_effect"])
    except Exception as exc:
        raise LLMResponseError(
            f"LLM refinement could not be parsed into a valid spec: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        ) from exc

    return LLMHypothesis(
        spec=child,
        hypothesis_text=hypothesis_text,
        expected_effect=expected_effect,
        prior_probability=prior,
        paper_ids=[],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(model, input_tokens=input_tokens, output_tokens=output_tokens),
    )

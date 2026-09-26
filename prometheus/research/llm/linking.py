"""prometheus/research/llm/linking.py -- typed relations between a new
claim and existing claims from other papers.

The caller picks candidates (claims sharing a concept); this module only
asks the model which of them the new claim SUPPORTS, CONTRADICTS, EXTENDS
or shares a mechanism with. Unrelated candidates are simply not returned.
No DB access here, same isolation rule as hypothesis.py and extraction.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from prometheus.research.llm.budget import estimate_cost
from prometheus.research.llm.extraction import EXTRACTION_MODEL
from prometheus.research.llm.hypothesis import (
    LLMResponseError,
    _AnthropicClientProtocol,
    response_text,
)

LINKING_MODEL = EXTRACTION_MODEL
RELATIONS = ("SUPPORTS", "CONTRADICTS", "EXTENDS", "SAME_MECHANISM")

_SYSTEM_PROMPT = f"""You compare research claims from different
quantitative-finance papers. You get one NEW claim and a numbered list of
EXISTING claims. For each existing claim that is genuinely related to the
new one, give the relation of the NEW claim to it:
- SUPPORTS: the new claim is evidence for the existing claim
- CONTRADICTS: the new claim is evidence against the existing claim
- EXTENDS: the new claim generalises or refines the existing claim
- SAME_MECHANISM: both rely on the same underlying mechanism, but neither
  supports nor contradicts the other's result

Leave out unrelated claims. Respond with ONLY a JSON object:
{{"links": [{{"id": <existing claim number>, "relation": one of
{list(RELATIONS)}, "rationale": one sentence}}]}}
No other text, no markdown fences."""


@dataclass(frozen=True)
class ClaimRef:
    claim_id: int
    mechanism: str
    asset_class: str
    horizon: str


@dataclass(frozen=True)
class ClaimLink:
    claim_a: int
    claim_b: int
    relation: str
    rationale: str


@dataclass(frozen=True)
class Linking:
    links: list[ClaimLink]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


def _describe(ref: ClaimRef) -> str:
    return f"{ref.mechanism} (asset class: {ref.asset_class}; horizon: {ref.horizon})"


async def link_claims(
    client: _AnthropicClientProtocol, *, new: ClaimRef, candidates: list[ClaimRef]
) -> Linking:
    listing = "\n".join(f"{c.claim_id}. {_describe(c)}" for c in candidates)
    message = client.messages.create(
        model=LINKING_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"NEW claim: {_describe(new)}\n\nEXISTING claims:\n{listing}",
            }
        ],
    )
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    valid_ids = {c.claim_id for c in candidates}
    try:
        raw_links = json.loads(response_text(message))["links"]
        if not isinstance(raw_links, list):
            raise ValueError("links is not a list")
        links: dict[int, ClaimLink] = {}
        for raw in raw_links:
            target = int(raw["id"])
            relation = raw["relation"]
            if target not in valid_ids:
                raise ValueError(f"id {target} was not one of the candidates")
            if relation not in RELATIONS:
                raise ValueError(f"relation {relation!r} not in {RELATIONS}")
            links[target] = ClaimLink(
                claim_a=new.claim_id,
                claim_b=target,
                relation=relation,
                rationale=str(raw["rationale"]).strip(),
            )
    except Exception as exc:
        raise LLMResponseError(
            f"claim linking could not be parsed: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=LINKING_MODEL,
        ) from exc
    return Linking(
        links=list(links.values()),
        model=LINKING_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(
            LINKING_MODEL, input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )

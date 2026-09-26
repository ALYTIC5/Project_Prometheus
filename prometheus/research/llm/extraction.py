"""prometheus/research/llm/extraction.py -- what a paper claims, as
structured, falsifiable statements.

One call per paper on the paper's own title and abstract. No DB access and
no strategy state: the extractor sees nothing but the paper text, the same
isolation rule hypothesis.py follows. family_hint is validated against the
registered families so a claim can only point at something the engine can
actually test.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from prometheus.research.llm.budget import estimate_cost
from prometheus.research.llm.hypothesis import (
    LLMResponseError,
    _AnthropicClientProtocol,
    response_text,
)
from prometheus.strategy.spec import FAMILIES

EXTRACTION_MODEL = "claude-haiku-4-5"
MAX_CLAIMS_PER_PAPER = 5
MAX_CONCEPTS_PER_CLAIM = 8

ASSET_CLASSES = ("equity", "crypto", "fx", "commodity", "fixed_income", "multi_asset", "other")
HORIZONS = ("intraday", "daily", "weekly", "monthly", "quarterly_plus", "unspecified")
DIRECTIONS = ("long", "short", "long_short", "market_neutral", "none")

_SYSTEM_PROMPT = f"""You read quantitative-finance paper abstracts and extract
the paper's empirical or theoretical CLAIMS about asset returns, risk or
trading. A claim is one falsifiable statement: a mechanism and what it is
said to predict.

Respond with ONLY a JSON object: {{"claims": [ ... ]}} with at most
{MAX_CLAIMS_PER_PAPER} claims. Return {{"claims": []}} if the paper makes no
claim about returns, risk or trading. Each claim is an object with keys:
- "mechanism": one sentence, WHY the effect should exist
- "asset_class": one of {list(ASSET_CLASSES)}
- "horizon": one of {list(HORIZONS)}
- "direction": one of {list(DIRECTIONS)}
- "stated_effect": the effect the paper reports, quoting its numbers if any
- "data_period": the sample period the paper used, or "unspecified"
- "testable": true only if the claim can be tested with daily OHLCV price
  and volume data alone
- "family_hint": the closest of {list(FAMILIES)} if testable, else null
- "concepts": up to {MAX_CONCEPTS_PER_CLAIM} short lowercase topic tags
  (e.g. "momentum", "volatility-clustering", "post-earnings-drift")

No other text, no markdown fences."""

_CONCEPT_JUNK = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ExtractedClaim:
    mechanism: str
    asset_class: str
    horizon: str
    direction: str
    stated_effect: str
    data_period: str
    testable: bool
    family_hint: str | None
    concepts: tuple[str, ...]


@dataclass(frozen=True)
class Extraction:
    claims: list[ExtractedClaim]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


def normalize_concept(raw: str) -> str:
    return _CONCEPT_JUNK.sub("-", raw.strip().lower()).strip("-")[:64]


def _one_of(value: Any, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field}={value!r} not in {allowed}")
    return str(value)


def _parse_claim(raw: dict[str, Any]) -> ExtractedClaim:
    family_hint = raw.get("family_hint")
    if family_hint is not None and family_hint not in FAMILIES:
        raise ValueError(f"family_hint={family_hint!r} is not a registered family")
    testable = raw["testable"]
    if not isinstance(testable, bool):
        raise ValueError(f"testable={testable!r} is not a boolean")
    concepts = tuple(
        dict.fromkeys(
            c for c in (normalize_concept(str(x)) for x in raw["concepts"]) if c
        )
    )[:MAX_CONCEPTS_PER_CLAIM]
    return ExtractedClaim(
        mechanism=str(raw["mechanism"]).strip(),
        asset_class=_one_of(raw["asset_class"], ASSET_CLASSES, "asset_class"),
        horizon=_one_of(raw["horizon"], HORIZONS, "horizon"),
        direction=_one_of(raw["direction"], DIRECTIONS, "direction"),
        stated_effect=str(raw["stated_effect"]).strip(),
        data_period=str(raw["data_period"]).strip(),
        testable=testable,
        family_hint=family_hint if testable else None,
        concepts=concepts,
    )


async def extract_claims(
    client: _AnthropicClientProtocol, *, title: str, abstract: str
) -> Extraction:
    message = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Title: {title}\n\nAbstract:\n{abstract}"}],
    )
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    try:
        parsed = json.loads(response_text(message))
        raw_claims = parsed["claims"]
        if not isinstance(raw_claims, list):
            raise ValueError("claims is not a list")
        claims = [_parse_claim(raw) for raw in raw_claims[:MAX_CLAIMS_PER_PAPER]]
    except Exception as exc:
        raise LLMResponseError(
            f"claim extraction could not be parsed: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=EXTRACTION_MODEL,
        ) from exc
    return Extraction(
        claims=claims,
        model=EXTRACTION_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(
            EXTRACTION_MODEL, input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )

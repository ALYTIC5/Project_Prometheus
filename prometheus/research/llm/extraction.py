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
each paper's empirical or theoretical CLAIMS about asset returns, risk or
trading. A claim is one falsifiable statement: a mechanism and what it is
said to predict.

You get one or more numbered papers. Respond with ONLY a JSON object:
{{"papers": [{{"paper": <number>, "claims": [ ... ]}}, ...]}} with exactly one
entry per paper and at most {MAX_CLAIMS_PER_PAPER} claims per paper. A paper
that makes no claim about returns, risk or trading gets "claims": [].
Each claim is an object with keys:
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


# Papers per extraction call: the instructions are sent once per 8 papers.
# Measured 2026-09-26 on 8 real papers: ~7% cheaper per paper, with no loss
# of testable claims versus single calls -- output tokens (5x the input
# price) dominate, and they only come from papers that do make claims.
# Small enough that the worst case (8 x 5 claims) fits in max_tokens.
EXTRACTION_BATCH_SIZE = 8
_MAX_TOKENS = 8192


@dataclass(frozen=True)
class BatchExtraction:
    """claims_by_paper[i] is the claims for the i-th paper passed in, or
    None when that paper's part of the response was missing or invalid --
    one bad entry never discards the other papers' results."""

    claims_by_paper: list[list[ExtractedClaim] | None]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


async def extract_claims_batch(
    client: _AnthropicClientProtocol, papers: list[tuple[str, str]]
) -> BatchExtraction:
    """One call for up to EXTRACTION_BATCH_SIZE (title, abstract) pairs.
    Raises LLMResponseError (carrying the billed usage) only when the
    response as a whole is unusable."""
    listing = "\n\n".join(
        f"[{i}] Title: {title}\nAbstract: {abstract}"
        for i, (title, abstract) in enumerate(papers, start=1)
    )
    message = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": listing}],
    )
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    try:
        entries = json.loads(response_text(message))["papers"]
        if not isinstance(entries, list):
            raise ValueError("papers is not a list")
    except Exception as exc:
        raise LLMResponseError(
            f"claim extraction could not be parsed: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=EXTRACTION_MODEL,
        ) from exc
    claims_by_paper: list[list[ExtractedClaim] | None] = [None] * len(papers)
    for entry in entries:
        try:
            index = int(entry["paper"]) - 1
            raw_claims = entry["claims"]
            if not 0 <= index < len(papers) or not isinstance(raw_claims, list):
                continue
            claims_by_paper[index] = [
                _parse_claim(raw) for raw in raw_claims[:MAX_CLAIMS_PER_PAPER]
            ]
        except (KeyError, TypeError, ValueError):
            continue
    return BatchExtraction(
        claims_by_paper=claims_by_paper,
        model=EXTRACTION_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(
            EXTRACTION_MODEL, input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


async def extract_claims(
    client: _AnthropicClientProtocol, *, title: str, abstract: str
) -> Extraction:
    """Single-paper form of extract_claims_batch."""
    batch = await extract_claims_batch(client, [(title, abstract)])
    claims = batch.claims_by_paper[0]
    if claims is None:
        raise LLMResponseError(
            "claim extraction could not be parsed: no valid entry for the paper",
            input_tokens=batch.input_tokens,
            output_tokens=batch.output_tokens,
            model=batch.model,
        )
    return Extraction(
        claims=claims,
        model=batch.model,
        input_tokens=batch.input_tokens,
        output_tokens=batch.output_tokens,
        est_cost_usd=batch.est_cost_usd,
    )

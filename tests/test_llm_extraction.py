"""tests/test_llm_extraction.py -- claim extraction and claim linking
parse only well-formed responses and always carry billed usage."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from prometheus.research.llm.extraction import (
    EXTRACTION_MODEL,
    extract_claims,
    extract_claims_batch,
    normalize_concept,
)
from prometheus.research.llm.hypothesis import LLMResponseError
from prometheus.research.llm.linking import ClaimRef, link_claims


def _client(payload: Any, *, stop_reason: str = "end_turn") -> MagicMock:
    """A single-paper {"claims": [...]} payload is sent in the batched
    response shape the extractor asks for."""
    client = MagicMock()
    message = MagicMock()
    if isinstance(payload, dict) and "claims" in payload:
        payload = {"papers": [{"paper": 1, "claims": payload["claims"]}]}
    body = payload if isinstance(payload, str) else json.dumps(payload)
    message.content = [MagicMock(type="text", text=body)]
    message.stop_reason = stop_reason
    message.usage.input_tokens = 400
    message.usage.output_tokens = 300
    client.messages.create.return_value = message
    return client


def _claim(**overrides: Any) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "mechanism": "Investors underreact to news, so past winners keep winning.",
        "asset_class": "equity",
        "horizon": "monthly",
        "direction": "long_short",
        "stated_effect": "1% per month spread",
        "data_period": "1965-1989",
        "testable": True,
        "family_hint": "TSMOM",
        "concepts": ["Momentum", "Under-reaction ", "momentum"],
    }
    claim.update(overrides)
    return claim


async def test_extract_claims_parses_and_normalizes() -> None:
    client = _client({"claims": [_claim()]})
    extraction = await extract_claims(client, title="t", abstract="a")

    assert len(extraction.claims) == 1
    claim = extraction.claims[0]
    assert claim.family_hint == "TSMOM"
    assert claim.concepts == ("momentum", "under-reaction")
    assert extraction.model == EXTRACTION_MODEL
    assert extraction.input_tokens == 400
    assert extraction.est_cost_usd > 0


@pytest.mark.parametrize(
    "wrap",
    ["```json\n{body}\n```", "```\n{body}\n```", "  ```json\n{body}```  ", "{body}"],
)
async def test_extract_claims_accepts_a_code_fenced_response(wrap: str) -> None:
    """claude-haiku-4-5 fences its JSON in production (2026-09-26)."""
    body = json.dumps({"papers": [{"paper": 1, "claims": [_claim()]}]})
    extraction = await extract_claims(_client(wrap.format(body=body)), title="t", abstract="a")
    assert len(extraction.claims) == 1


async def test_extract_claims_drops_family_hint_on_untestable_claims() -> None:
    client = _client({"claims": [_claim(testable=False)]})
    extraction = await extract_claims(client, title="t", abstract="a")
    assert extraction.claims[0].family_hint is None


async def test_extract_claims_allows_papers_with_no_claims() -> None:
    extraction = await extract_claims(_client({"claims": []}), title="t", abstract="a")
    assert extraction.claims == []


@pytest.mark.parametrize(
    "bad",
    [
        _claim(asset_class="stocks"),
        _claim(family_hint="NOT_A_FAMILY"),
        _claim(testable="yes"),
    ],
)
async def test_extract_claims_rejects_invalid_fields_with_usage(bad: dict[str, Any]) -> None:
    with pytest.raises(LLMResponseError) as excinfo:
        await extract_claims(_client({"claims": [bad]}), title="t", abstract="a")
    assert excinfo.value.output_tokens == 300


async def test_extract_claims_rejects_truncated_response() -> None:
    with pytest.raises(LLMResponseError):
        await extract_claims(
            _client({"claims": []}, stop_reason="max_tokens"), title="t", abstract="a"
        )


async def test_batch_sends_all_papers_in_one_call_and_isolates_a_bad_entry() -> None:
    client = _client(
        {
            "papers": [
                {"paper": 1, "claims": [_claim()]},
                {"paper": 2, "claims": [_claim(asset_class="stocks")]},
                {"paper": 3, "claims": []},
            ]
        }
    )
    batch = await extract_claims_batch(client, [("a", "x"), ("b", "y"), ("c", "z"), ("d", "w")])

    assert client.messages.create.call_count == 1
    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "[1] Title: a" in content and "[4] Title: d" in content
    first, bad, empty, missing = batch.claims_by_paper
    assert first is not None and len(first) == 1
    assert bad is None  # invalid enum drops only this paper
    assert empty == []
    assert missing is None  # no entry returned for paper 4
    assert batch.input_tokens == 400


def test_normalize_concept() -> None:
    assert normalize_concept("  Post-Earnings  Drift!") == "post-earnings-drift"


_NEW = ClaimRef(10, "new mechanism", "equity", "monthly")
_CANDIDATES = [ClaimRef(3, "old a", "equity", "monthly"), ClaimRef(4, "old b", "fx", "daily")]


async def test_link_claims_returns_typed_links_from_new_to_existing() -> None:
    client = _client(
        {"links": [{"id": 3, "relation": "CONTRADICTS", "rationale": "opposite sign"}]}
    )
    linking = await link_claims(client, new=_NEW, candidates=_CANDIDATES)

    assert [(k.claim_a, k.claim_b, k.relation) for k in linking.links] == [
        (10, 3, "CONTRADICTS")
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"links": [{"id": 99, "relation": "SUPPORTS", "rationale": "r"}]},
        {"links": [{"id": 3, "relation": "INSPIRES", "rationale": "r"}]},
        "not json",
    ],
)
async def test_link_claims_rejects_invalid_links_with_usage(bad: Any) -> None:
    with pytest.raises(LLMResponseError) as excinfo:
        await link_claims(_client(bad), new=_NEW, candidates=_CANDIDATES)
    assert excinfo.value.input_tokens == 400

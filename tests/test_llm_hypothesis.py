"""tests/test_llm_hypothesis.py"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from prometheus.research.llm.hypothesis import PaperContext, generate_hypothesis

_VALID_RESPONSE_JSON = json.dumps(
    {
        "family": "MOMENTUM",
        "fast_window": 10,
        "slow_window": 50,
        "expected_horizon": 5,
        "hypothesis_text": "Faster momentum crossovers may capture short-term trend continuation.",
        "expected_effect": "Higher turnover, similar or better risk-adjusted return.",
    }
)

_MALFORMED_RESPONSE_JSON = json.dumps(
    {
        "family": "MOMENTUM",
        "fast_window": 50,
        "slow_window": 10,  # invalid: slow_window must exceed fast_window
        "expected_horizon": 5,
        "hypothesis_text": "bad",
        "expected_effect": "bad",
    }
)

_UNKNOWN_FAMILY_RESPONSE_JSON = json.dumps(
    {
        "family": "CARRY",  # not one of MOMENTUM/BOLLINGER/VOL_BREAKOUT
        "expected_horizon": 5,
        "hypothesis_text": "bad",
        "expected_effect": "bad",
    }
)


def _mock_client(
    response_text: str, *, input_tokens: int = 500, output_tokens: int = 200
) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = [MagicMock(text=response_text)]
    message.usage.input_tokens = input_tokens
    message.usage.output_tokens = output_tokens
    client.messages.create.return_value = message
    return client


async def test_generate_hypothesis_produces_valid_spec() -> None:
    client = _mock_client(_VALID_RESPONSE_JSON)
    result = await generate_hypothesis(
        client, "claude-sonnet-5", "BTC/USDT", "1d",
        [PaperContext(paper_id=1, key_sections="momentum literature review")],
    )
    assert result.spec.family == "MOMENTUM"
    assert result.spec.fast_window == 10
    assert result.spec.slow_window == 50
    assert result.spec.source == "llm_hypothesis"
    assert result.paper_ids == [1]
    assert result.input_tokens == 500
    assert result.output_tokens == 200
    assert result.est_cost_usd > 0


async def test_generate_hypothesis_raises_on_invalid_spec_rather_than_coercing() -> None:
    client = _mock_client(_MALFORMED_RESPONSE_JSON)
    with pytest.raises(ValueError):
        await generate_hypothesis(
            client, "claude-sonnet-5", "BTC/USDT", "1d",
            [PaperContext(paper_id=1, key_sections="momentum literature review")],
        )


async def test_generate_hypothesis_raises_value_error_on_unknown_family() -> None:
    """An unknown family is a KeyError against the internal param_fields
    dict -- must surface as ValueError, not KeyError, so callers can rely
    on catching just ValueError for "this response was malformed."""
    client = _mock_client(_UNKNOWN_FAMILY_RESPONSE_JSON)
    with pytest.raises(ValueError):
        await generate_hypothesis(
            client, "claude-sonnet-5", "BTC/USDT", "1d",
            [PaperContext(paper_id=1, key_sections="momentum literature review")],
        )

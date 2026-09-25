"""tests/test_llm_hypothesis.py"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from prometheus.research.llm.hypothesis import (
    LLMResponseError,
    PaperContext,
    generate_hypothesis,
)

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
    response_text: str,
    *,
    input_tokens: int = 500,
    output_tokens: int = 200,
    leading_blocks: list[MagicMock] | None = None,
    stop_reason: str = "end_turn",
) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = [*(leading_blocks or []), MagicMock(type="text", text=response_text)]
    message.stop_reason = stop_reason
    message.usage.input_tokens = input_tokens
    message.usage.output_tokens = output_tokens
    client.messages.create.return_value = message
    return client


async def test_generate_hypothesis_reads_the_text_block_after_a_thinking_block() -> None:
    """Production 2026-09-25: claude-sonnet-5 returned a ThinkingBlock as
    content[0]; reading content[0].text raised AttributeError and every
    hypothesis was discarded after being billed."""
    thinking = MagicMock(spec=["type", "thinking"], type="thinking", thinking="")
    client = _mock_client(_VALID_RESPONSE_JSON, leading_blocks=[thinking])
    result = await generate_hypothesis(
        client, "claude-sonnet-5", "BTC/USDT", "1d",
        [PaperContext(paper_id=1, key_sections="momentum literature review")],
    )
    assert result.spec.family == "MOMENTUM"


async def test_generate_hypothesis_disables_thinking() -> None:
    client = _mock_client(_VALID_RESPONSE_JSON)
    await generate_hypothesis(
        client, "claude-sonnet-5", "BTC/USDT", "1d",
        [PaperContext(paper_id=1, key_sections="x")],
    )
    assert client.messages.create.call_args.kwargs["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
async def test_generate_hypothesis_rejects_truncated_or_refused_responses(
    stop_reason: str,
) -> None:
    client = _mock_client(_VALID_RESPONSE_JSON, stop_reason=stop_reason, output_tokens=1024)
    with pytest.raises(LLMResponseError) as excinfo:
        await generate_hypothesis(
            client, "claude-sonnet-5", "BTC/USDT", "1d",
            [PaperContext(paper_id=1, key_sections="x")],
        )
    assert excinfo.value.output_tokens == 1024


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


@pytest.mark.parametrize(
    "response_text",
    [
        _MALFORMED_RESPONSE_JSON,  # fails StrategySpec's own model_validator
        _UNKNOWN_FAMILY_RESPONSE_JSON,  # KeyError against the param_fields dict
        "not json at all",  # json.JSONDecodeError
    ],
    ids=["invalid-spec", "unknown-family", "unparseable-json"],
)
async def test_every_post_call_failure_raises_llm_response_error_carrying_usage(
    response_text: str,
) -> None:
    """I3 (final-review fix wave): the Anthropic call already billed by
    the time ANY of these failures happen, so each must surface as
    LLMResponseError carrying the exact token counts and model the caller
    needs to write the llm_usage row. LLMResponseError subclasses
    ValueError, so callers catching ValueError are unaffected."""
    client = _mock_client(response_text, input_tokens=777, output_tokens=333)
    with pytest.raises(LLMResponseError) as excinfo:
        await generate_hypothesis(
            client, "claude-sonnet-5", "BTC/USDT", "1d",
            [PaperContext(paper_id=1, key_sections="momentum literature review")],
        )

    assert isinstance(excinfo.value, ValueError)
    assert excinfo.value.input_tokens == 777
    assert excinfo.value.output_tokens == 333
    assert excinfo.value.model == "claude-sonnet-5"

"""AlpacaProvider.fetch_bars() against mocked httpx responses -- no live
network call, no real API key needed to run this suite. Response shapes
below match Alpaca's documented GET /v2/stocks/bars schema exactly
(fields t/o/h/l/c/v; n and vw are present in real responses but unused
here).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prometheus.data.providers.alpaca import AlpacaProvider
from prometheus.data.providers.base import RawBar

_ONE_PAGE_RESPONSE = {
    "bars": {
        "SPY": [
            {
                "t": "2024-01-02T05:00:00Z",
                "o": 470.0,
                "h": 471.5,
                "l": 469.0,
                "c": 470.5,
                "v": 1000000.0,
                "n": 5000,
                "vw": 470.2,
            },
            {
                "t": "2024-01-03T05:00:00Z",
                "o": 470.5,
                "h": 472.0,
                "l": 470.0,
                "c": 471.0,
                "v": 1100000.0,
                "n": 5200,
                "vw": 471.1,
            },
        ]
    },
    "next_page_token": None,
}

_PAGE_1_RESPONSE = {
    "bars": {
        "SPY": [
            {
                "t": "2024-01-02T05:00:00Z",
                "o": 470.0,
                "h": 471.5,
                "l": 469.0,
                "c": 470.5,
                "v": 1000000.0,
                "n": 1,
                "vw": 470.0,
            }
        ]
    },
    "next_page_token": "abc123",
}
_PAGE_2_RESPONSE = {
    "bars": {
        "SPY": [
            {
                "t": "2024-01-03T05:00:00Z",
                "o": 470.5,
                "h": 472.0,
                "l": 470.0,
                "c": 471.0,
                "v": 1100000.0,
                "n": 1,
                "vw": 471.0,
            }
        ]
    },
    "next_page_token": None,
}


def _mock_client(*responses: dict[str, object]) -> MagicMock:
    mock_response_objs = []
    for body in responses:
        resp = MagicMock()
        resp.json.return_value = body
        resp.raise_for_status = MagicMock()
        mock_response_objs.append(resp)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=mock_response_objs)
    return client


@patch.dict(
    os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"}
)
async def test_fetch_bars_parses_one_page_into_raw_bars() -> None:
    with patch("httpx.AsyncClient", return_value=_mock_client(_ONE_PAGE_RESPONSE)):
        provider = AlpacaProvider()
        bars = await provider.fetch_bars(
            ["SPY"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    assert bars == [
        RawBar(
            symbol="SPY",
            event_time=datetime(2024, 1, 2, 5, 0, tzinfo=UTC),
            open=470.0,
            high=471.5,
            low=469.0,
            close=470.5,
            volume=1000000.0,
        ),
        RawBar(
            symbol="SPY",
            event_time=datetime(2024, 1, 3, 5, 0, tzinfo=UTC),
            open=470.5,
            high=472.0,
            low=470.0,
            close=471.0,
            volume=1100000.0,
        ),
    ]


@patch.dict(
    os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"}
)
async def test_fetch_bars_follows_pagination() -> None:
    mock = _mock_client(_PAGE_1_RESPONSE, _PAGE_2_RESPONSE)
    with patch("httpx.AsyncClient", return_value=mock):
        provider = AlpacaProvider()
        bars = await provider.fetch_bars(
            ["SPY"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    assert len(bars) == 2
    assert mock.get.await_count == 2


@patch.dict(
    os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"}
)
async def test_fetch_bars_sends_auth_headers_and_raw_adjustment() -> None:
    mock = _mock_client(_ONE_PAGE_RESPONSE)
    with patch("httpx.AsyncClient", return_value=mock):
        provider = AlpacaProvider()
        await provider.fetch_bars(
            ["SPY"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    _, kwargs = mock.get.await_args
    assert kwargs["headers"]["APCA-API-KEY-ID"] == "test-key"
    assert kwargs["headers"]["APCA-API-SECRET-KEY"] == "test-secret"
    assert kwargs["params"]["adjustment"] == "raw"


async def test_fetch_bars_raises_a_clear_error_without_credentials() -> None:
    with patch.dict(os.environ, {}, clear=True):
        provider = AlpacaProvider()
        with pytest.raises(KeyError):
            await provider.fetch_bars(
                ["SPY"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 5, tzinfo=UTC),
                "1d",
            )


def test_capabilities_are_true_for_a_real_audited_feed() -> None:
    caps = AlpacaProvider().capabilities()
    assert caps["survivorship_safe"] is True
    assert caps["point_in_time"] is True
    assert caps["asset_classes"] == ["etf"]

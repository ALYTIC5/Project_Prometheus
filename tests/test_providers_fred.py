"""FREDProvider.fetch_bars() against mocked httpx responses -- no live
network call, no real API key needed to run this suite. Response shape
matches FRED's documented GET /fred/series/observations schema exactly
(realtime_start/realtime_end/date/value per observation).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prometheus.data.providers.base import RawBar
from prometheus.data.providers.fred import FREDProvider

_TWO_OBSERVATIONS_RESPONSE = {
    "observations": [
        {"realtime_start": "2024-01-02", "realtime_end": "2024-01-02", "date": "2024-01-02", "value": "13.20"},
        {"realtime_start": "2024-01-03", "realtime_end": "2024-01-03", "date": "2024-01-03", "value": "13.35"},
    ]
}

_WITH_MISSING_OBSERVATION_RESPONSE = {
    "observations": [
        {"realtime_start": "2024-01-01", "realtime_end": "2024-01-01", "date": "2024-01-01", "value": "."},
        {"realtime_start": "2024-01-02", "realtime_end": "2024-01-02", "date": "2024-01-02", "value": "13.20"},
    ]
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


@patch.dict(os.environ, {"FRED_API_KEY": "test-key"})
async def test_fetch_bars_parses_observations_into_flat_ohlc_raw_bars() -> None:
    with patch("httpx.AsyncClient", return_value=_mock_client(_TWO_OBSERVATIONS_RESPONSE)):
        provider = FREDProvider()
        bars = await provider.fetch_bars(
            ["FRED:VIXCLS"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    assert bars == [
        RawBar(
            symbol="FRED:VIXCLS", event_time=datetime(2024, 1, 2, tzinfo=UTC),
            open=13.20, high=13.20, low=13.20, close=13.20, volume=0.0,
        ),
        RawBar(
            symbol="FRED:VIXCLS", event_time=datetime(2024, 1, 3, tzinfo=UTC),
            open=13.35, high=13.35, low=13.35, close=13.35, volume=0.0,
        ),
    ]


@patch.dict(os.environ, {"FRED_API_KEY": "test-key"})
async def test_fetch_bars_skips_missing_observations() -> None:
    """FRED marks a missing observation (e.g. a market holiday) with the
    literal string "." -- must be skipped, not fabricated as 0.0 or
    crash on float('.')."""
    with patch(
        "httpx.AsyncClient", return_value=_mock_client(_WITH_MISSING_OBSERVATION_RESPONSE)
    ):
        provider = FREDProvider()
        bars = await provider.fetch_bars(
            ["FRED:VIXCLS"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    assert len(bars) == 1
    assert bars[0].event_time == datetime(2024, 1, 2, tzinfo=UTC)


@patch.dict(os.environ, {"FRED_API_KEY": "test-key"})
async def test_fetch_bars_sends_series_id_and_api_key() -> None:
    mock = _mock_client(_TWO_OBSERVATIONS_RESPONSE)
    with patch("httpx.AsyncClient", return_value=mock):
        provider = FREDProvider()
        await provider.fetch_bars(
            ["FRED:VIXCLS"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )

    _, kwargs = mock.get.await_args
    assert kwargs["params"]["series_id"] == "VIXCLS"
    assert kwargs["params"]["api_key"] == "test-key"


@patch.dict(os.environ, {"FRED_API_KEY": "test-key"})
async def test_fetch_bars_rejects_a_series_not_confirmed_non_revised() -> None:
    """A revised series (e.g. GDP, CPI) fetched through this same client
    would NOT be point-in-time-safe -- FREDProvider must refuse rather
    than silently serve a Law-1-unsafe series."""
    provider = FREDProvider()
    with pytest.raises(ValueError, match="non-revised"):
        await provider.fetch_bars(
            ["FRED:GDP"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "1d",
        )


@patch.dict(os.environ, {"FRED_API_KEY": "test-key"})
async def test_fetch_bars_rejects_non_daily_interval() -> None:
    provider = FREDProvider()
    with pytest.raises(ValueError, match="1d"):
        await provider.fetch_bars(
            ["FRED:VIXCLS"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            "4h",
        )


async def test_fetch_bars_raises_a_clear_error_without_credentials() -> None:
    with patch.dict(os.environ, {}, clear=True):
        provider = FREDProvider()
        with pytest.raises(KeyError):
            await provider.fetch_bars(
                ["FRED:VIXCLS"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 5, tzinfo=UTC),
                "1d",
            )


def test_capabilities_are_true_for_a_real_audited_feed() -> None:
    caps = FREDProvider().capabilities()
    assert caps["survivorship_safe"] is True
    assert caps["point_in_time"] is True
    assert caps["asset_classes"] == ["macro"]

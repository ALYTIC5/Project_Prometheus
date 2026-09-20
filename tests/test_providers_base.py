"""MarketDataProvider is an ABC with no real behavior of its own to
test beyond "the interface shape is what callers depend on" -- concrete
adapters (AlpacaProvider) get their own real behavioral tests.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar
from prometheus.data.providers.stocks import StockProvider


def test_raw_bar_is_frozen_and_has_no_available_at_field() -> None:
    """RawBar deliberately excludes available_at/source/revision --
    those are orchestration decisions (ingestion-lag policy), not
    provider concerns. A provider that tried to set available_at would
    be making a policy call it shouldn't be trusted to make."""
    bar = RawBar(
        symbol="SPY",
        event_time=datetime(2024, 1, 2, tzinfo=UTC),
        open=470.0,
        high=471.0,
        low=469.0,
        close=470.5,
        volume=1_000_000.0,
    )
    assert not hasattr(bar, "available_at")
    with pytest.raises(AttributeError):
        bar.open = 999.0  # type: ignore[misc]


def test_market_data_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        MarketDataProvider()  # type: ignore[abstract]


async def test_stock_provider_declares_itself_unimplemented() -> None:
    provider = StockProvider()
    with pytest.raises(NotImplementedError):
        await provider.fetch_bars(
            ["AAPL"], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC), "1d"
        )


def test_stock_provider_capabilities_are_honest_about_being_unimplemented() -> None:
    caps: ProviderCapabilities = StockProvider().capabilities()
    assert caps["survivorship_safe"] is False
    assert caps["point_in_time"] is False

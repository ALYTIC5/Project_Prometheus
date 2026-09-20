"""The provider-agnostic interface every market data source implements.
One schema (RawBar), many adapters (AlpacaProvider today; a future
CcxtProvider wraps today's ccxt-based crypto ingestion; StockProvider is
an intentional stub) so a new data source slots in without a rewrite.

Every adapter DECLARES whether it is survivorship-safe and point-in-time
via capabilities(). That flag is meant to propagate into data_version
and every backtest result downstream (prometheus.data.versioning) --
never invent a "probably fine" default for it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


@dataclass(frozen=True)
class RawBar:
    """One bar as a provider hands it over -- deliberately missing
    available_at/source/revision. Ingestion-lag policy (how long after
    event_time a bar becomes knowable) is an orchestration decision, the
    same way prometheus.data.ingestion's _INGESTION_LAG constant lives
    in the orchestration layer today, not inside any exchange client."""

    symbol: str
    event_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class ProviderCapabilities(TypedDict):
    asset_classes: list[str]
    intervals: list[str]
    survivorship_safe: bool
    point_in_time: bool
    rate_limit: str


class MarketDataProvider(ABC):
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]: ...

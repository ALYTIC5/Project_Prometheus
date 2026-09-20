"""Single-stock data adapter -- deliberately unimplemented (PROMPT 2's
2.3e). Every genuinely free source for single-stock history is either
survivorship-biased or split-adjusted in place (yfinance, most free
scrapers): silently wiring one up would make every backtest on it look
better than reality without any way to tell which results were real,
which is exactly the failure this whole point-in-time layer exists to
prevent. Do NOT implement this against yfinance or an equivalent free
scrape under time pressure -- wait for a real survivorship-safe source
(Polygon, Sharadar, or Tiingo, roughly $30-100/mo) and revisit after the
system has proven the machinery produces trustworthy results at all.
"""
from __future__ import annotations

from datetime import datetime

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar


class StockProvider(MarketDataProvider):
    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["stock"],
            "intervals": [],
            "survivorship_safe": False,
            "point_in_time": False,
            "rate_limit": "n/a -- unimplemented",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        raise NotImplementedError(
            "Single-stock data needs a survivorship-safe paid provider "
            "(Polygon, Sharadar, or Tiingo) -- see this module's docstring. "
            "Never wire this up against yfinance or an equivalent free scrape."
        )

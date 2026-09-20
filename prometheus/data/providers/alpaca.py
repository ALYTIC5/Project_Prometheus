"""Alpaca Market Data API adapter -- ETF/index daily bars. Legacy
header auth (APCA-API-KEY-ID/APCA-API-SECRET-KEY), not the OAuth2
client_credentials flow (that's Broker API only, a different product
for platforms managing multiple end-users' accounts -- confirmed
against Alpaca's own docs, not assumed). Free tier, real signup
required, but a documented and stable REST API, unlike the keyless
sources that turned out not to work (see this sub-project's design doc
for why Stooq was ruled out).
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

_BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
_TIMEFRAME_MAP = {"1d": "1Day"}
_PAGE_LIMIT = 10000


class AlpacaProvider(MarketDataProvider):
    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["etf"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            "point_in_time": True,
            "rate_limit": "200 req/min (free tier)",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        # Read at call time, not __init__/import time -- importing this
        # module must never require a real credential to be set, same
        # posture as worker._anthropic_client().
        headers = {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        }
        timeframe = _TIMEFRAME_MAP[interval]

        bars: list[RawBar] = []
        async with httpx.AsyncClient() as client:
            for symbol in symbols:
                page_token: str | None = None
                while True:
                    params: dict[str, str | int] = {
                        "symbols": symbol,
                        "timeframe": timeframe,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "adjustment": "raw",
                        "limit": _PAGE_LIMIT,
                    }
                    if page_token is not None:
                        params["page_token"] = page_token
                    response = await client.get(_BASE_URL, headers=headers, params=params)
                    response.raise_for_status()
                    body = response.json()
                    for raw in body["bars"].get(symbol, []):
                        bars.append(
                            RawBar(
                                symbol=symbol,
                                event_time=datetime.fromisoformat(raw["t"].replace("Z", "+00:00")),
                                open=float(raw["o"]),
                                high=float(raw["h"]),
                                low=float(raw["l"]),
                                close=float(raw["c"]),
                                volume=float(raw["v"]),
                            )
                        )
                    page_token = body.get("next_page_token")
                    if page_token is None:
                        break
        return bars

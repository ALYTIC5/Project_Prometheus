"""Yahoo Finance chart API adapter -- ETF daily bars, no API key.

Chosen 2026-09-25 (user direction: keyless public data instead of an Alpaca
signup) after checking the alternatives: Stooq is keyless but serves only
dividend+split-ADJUSTED history (a Law 1 leak -- adjustments are computed
from future corporate actions); Alpha Vantage/Tiingo/EODHD/Finnhub all need
a key. Yahoo's v8 chart endpoint answered from Railway's own network
(verified before building this).

Law 1 handling: Yahoo's OHLC is split-adjusted in place (not dividend-
adjusted). This adapter REVERSES splits using Yahoo's own split events
(`events=split`), so every bar carries the price actually traded that day
-- the same raw contract providers/alpaca.py gets via adjustment=raw.

event_time is the session DATE at 00:00 UTC (Yahoo stamps bars at the
exchange open); data.ingestion.bar_available_at then makes a bar knowable
only after that UTC day ends, i.e. after the US close.

Honest limits, recorded in capabilities(): not an official, contracted
feed (it can rate-limit or change shape), and not survivorship-safe for
arbitrary tickers -- acceptable here because the ETF universe is a fixed
list of live funds whose Law 2 listing dates come from
config/universe_etf.yaml, not from this provider.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; prometheus-research/1.0)"}
_INTERVAL_MAP = {"1d": "1d"}


def parse_chart(symbol: str, body: dict[str, Any]) -> list[RawBar]:
    """Yahoo chart JSON -> raw (split-reversed) daily bars. Days with any
    null OHLC field (Yahoo's placeholder for a missing session) are
    skipped, never forward-filled."""
    result = body["chart"]["result"][0]
    timestamps: list[int] = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    splits = (result.get("events") or {}).get("splits") or {}
    split_points = sorted(
        (int(s["date"]), float(s["numerator"]) / float(s["denominator"])) for s in splits.values()
    )

    bars: list[RawBar] = []
    for i, ts in enumerate(timestamps):
        values = [quote[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in values):
            continue
        # Splits effective AFTER this bar were applied to it retroactively;
        # undo them to recover the price that actually traded.
        factor = 1.0
        for split_ts, ratio in split_points:
            if split_ts > ts:
                factor *= ratio
        o, h, low, c, v = (float(x) for x in values)
        session_date = datetime.fromtimestamp(ts, tz=UTC).date()
        bars.append(
            RawBar(
                symbol=symbol,
                event_time=datetime(
                    session_date.year, session_date.month, session_date.day, tzinfo=UTC
                ),
                open=o * factor,
                high=h * factor,
                low=low * factor,
                close=c * factor,
                volume=v / factor,
            )
        )
    return bars


class YahooChartProvider(MarketDataProvider):
    SOURCE = "yahoo"

    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["etf"],
            "intervals": ["1d"],
            "survivorship_safe": False,
            "point_in_time": True,
            "rate_limit": "unofficial public endpoint; no published limit",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        bars: list[RawBar] = []
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0) as client:
            for symbol in symbols:
                response = await client.get(
                    _CHART_URL.format(symbol=symbol),
                    params={
                        "period1": int(start.timestamp()),
                        "period2": int(end.timestamp()),
                        "interval": _INTERVAL_MAP[interval],
                        "events": "split",
                    },
                )
                response.raise_for_status()
                bars.extend(parse_chart(symbol, response.json()))
        return bars

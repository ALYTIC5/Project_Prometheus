"""FRED (Federal Reserve Bank of St. Louis) adapter -- macro/index
series ingested as synthetic single-symbol point-in-time "bars", the
same MarketDataProvider interface AlpacaProvider already implements.

Deliberately restricted to non-revised series (VIXCLS -- the CBOE
Volatility Index close -- today; a caller adding a new series must
verify it shares this property before reusing this provider for it).
FRED's free basic API returns each observation's LATEST value, not the
value as it was known on that observation's own date -- fine for a
series like VIXCLS, which is published once and never restated, but
would be a real Law 1 violation for a revised series (GDP, CPI,
employment all get restated after first release; using today's revised
figure as if it were known on the original date is exactly the kind of
look-ahead this project's own point-in-time architecture exists to
prevent). FRED's ALFRED vintage API solves this properly for revised
series but is a separate, unbuilt integration -- not silently assumed
here.

Each observation becomes one RawBar with open=high=low=close=value
(FRED gives one number per day, not real OHLC) and volume=0.0 (no
volume concept for an index level) -- honest about being a single
observation, not a fabricated four-number range. See data/quality.py's
`skip_stale_check` for why this shape needs its own ingestion path
rather than reusing ingestion.py's/ingest_etf.py's default quality
gate, which correctly rejects flat-OHLC bars for a real tradeable
instrument.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Series confirmed non-revised (published once, never restated) --
# capabilities() below only ever claims point_in_time=True for a series
# in this set. Extend only after checking the new series' own FRED
# documentation makes the same "not subject to revision" claim VIXCLS
# does.
_NON_REVISED_SERIES = {"VIXCLS"}


class FREDProvider(MarketDataProvider):
    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["macro"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            # True only for the non-revised series this adapter is
            # restricted to (see module docstring) -- a genuinely
            # revised series fetched through this same client would NOT
            # be point-in-time-safe, so this flag is a property of which
            # series are actually requested, not of the adapter itself.
            "point_in_time": True,
            "rate_limit": "120 req/min (free tier)",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        if interval != "1d":
            raise ValueError(f"FREDProvider only supports interval='1d', got {interval!r}")

        # Read at call time, not __init__/import time -- importing this
        # module must never require a real credential to be set, same
        # posture as AlpacaProvider.fetch_bars/worker._anthropic_client().
        api_key = os.environ["FRED_API_KEY"]

        bars: list[RawBar] = []
        async with httpx.AsyncClient() as client:
            for symbol in symbols:
                series_id = symbol.removeprefix("FRED:")
                if series_id not in _NON_REVISED_SERIES:
                    raise ValueError(
                        f"FREDProvider only serves non-revised series {_NON_REVISED_SERIES}, "
                        f"got {series_id!r} -- verify it is genuinely non-revised before adding "
                        "it to _NON_REVISED_SERIES (see module docstring)"
                    )
                params = {
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "observation_start": start.date().isoformat(),
                    "observation_end": end.date().isoformat(),
                }
                response = await client.get(_BASE_URL, params=params)
                response.raise_for_status()
                body = response.json()
                for obs in body.get("observations", []):
                    # FRED marks a missing observation (e.g. a market
                    # holiday) with the literal string "." -- skip it
                    # rather than fabricating a value.
                    if obs["value"] == ".":
                        continue
                    value = float(obs["value"])
                    event_time = datetime.fromisoformat(obs["date"]).replace(tzinfo=UTC)
                    bars.append(
                        RawBar(
                            symbol=symbol,
                            event_time=event_time,
                            open=value,
                            high=value,
                            low=value,
                            close=value,
                            volume=0.0,
                        )
                    )
        return bars

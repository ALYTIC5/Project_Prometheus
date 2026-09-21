"""Macro/index series ingestion via FREDProvider -- reuses the exact
same MarketDataProvider/quality-check/holdout-split/versioning
machinery ingest_etf.py already established for ETFs, applied to a
genuinely different asset class (macro index levels, not tradeable
instruments) via the same generic asset_class column
universe_membership already supports. Deliberately isolated from
ingestion.py (crypto/ccxt) and ingest_etf.py (Alpaca/equity) -- same
"small duplication, deliberately short-lived until a future sub-project
unifies every path behind MarketDataProvider" posture ingest_etf.py's
own docstring already states.

Not yet wired into any strategy signal: this ships the ingestion
pipeline only (real macro data lands in ohlcv_bars, point-in-time-safe,
versioned, queryable) -- see docs/DEFERRED.md's "FRED macro feature
integration" entry for why turning this into an actual ml_features.py
feature is deliberately scoped as separate, future work rather than
built in the same pass as the ingestion pipeline.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from prometheus.core.db import get_session
from prometheus.data.ingestion import (
    _INSERT_BAR,
    _INSERT_HOLDOUT_BAR,
    _INSERT_RAW,
    _UPDATE_RAW_STATUS,
)
from prometheus.data.providers.base import MarketDataProvider
from prometheus.data.providers.fred import FREDProvider
from prometheus.data.quality import run_quality_checks
from prometheus.data.universe import load_universe_symbols_for_asset_class, sync_from_yaml
from prometheus.data.versioning import record_data_version
from prometheus.experiments.violations import record_config_snapshot
from prometheus.validation.holdout import load_holdout_config

_UNIVERSE_MACRO_YAML = "config/universe_macro.yaml"
_TIMEFRAME = "1d"
_INGESTION_LAG = timedelta(minutes=5)
_SOURCE = "fred"
# Same 100h tolerance ingest_etf.py uses -- FRED's VIXCLS is a business-
# day series (weekends/holidays are expected gaps), same non-24/7
# calendar reasoning, not a coincidence (both track US market sessions).
_MAX_GAP_HOURS = 100.0

_HOLDOUT_CONFIG, _ = load_holdout_config()


async def backfill_macro(
    days: int,
    symbols: list[str] | None = None,
    provider: MarketDataProvider | None = None,
    end: datetime | None = None,
) -> None:
    """`end` defaults to now -- overridable so a test can pin a fixed
    window instead of always reaching up to the live holdout boundary,
    same reasoning backfill_etf's own docstring gives."""
    provider = provider or FREDProvider()
    now = end or datetime.now(UTC)
    since = now - timedelta(days=days)
    holdout_cutoff = datetime.combine(_HOLDOUT_CONFIG.holdout_start, datetime.min.time(), UTC)

    async with get_session() as session:
        await sync_from_yaml(session, _UNIVERSE_MACRO_YAML, asset_class="macro")
        await record_config_snapshot(session, _UNIVERSE_MACRO_YAML)
        await session.commit()

        resolved_symbols = symbols or await load_universe_symbols_for_asset_class(
            session, "macro"
        )

        for symbol in resolved_symbols:
            raw_bars = await provider.fetch_bars([symbol], since, now, _TIMEFRAME)
            raw_rows = [
                b.__dict__ | {"event_time": b.event_time.isoformat()} for b in raw_bars
            ]
            raw_id = (
                await session.execute(
                    _INSERT_RAW,
                    {
                        "source": _SOURCE,
                        "symbol": symbol,
                        "timeframe": _TIMEFRAME,
                        "payload": {"rows": raw_rows},
                    },
                )
            ).scalar_one()

            if not raw_bars:
                await session.execute(
                    _UPDATE_RAW_STATUS,
                    {"status": "normalized", "quality_issues": None, "id": raw_id},
                )
                await session.commit()
                continue

            bars: list[dict[str, Any]] = [
                {
                    "symbol": b.symbol,
                    "timeframe": _TIMEFRAME,
                    "event_time": b.event_time,
                    "available_at": b.event_time + _INGESTION_LAG,
                    "source": _SOURCE,
                    "revision": 1,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in raw_bars
            ]
            frame = pl.DataFrame(bars)
            report = run_quality_checks(
                frame, _TIMEFRAME, max_gap_hours=_MAX_GAP_HOURS, skip_stale_check=True
            )

            if not report.passed:
                await session.execute(
                    _UPDATE_RAW_STATUS,
                    {
                        "status": "quarantined",
                        "quality_issues": {"issues": report.issues},
                        "id": raw_id,
                    },
                )
                await session.commit()
                continue

            for bar in bars:
                if bar["event_time"] >= holdout_cutoff:
                    await session.execute(_INSERT_HOLDOUT_BAR, bar)
                else:
                    await session.execute(_INSERT_BAR, bar)
            await session.execute(
                _UPDATE_RAW_STATUS,
                {"status": "normalized", "quality_issues": None, "id": raw_id},
            )
            await session.commit()

            await record_data_version(
                session,
                frame,
                date_range_start=since.date(),
                date_range_end=now.date(),
                source_versions={_SOURCE: {"version": "v1", **provider.capabilities()}},
            )
            await session.commit()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill macro/index daily series via FRED.")
    parser.add_argument("--days", type=int, default=2000)
    return parser.parse_args(argv)


def main() -> None:
    import asyncio

    args = _parse_args()
    asyncio.run(backfill_macro(days=args.days))


if __name__ == "__main__":
    main()

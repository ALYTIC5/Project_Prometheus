"""ETF/index daily-bar ingestion (default provider: keyless YahooChartProvider
since 2026-09-25; AlpacaProvider remains usable by passing it in) -- PROMPT 2's
"honest equity path". Deliberately isolated from ingestion.py's
crypto/ccxt path (this sub-project's design doc, Approach B): reuses
the *existing* quality-check, holdout-split, and versioning machinery
(quality.run_quality_checks's max_gap_hours override accounts for
non-24/7 markets -- see this task's Step 2), but does not touch
ingestion.py itself. A future sub-project unifies both paths behind
MarketDataProvider once crypto migrates onto it too -- the small
duplication here (the holdout-split insert loop) is deliberately
short-lived, not a permanent fork.
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
    bar_available_at,
    latest_stored_revisions,
    plan_bar_writes,
)
from prometheus.data.providers.base import MarketDataProvider
from prometheus.data.providers.yahoo import YahooChartProvider
from prometheus.data.quality import run_quality_checks
from prometheus.data.universe import load_universe_symbols_for_asset_class, sync_from_yaml
from prometheus.data.versioning import record_data_version
from prometheus.experiments.violations import record_config_snapshot
from prometheus.validation.holdout import load_holdout_config

_UNIVERSE_ETF_YAML = "config/universe_etf.yaml"
_TIMEFRAME = "1d"

_HOLDOUT_CONFIG, _ = load_holdout_config()


async def backfill_etf(
    days: int,
    symbols: list[str] | None = None,
    provider: MarketDataProvider | None = None,
    end: datetime | None = None,
) -> None:
    """`end` defaults to now -- overridable so a test can pin a fixed
    window instead of always reaching up to the live holdout boundary
    (config/holdout.yaml's holdout_start), which would otherwise write
    fake test bars into the shared Law-3-protected holdout schema."""
    provider = provider or YahooChartProvider()
    source = getattr(provider, "SOURCE", type(provider).__name__.lower())
    now = end or datetime.now(UTC)
    since = now - timedelta(days=days)
    holdout_cutoff = datetime.combine(_HOLDOUT_CONFIG.holdout_start, datetime.min.time(), UTC)

    async with get_session() as session:
        await sync_from_yaml(session, _UNIVERSE_ETF_YAML, asset_class="etf")
        await record_config_snapshot(session, _UNIVERSE_ETF_YAML)
        await session.commit()

        resolved_symbols = symbols or await load_universe_symbols_for_asset_class(session, "etf")

        for symbol in resolved_symbols:
            raw_bars = await provider.fetch_bars([symbol], since, now, _TIMEFRAME)
            raw_rows = [
                b.__dict__ | {"event_time": b.event_time.isoformat()} for b in raw_bars
            ]
            raw_id = (
                await session.execute(
                    _INSERT_RAW,
                    {
                        "source": source,
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
                    "available_at": bar_available_at(b.event_time, _TIMEFRAME),
                    "source": source,
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
            # 100h: comfortably above a 3-day holiday weekend (~96h) on a
            # real equity/ETF calendar, still catches a genuinely broken
            # 4+ day outage. See this task's Step 2 for the full reasoning.
            report = run_quality_checks(frame, _TIMEFRAME, max_gap_hours=100.0)

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

            stored = await latest_stored_revisions(session, symbol, _TIMEFRAME, since)
            writes = plan_bar_writes(
                bars, existing=stored, now=datetime.now(UTC), timeframe=_TIMEFRAME
            )
            for bar in writes:
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
                source_versions={
                    source: {
                        "version": "v2",
                        # Discoverable/auditable in data_versions: which
                        # feed tier (e.g. Alpaca's free-tier "iex") the
                        # bars actually came from. Not every provider
                        # exposes this, hence the getattr guard.
                        "feed": getattr(provider, "FEED", None),
                        **provider.capabilities(),
                    }
                },
            )
            await session.commit()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ETF/index daily bars (keyless Yahoo chart API)."
    )
    parser.add_argument("--days", type=int, default=2000)
    return parser.parse_args(argv)


def main() -> None:
    import asyncio

    args = _parse_args()
    asyncio.run(backfill_etf(days=args.days))


if __name__ == "__main__":
    main()

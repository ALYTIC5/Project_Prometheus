"""ccxt-based Binance spot OHLCV ingestion. Idempotent via
INSERT ... ON CONFLICT DO NOTHING against ohlcv_bars' unique
(symbol, timeframe, event_time, revision) constraint — re-running never
duplicates. Rate-limit aware via ccxt's own throttling. Writes raw
responses to raw_ingest before any normalisation.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import polars as pl
import sqlalchemy as sa
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import get_session
from prometheus.data.quality import run_quality_checks
from prometheus.data.versioning import record_data_version

_TIMEFRAMES = ("1d", "4h")
_INGESTION_LAG = timedelta(minutes=5)

# `expanding=True` lets SQLAlchemy safely bind a Python list against an
# IN clause — the plain-string `ANY(:symbols)` form does not reliably
# adapt a list parameter through text() across dialects.
_SELECT_BARS_FOR_VERSIONING = text(
    """
    SELECT symbol, timeframe, event_time, available_at, open, high, low, close, volume
    FROM ohlcv_bars
    WHERE symbol IN :symbols AND event_time >= :since
    """
).bindparams(sa.bindparam("symbols", expanding=True))

_INSERT_RAW = text(
    """
    INSERT INTO raw_ingest (source, symbol, timeframe, payload, status)
    VALUES (:source, :symbol, :timeframe, :payload, 'pending')
    RETURNING id
    """
)

_INSERT_BAR = text(
    """
    INSERT INTO ohlcv_bars
        (symbol, timeframe, event_time, available_at, ingested_at, source, revision,
         open, high, low, close, volume)
    VALUES
        (:symbol, :timeframe, :event_time, :available_at, now(), :source, :revision,
         :open, :high, :low, :close, :volume)
    ON CONFLICT ON CONSTRAINT uq_ohlcv_bar_revision DO NOTHING
    """
)

_UPDATE_RAW_STATUS = text(
    "UPDATE raw_ingest SET status = :status, quality_issues = :quality_issues WHERE id = :id"
)


class ExchangeClient(Protocol):
    """The ccxt subset this module uses. Real ccxt.binance() satisfies
    this at runtime; tests inject a fake.
    """

    rateLimit: int

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int = 1000
    ) -> list[list[float]]: ...


def load_universe_symbols(path: str = "config/universe.yaml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [row["symbol"] for row in data["symbols"] if row.get("delisted_at") is None]


def ccxt_rows_to_bars(
    raw_rows: list[list[float]], symbol: str, timeframe: str, source: str
) -> list[dict[str, Any]]:
    """ccxt's fetch_ohlcv rows are [timestamp_ms, open, high, low, close,
    volume]. available_at = event_time + a fixed ingestion lag: the bar
    isn't knowable until it closes plus the time an exchange takes to
    serve it. This is the one place that lag is decided.
    """
    bars = []
    for ts_ms, o, h, low, c, v in raw_rows:
        event_time = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        bars.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "event_time": event_time,
                "available_at": event_time + _INGESTION_LAG,
                "source": source,
                "revision": 1,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
            }
        )
    return bars


async def ingest_symbol(
    session: AsyncSession,
    exchange: ExchangeClient,
    symbol: str,
    timeframe: str,
    since: datetime,
    source: str = "binance",
) -> None:
    since_ms = int(since.timestamp() * 1000)
    raw_rows = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
    raw_id = (
        await session.execute(
            _INSERT_RAW,
            {
                "source": source,
                "symbol": symbol,
                "timeframe": timeframe,
                "payload": {"rows": raw_rows},
            },
        )
    ).scalar_one()

    if not raw_rows:
        await session.execute(
            _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
        )
        await session.commit()
        return

    bars = ccxt_rows_to_bars(raw_rows, symbol, timeframe, source)
    frame = pl.DataFrame(bars)
    report = run_quality_checks(frame, timeframe)

    if not report.passed:
        await session.execute(
            _UPDATE_RAW_STATUS,
            {"status": "quarantined", "quality_issues": {"issues": report.issues}, "id": raw_id},
        )
        await session.commit()
        return

    for bar in bars:
        await session.execute(_INSERT_BAR, bar)
    await session.execute(
        _UPDATE_RAW_STATUS, {"status": "normalized", "quality_issues": None, "id": raw_id}
    )
    await session.commit()


async def _load_bars_for_versioning(
    session: AsyncSession, symbols: list[str], since: datetime
) -> pl.DataFrame:
    result = await session.execute(
        _SELECT_BARS_FOR_VERSIONING, {"symbols": symbols, "since": since}
    )
    rows = result.mappings().all()
    return pl.DataFrame(
        {
            "symbol": [r["symbol"] for r in rows],
            "timeframe": [r["timeframe"] for r in rows],
            "event_time": [r["event_time"] for r in rows],
            "available_at": [r["available_at"] for r in rows],
            "open": [float(r["open"]) for r in rows],
            "high": [float(r["high"]) for r in rows],
            "low": [float(r["low"]) for r in rows],
            "close": [float(r["close"]) for r in rows],
            "volume": [float(r["volume"]) for r in rows],
        }
    )


async def backfill(days: int, symbols: list[str] | None = None) -> None:
    import ccxt

    exchange = ccxt.binance()
    exchange.enableRateLimit = True
    symbols = symbols or load_universe_symbols()
    since = datetime.now(UTC) - timedelta(days=days)

    async with get_session() as session:
        for symbol in symbols:
            for timeframe in _TIMEFRAMES:
                await ingest_symbol(session, exchange, symbol, timeframe, since)
                await asyncio.sleep(exchange.rateLimit / 1000)

        # Law-adjacent requirement: every ingest run produces a
        # data_version row, not just the ones that happened to insert
        # new bars — this run's dataset is "everything in the backfilled
        # window for these symbols", read back rather than accumulated
        # in memory across the loop above (simpler, and correct even if
        # some bars pre-existed from an earlier run).
        frame = await _load_bars_for_versioning(session, symbols, since)
        if frame.height:
            await record_data_version(
                session,
                frame,
                date_range_start=since.date(),
                date_range_end=datetime.now(UTC).date(),
                source_versions={"binance": "ccxt/" + ccxt.__version__},
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest OHLCV data for the crypto-majors universe."
    )
    parser.add_argument("--backfill", action="store_true", help="run a historical backfill")
    parser.add_argument(
        "--days", type=int, default=800, help="how many days of history to backfill"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.backfill:
        asyncio.run(backfill(args.days))
    else:
        raise SystemExit("nothing to do — pass --backfill")


if __name__ == "__main__":
    main()

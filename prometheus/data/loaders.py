"""The one missing link in the data layer: DB -> PointInTimeFrame.

`ingestion.py`'s `_load_bars_for_versioning` reads `ohlcv_bars` back out,
but it is private and versioning-only (see its own module docstring).
Nothing before this module has ever loaded real bars for feature or
backtest use.
"""
from __future__ import annotations

from datetime import datetime

import polars as pl
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.schema import PointInTimeFrame
from prometheus.data.versioning import compute_content_hash

_SELECT_BARS = text(
    """
    SELECT symbol, timeframe, event_time, available_at, open, high, low, close, volume
    FROM ohlcv_bars
    WHERE symbol IN :symbols AND timeframe = :timeframe
      AND event_time >= :start AND event_time <= :end
    ORDER BY symbol, event_time
    """
).bindparams(sa.bindparam("symbols", expanding=True))

_FRAME_SCHEMA = {
    "symbol": pl.Utf8,
    "timeframe": pl.Utf8,
    "event_time": pl.Datetime("us", "UTC"),
    "available_at": pl.Datetime("us", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


async def load_point_in_time(
    session: AsyncSession,
    symbols: list[str],
    timeframe: str,
    start: datetime,
    end: datetime,
) -> tuple[PointInTimeFrame, str]:
    """Real bars from `ohlcv_bars` in [start, end], wrapped so the only way
    to read them back out is PointInTimeFrame.as_of() -- same discipline
    every other feature/backtest code path is held to. The second element
    is data.versioning.compute_content_hash() over the exact rows loaded --
    reused rather than recomputed differently, so an experiment's recorded
    data_version_hash matches what ingestion would have hashed for the
    identical rows -- for core.db.Experiment.data_version_hash
    (migration 0006)."""
    result = await session.execute(
        _SELECT_BARS, {"symbols": symbols, "timeframe": timeframe, "start": start, "end": end}
    )
    rows = result.mappings().all()
    frame = pl.DataFrame(
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
        },
        schema=_FRAME_SCHEMA,
    )
    return PointInTimeFrame(frame), compute_content_hash(frame)

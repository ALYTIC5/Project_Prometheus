"""Every ingest run produces a data_version row: content hash, row
count, date range, source versions. Backtests reference a data_version
and can be replayed against it.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from prometheus.data.models import DataVersion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def compute_content_hash(frame: pl.DataFrame) -> str:
    """Deterministic hash of a dataset's content: the full bar shape
    (symbol, timeframe, event_time, available_at, open, high, low, close,
    volume — matching prometheus.data.schema's bar columns), sorted by
    (symbol, timeframe, event_time) with ties held in their original
    order, so two datasets with identical bars hash identically regardless
    of row order, and a correction to any column — not just close — is
    detected.
    """
    canonical = frame.select(
        [
            "symbol",
            "timeframe",
            "event_time",
            "available_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    ).sort(["symbol", "timeframe", "event_time"], maintain_order=True)
    raw = canonical.write_csv()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_data_version(
    session: AsyncSession,
    frame: pl.DataFrame,
    date_range_start: date,
    date_range_end: date,
    source_versions: dict[str, str],
) -> DataVersion:
    version = DataVersion(
        content_hash=compute_content_hash(frame),
        row_count=frame.height,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        source_versions=source_versions,
    )
    session.add(version)
    await session.flush()
    return version

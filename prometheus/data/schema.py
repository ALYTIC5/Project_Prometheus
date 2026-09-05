"""Point-in-time OHLCV schema and the structurally-enforced accessor.

Every bar carries five extra fields beyond OHLCV: event_time (the bar's
own timestamp), available_at (when the bar became knowable — the ONLY
timestamp feature code may filter on), ingested_at (when we actually
pulled it), source, and revision (corrections are new rows with an
incremented revision, never an UPDATE — consistent with this repo's
append-only discipline elsewhere).

PointInTimeFrame is the only way feature code touches this data. Its
as_of() drops event_time from the returned schema entirely — not
filtered by convention, physically absent as a column.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

BAR_COLUMNS = (
    "symbol", "timeframe", "event_time", "available_at", "open", "high", "low", "close", "volume",
)
_POINT_IN_TIME_COLUMNS = (
    "symbol", "timeframe", "available_at", "open", "high", "low", "close", "volume",
)


@dataclass(frozen=True)
class OHLCVBar:
    """One normalised bar. source/ingested_at/revision are storage
    bookkeeping, not feature-visible, so they're intentionally absent
    here too — this dataclass shapes what feature code ever sees.
    """

    symbol: str
    timeframe: str
    event_time: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class PointInTimeFrame:
    """Wraps OHLCV rows. `as_of(cutoff)` is the only read path feature
    code gets: filters on available_at, and the returned frame's schema
    never contains event_time.
    """

    def __init__(self, frame: pl.DataFrame | pl.LazyFrame) -> None:
        missing = set(BAR_COLUMNS) - set(frame.collect_schema().names())
        if missing:
            raise ValueError(f"PointInTimeFrame is missing required columns: {sorted(missing)}")
        self._lf = frame.lazy()

    def as_of(self, cutoff: datetime) -> pl.DataFrame:
        return (
            self._lf.filter(pl.col("available_at") <= cutoff)
            .select(list(_POINT_IN_TIME_COLUMNS))
            .sort(["symbol", "available_at"])
            .collect()
        )

    @property
    def visible_columns(self) -> tuple[str, ...]:
        return _POINT_IN_TIME_COLUMNS

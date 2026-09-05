"""ORM models for the point-in-time data layer: raw exchange responses,
normalised OHLCV bars, universe membership history, and dataset
versioning. All share prometheus.core.db.Base's metadata.
"""
from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from prometheus.core.db import Base


class RawIngest(Base):
    __tablename__ = "raw_ingest"
    __table_args__ = (sa.Index("ix_raw_ingest_symbol_timeframe", "symbol", "timeframe"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(sa.String(32))
    symbol: Mapped[str] = mapped_column(sa.String(32))
    timeframe: Mapped[str] = mapped_column(sa.String(8))
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    quality_issues: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class OhlcvBar(Base):
    __tablename__ = "ohlcv_bars"
    __table_args__ = (
        sa.UniqueConstraint(
            "symbol", "timeframe", "event_time", "revision", name="uq_ohlcv_bar_revision"
        ),
        sa.Index(
            "ix_ohlcv_bars_symbol_timeframe_event_time", "symbol", "timeframe", "event_time"
        ),
        sa.Index("ix_ohlcv_bars_available_at", "available_at"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    timeframe: Mapped[str] = mapped_column(sa.String(8))
    event_time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    source: Mapped[str] = mapped_column(sa.String(32))
    revision: Mapped[int] = mapped_column(default=1)
    open: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    high: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    low: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    close: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    volume: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))


class UniverseMembership(Base):
    __tablename__ = "universe_membership"
    __table_args__ = (sa.Index("ix_universe_membership_symbol", "symbol"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    exchange: Mapped[str] = mapped_column(sa.String(32))
    listed_at: Mapped[date] = mapped_column(sa.Date)
    delisted_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)


class DataVersion(Base):
    __tablename__ = "data_versions"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    row_count: Mapped[int] = mapped_column(sa.BigInteger)
    date_range_start: Mapped[date] = mapped_column(sa.Date)
    date_range_end: Mapped[date] = mapped_column(sa.Date)
    source_versions: Mapped[dict[str, str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

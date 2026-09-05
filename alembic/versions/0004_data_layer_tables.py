"""data layer tables: raw_ingest, ohlcv_bars, universe_membership, data_versions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_ingest",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("quality_issues", JSONB, nullable=True),
    )
    op.create_index("ix_raw_ingest_symbol_timeframe", "raw_ingest", ["symbol", "timeframe"])

    op.create_table(
        "ohlcv_bars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(28, 8), nullable=False),
        sa.UniqueConstraint(
            "symbol", "timeframe", "event_time", "revision", name="uq_ohlcv_bar_revision"
        ),
    )
    op.create_index(
        "ix_ohlcv_bars_symbol_timeframe_event_time",
        "ohlcv_bars",
        ["symbol", "timeframe", "event_time"],
    )
    op.create_index("ix_ohlcv_bars_available_at", "ohlcv_bars", ["available_at"])

    op.create_table(
        "universe_membership",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("listed_at", sa.Date, nullable=False),
        sa.Column("delisted_at", sa.Date, nullable=True),
    )
    op.create_index("ix_universe_membership_symbol", "universe_membership", ["symbol"])

    op.create_table(
        "data_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.BigInteger, nullable=False),
        sa.Column("date_range_start", sa.Date, nullable=False),
        sa.Column("date_range_end", sa.Date, nullable=False),
        sa.Column("source_versions", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("data_versions")
    op.drop_index("ix_universe_membership_symbol", table_name="universe_membership")
    op.drop_table("universe_membership")
    op.drop_index("ix_ohlcv_bars_available_at", table_name="ohlcv_bars")
    op.drop_index("ix_ohlcv_bars_symbol_timeframe_event_time", table_name="ohlcv_bars")
    op.drop_table("ohlcv_bars")
    op.drop_index("ix_raw_ingest_symbol_timeframe", table_name="raw_ingest")
    op.drop_table("raw_ingest")

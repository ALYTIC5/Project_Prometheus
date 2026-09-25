"""ohlcv_bars / holdout.ohlcv_bars: available_at = candle CLOSE + lag.

Every ingestion path set available_at = event_time + 5 min, and event_time
is the candle's OPEN, so a daily bar's close price was labelled knowable
~24h before it existed (Law 1). Engine backtests were protected by their
own shift(1) discipline, but any as_of(cutoff) inside a candle -- holdout
boundaries, ablation windows, paper decisions -- could see that candle's
future close. data.ingestion.bar_available_at now uses close + lag; this
relabels existing rows by the same formula. Only rows still carrying the
old open+5min label are touched, so it is idempotent and never overwrites a
correction revision's own (later) available_at.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_TABLES = ("ohlcv_bars", "holdout.ohlcv_bars")
_DURATIONS = {"1d": "1 day", "4h": "4 hours", "1h": "1 hour"}


def upgrade() -> None:
    for table in _TABLES:
        for timeframe, duration in _DURATIONS.items():
            op.execute(
                f"""
                UPDATE {table}
                   SET available_at = event_time + interval '{duration}' + interval '5 minutes'
                 WHERE timeframe = '{timeframe}'
                   AND available_at = event_time + interval '5 minutes'
                """
            )


def downgrade() -> None:
    for table in _TABLES:
        for timeframe, duration in _DURATIONS.items():
            op.execute(
                f"""
                UPDATE {table}
                   SET available_at = event_time + interval '5 minutes'
                 WHERE timeframe = '{timeframe}'
                   AND available_at = event_time + interval '{duration}' + interval '5 minutes'
                """
            )

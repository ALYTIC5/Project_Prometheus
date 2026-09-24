"""benchmark_equity: one curve per universe, not one global date-keyed row.

docs/DEFERRED.md I5: record_benchmark_curve upserted ON CONFLICT (date), so
every spec's buy-and-hold overwrote every other universe's for the same
date -- the curve the world view / Monument rendered was whichever symbol
happened to run last. Adds `universe_key` (benchmark.universe_key(): sorted,
comma-joined symbols) and makes (universe_key, date) the unique key.

Existing rows are an unknowable mix of universes, so they are labelled
LEGACY_MIXED rather than attributed to any symbol (no invented default) and
readers ignore that key. They are superseded as soon as the worker records
real per-universe curves.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

LEGACY_KEY = "LEGACY_MIXED"


def upgrade() -> None:
    op.add_column(
        "benchmark_equity",
        sa.Column("universe_key", sa.String(), nullable=False, server_default=LEGACY_KEY),
    )
    op.alter_column("benchmark_equity", "universe_key", server_default=None)
    op.drop_index("ix_benchmark_equity_date", table_name="benchmark_equity")
    op.create_index(
        "uq_benchmark_equity_universe_date",
        "benchmark_equity",
        ["universe_key", "date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_benchmark_equity_universe_date", table_name="benchmark_equity")
    op.execute(f"DELETE FROM benchmark_equity WHERE universe_key <> '{LEGACY_KEY}'")
    op.create_index("ix_benchmark_equity_date", "benchmark_equity", ["date"], unique=True)
    op.drop_column("benchmark_equity", "universe_key")

"""strategies and benchmark_equity tables (Prompt 4)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("family", sa.String(16), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_strategies_family", "strategies", ["family"])

    # Deliberately NOT added to migration 0003's append-only trigger set
    # (which names exactly experiments/results/decisions) -- a strategy's
    # `status` is current lifecycle state, not a history log, and is meant
    # to be UPDATEd as that state changes.

    op.create_table(
        "benchmark_equity",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_benchmark_equity_date", "benchmark_equity", ["date"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_benchmark_equity_date", table_name="benchmark_equity")
    op.drop_table("benchmark_equity")
    op.drop_index("ix_strategies_family", table_name="strategies")
    op.drop_table("strategies")

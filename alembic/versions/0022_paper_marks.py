"""paper_marks: the latest close each paper tick actually decided on.

Every bar since holdout_start lives in the holdout vault, readable only via
validation.holdout.access_holdout_for_paper (worker). The /paper/ route
marked open positions at ohlcv_bars' latest close -- frozen at 2026-09-15 --
so a fresh XLM position showed a -19% paper loss that never happened. The
worker now records the mark it used here; the route reads it instead of
the vault. Append-only by convention (same treatment as paper_findings).

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_marks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("bar_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "marked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_paper_marks_symbol_marked_at", "paper_marks", ["symbol", "marked_at"])


def downgrade() -> None:
    op.drop_index("ix_paper_marks_symbol_marked_at", table_name="paper_marks")
    op.drop_table("paper_marks")

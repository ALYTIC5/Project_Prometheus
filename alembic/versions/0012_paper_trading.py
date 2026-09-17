"""paper_orders + paper_findings + worker_cadence -- PROMPT 8's Harbour

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-17

`paper_orders`: mutable current-state table, same exemption as
`strategies.status`/`jobs` -- a fill UPDATEs the same row, it is not an
event log.

`paper_findings`: INSERT-only by convention, same precedent as
`research_violations` (migration 0008) and `ablation_trials`
(migration 0011) -- a measurement record, not a decision history, so
not added to Law 6's append-only trigger set (matches those two).
Column names (`finding_type`, `detail`, `detected_at`) deliberately
mirror `research_violations`'s existing shape rather than inventing new
names for the same concept.

`worker_cadence`: scheduling state for worker.py's cadence-gated
concerns (ingest hourly / research 30min / paper 15min from one
tightened */15 cron) -- mutable, like strategies.status, not a log.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("strategy_id", sa.String(16), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("exchange_order_id", sa.String(64), nullable=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric(28, 8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="SUBMITTED"),
        sa.Column("expected_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("expected_qty", sa.Numeric(28, 8), nullable=False),
        sa.Column("filled_qty", sa.Numeric(28, 8), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_paper_orders_strategy_id", "paper_orders", ["strategy_id"])
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])

    op.create_table(
        "paper_findings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(16), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("finding_type", sa.String(32), nullable=False),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_paper_findings_strategy_id", "paper_findings", ["strategy_id"])

    op.create_table(
        "worker_cadence",
        sa.Column("concern", sa.String(16), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_cadence")
    op.drop_index("ix_paper_findings_strategy_id", table_name="paper_findings")
    op.drop_table("paper_findings")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_strategy_id", table_name="paper_orders")
    op.drop_table("paper_orders")

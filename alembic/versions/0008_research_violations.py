"""research_violations -- Law 7 detection

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16

INSERT-only by convention (prometheus/experiments/violations.py never
UPDATEs or DELETEs a row here), but not added to migration 0003's trigger
set -- that trigger names exactly experiments/results/decisions, and this
table postdates it; adding new tables to an existing law's enforcement
list is exactly the kind of change Law 7 itself is suspicious of doing
quietly. A violation record is inherently a finding about something that
already happened and is never corrected in place, which is why the
convention is enough here without a DB-level trigger.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_violations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("violation_type", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.String(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_research_violations_experiment_id", "research_violations", ["experiment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_research_violations_experiment_id", table_name="research_violations")
    op.drop_table("research_violations")

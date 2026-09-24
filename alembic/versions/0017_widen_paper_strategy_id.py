"""paper_orders.strategy_id / paper_findings.strategy_id VARCHAR(16) ->
unbounded VARCHAR, matching the strategies.id column they reference.

core.ids.next_strategy_id produces `{FAMILY}-{NNNNNN}`: EMA_CROSSOVER-000123
is 20 chars, VOL_OF_VOL_FILTER-000001 is 24. Only MOMENTUM/BOLLINGER-length
families fit in 16. Latent until now because no non-MOMENTUM strategy has
ever reached CHAMPION (the 2026-09-24 signal-strength fix is what lets
them); the first long-named champion's first paper order would have hit
StringDataRightTruncation inside worker._run_paper -- the same bug class
migration 0015 already fixed once for strategies.family.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("paper_orders", "paper_findings"):
        op.alter_column(
            table,
            "strategy_id",
            type_=sa.String(),
            existing_type=sa.String(16),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in ("paper_orders", "paper_findings"):
        op.alter_column(
            table,
            "strategy_id",
            type_=sa.String(16),
            existing_type=sa.String(),
            existing_nullable=False,
        )

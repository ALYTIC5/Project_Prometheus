"""evaluator.holdout_verdicts -- the one-shot vault test (Law 3).

One row per spec (config_hash UNIQUE): the single test of a gate discovery
on bars it has never seen (holdout_start onward, warm-up from research
bars). Append-only (Law 6 trigger). Lives in the evaluator schema, so the
research role cannot read or write it (Law 9, migration 0024).

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holdout_verdicts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("config_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("strategy_id", sa.String, nullable=False),
        sa.Column("window_start", sa.Date, nullable=True),
        sa.Column("window_end", sa.Date, nullable=True),
        sa.Column("n_observations", sa.Integer, nullable=False),
        sa.Column("p_value", sa.Float, nullable=True),
        sa.Column("excess_return_pct", sa.Float, nullable=True),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="evaluator",
    )
    op.execute(
        """
        CREATE TRIGGER holdout_verdicts_append_only
        BEFORE UPDATE OR DELETE ON evaluator.holdout_verdicts
        FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER holdout_verdicts_append_only_truncate
        BEFORE TRUNCATE ON evaluator.holdout_verdicts
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
        """
    )


def downgrade() -> None:
    op.drop_table("holdout_verdicts", schema="evaluator")

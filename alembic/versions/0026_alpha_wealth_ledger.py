"""evaluator.alpha_wealth_ledger -- every LORD++ discovery-gate test.

One row per test (Law 10): the p-value, the threshold it faced, whether it
was a discovery, and alpha-wealth before and after. One test per spec
(config_hash UNIQUE), test indices unique and gap-free by construction.
Lives in the evaluator schema (the research role has no access) and is
append-only (Law 6 trigger from 0003): nobody may reset, top up or reorder
it.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alpha_wealth_ledger",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("test_index", sa.Integer, nullable=False, unique=True),
        sa.Column("config_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("p_value", sa.Float, nullable=False),
        sa.Column("alpha_threshold", sa.Float, nullable=False),
        sa.Column("discovery", sa.Boolean, nullable=False),
        sa.Column("wealth_before", sa.Float, nullable=False),
        sa.Column("wealth_after", sa.Float, nullable=False),
        sa.Column("n_observations", sa.Integer, nullable=False),
        sa.Column("excess_sharpe_per_period", sa.Float, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("p_value >= 0 AND p_value <= 1", name="ck_alpha_ledger_p_value"),
        sa.CheckConstraint("alpha_threshold >= 0", name="ck_alpha_ledger_threshold"),
        sa.CheckConstraint("test_index >= 1", name="ck_alpha_ledger_index"),
        schema="evaluator",
    )
    op.execute(
        """
        CREATE TRIGGER alpha_wealth_ledger_append_only
        BEFORE UPDATE OR DELETE ON evaluator.alpha_wealth_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER alpha_wealth_ledger_append_only_truncate
        BEFORE TRUNCATE ON evaluator.alpha_wealth_ledger
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
        """
    )


def downgrade() -> None:
    op.drop_table("alpha_wealth_ledger", schema="evaluator")

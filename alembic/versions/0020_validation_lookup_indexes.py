"""Indexes for the per-strategy "latest experiment / latest score" lookups.

research/population.py's _LATEST_FINGERPRINT_CTE (used by elect_champions and
every selection mode) does, for every strategy, DISTINCT ON over experiments
by strategy_id and a LATERAL "latest validation_results row for this
config_hash". Neither validation_results.strategy_fingerprint nor
experiments.strategy_id/config_hash was indexed, so each lateral probe was a
sequential scan. Harmless at a few thousand rows; with ~441k experiments
(most from the 2026-09-24 retry churn) one elect_champions call ran for
tens of minutes, and it runs after every validate batch -- a single research
cycle's validation took 3.8 hours (found 2026-09-25 from worker timing logs;
the query was confirmed to hang in isolation, while the per-spec lookups it
sits beside returned in <0.05s).

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_validation_results_fingerprint_created",
        "validation_results",
        ["strategy_fingerprint", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_experiments_strategy_created",
        "experiments",
        ["strategy_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_experiments_config_hash_created",
        "experiments",
        ["config_hash", sa.text("created_at DESC")],
    )
    op.create_index("ix_strategies_status", "strategies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_strategies_status", table_name="strategies")
    op.drop_index("ix_experiments_config_hash_created", table_name="experiments")
    op.drop_index("ix_experiments_strategy_created", table_name="experiments")
    op.drop_index("ix_validation_results_fingerprint_created", table_name="validation_results")

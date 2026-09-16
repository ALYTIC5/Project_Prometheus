"""lineage and reproducibility columns on experiments; config_snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16

Every new experiments column is nullable. Migration 0003's trigger forbids
UPDATE on experiments, so rows written before this migration can never be
backfilled -- they read as lineage roots (parent_experiment_id IS NULL),
which is true: they recorded no parent. Every column a new INSERT can and
should populate is added here as one migration, not one column at a time,
because each later ALTER would itself be a permanent nullable gap in the
history this table is supposed to be.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("parent_experiment_id", sa.String(), nullable=True))
    op.add_column("experiments", sa.Column("strategy_id", sa.String(), nullable=True))
    op.add_column("experiments", sa.Column("data_version_hash", sa.String(64), nullable=True))
    op.add_column("experiments", sa.Column("code_sha", sa.String(40), nullable=True))
    op.add_column("experiments", sa.Column("config_hash", sa.String(64), nullable=True))
    op.add_column("experiments", sa.Column("seed", sa.BigInteger(), nullable=True))
    op.add_column("experiments", sa.Column("compute_cost", sa.Float(), nullable=True))
    op.add_column("experiments", sa.Column("hypothesis", sa.Text(), nullable=True))
    op.add_column("experiments", sa.Column("change_set", JSONB, nullable=True))

    op.create_foreign_key(
        "fk_experiments_parent_experiment_id",
        "experiments",
        "experiments",
        ["parent_experiment_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_experiments_strategy_id", "experiments", "strategies", ["strategy_id"], ["id"]
    )
    # Descendant lookups (WHERE parent_experiment_id = :id) are the hot path
    # for lineage.py's recursive CTE; the ancestor direction walks one row
    # at a time off the primary key and needs no index of its own.
    op.create_index(
        "ix_experiments_parent_experiment_id", "experiments", ["parent_experiment_id"]
    )

    # The substrate experiments/violations.py's UNIVERSE_CHANGED_AFTER_RESULTS
    # detector needs: one row per distinct content of a tracked config file,
    # written by runner.run_one via ON CONFLICT DO NOTHING so re-running with
    # an unchanged file never duplicates. Not trigger-protected -- a snapshot
    # table's job is deduplicated presence, not an event log.
    op.create_table(
        "config_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_config_snapshots_path_hash",
        "config_snapshots",
        ["path", "content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_config_snapshots_path_hash", table_name="config_snapshots")
    op.drop_table("config_snapshots")

    op.drop_index("ix_experiments_parent_experiment_id", table_name="experiments")
    op.drop_constraint("fk_experiments_strategy_id", "experiments", type_="foreignkey")
    op.drop_constraint(
        "fk_experiments_parent_experiment_id", "experiments", type_="foreignkey"
    )

    op.drop_column("experiments", "change_set")
    op.drop_column("experiments", "hypothesis")
    op.drop_column("experiments", "compute_cost")
    op.drop_column("experiments", "seed")
    op.drop_column("experiments", "config_hash")
    op.drop_column("experiments", "code_sha")
    op.drop_column("experiments", "data_version_hash")
    op.drop_column("experiments", "strategy_id")
    op.drop_column("experiments", "parent_experiment_id")

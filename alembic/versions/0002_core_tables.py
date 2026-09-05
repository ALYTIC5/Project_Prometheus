"""core tables: experiments, results, decisions, policy_versions, id_counters

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String, sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String, sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("decision", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_yaml", sa.Text, nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "id_counters",
        sa.Column("scope", sa.String, primary_key=True),
        sa.Column("next_value", sa.BigInteger, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("id_counters")
    op.drop_table("policy_versions")
    op.drop_table("decisions")
    op.drop_table("results")
    op.drop_table("experiments")

"""ablation_trials.version / component_registry.version VARCHAR(32) -> 64.

worker._run_ablation passes version=code_sha(), which in production is the
full 40-character git SHA (GIT_SHA / RAILWAY_GIT_COMMIT_SHA). Every
component's registration hit StringDataRightTruncation, so the ablation
verdicts (the "is this mechanism actually helping" evidence) were never
recorded -- found 2026-09-25 via the worker_health ERROR logs. 64 covers a
SHA-256 as well as a SHA-1.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_TABLES = ("ablation_trials", "component_registry")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table, "version", type_=sa.String(64), existing_type=sa.String(32),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table, "version", type_=sa.String(32), existing_type=sa.String(64),
            existing_nullable=False,
        )

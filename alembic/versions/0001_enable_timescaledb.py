"""enable timescaledb extension

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS timescaledb;")

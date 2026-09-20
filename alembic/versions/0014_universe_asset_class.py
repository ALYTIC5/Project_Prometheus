"""universe_membership.asset_class -- Law 2's as_of() must be able to
reconstruct one asset class's universe without mixing in another's.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-20

DEFAULT 'crypto' exists only to backfill every existing row (all of
today's universe_membership is crypto) without a manual data migration
step; dropped immediately after so future inserts must specify it
explicitly -- same "no invented default that silently hides a real
decision" posture as next_strategy_id's explicit family validation.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "universe_membership",
        sa.Column("asset_class", sa.String(16), nullable=False, server_default="crypto"),
    )
    op.alter_column("universe_membership", "asset_class", server_default=None)


def downgrade() -> None:
    op.drop_column("universe_membership", "asset_class")

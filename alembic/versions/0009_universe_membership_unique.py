"""unique constraint on universe_membership for idempotent yaml sync

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16

data/universe.py's sync_from_yaml() upserts one row per (symbol, exchange,
listed_at) -- re-syncing after a symbol is delisted must UPDATE that row's
delisted_at, never insert a second row for the same listing, or as_of()'s
"delisted_at IS NULL" branch would keep reporting the symbol alive forever
through the stale first row. This constraint is what makes ON CONFLICT
target a real thing.
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_universe_membership_symbol_exchange_listed_at",
        "universe_membership",
        ["symbol", "exchange", "listed_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_universe_membership_symbol_exchange_listed_at",
        "universe_membership",
        type_="unique",
    )

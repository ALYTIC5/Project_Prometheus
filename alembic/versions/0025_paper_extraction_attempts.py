"""paper_extractions: one row per ATTEMPT, not per paper.

0023 keyed paper_extractions on paper_id so a paper could be marked
processed exactly once. On 2026-09-26 every production extraction came
back as ```json-fenced text the parser rejected, so 68 papers were marked
unparseable and could never be retried. The table stays append-only; it
now gets a surrogate key so a paper whose only attempts were unparseable
can be tried again (the worker caps attempts).

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-26
"""
from __future__ import annotations

import os

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("paper_extractions_pkey", "paper_extractions", type_="primary")
    op.add_column(
        "paper_extractions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), nullable=False),
    )
    op.create_primary_key("paper_extractions_pkey", "paper_extractions", ["id"])
    op.create_index("ix_paper_extractions_paper_id", "paper_extractions", ["paper_id"])
    role = os.environ.get("RESEARCH_DB_ROLE")
    if role:
        op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')


def downgrade() -> None:
    op.drop_index("ix_paper_extractions_paper_id", table_name="paper_extractions")
    op.drop_constraint("paper_extractions_pkey", "paper_extractions", type_="primary")
    op.drop_column("paper_extractions", "id")
    op.create_primary_key("paper_extractions_pkey", "paper_extractions", ["paper_id"])

"""paper knowledge: claims extracted from each paper, their concepts, and
typed links between claims across papers.

paper_extractions marks a paper as processed (including papers that yielded
no claims) so extraction runs exactly once per paper. llm_hypotheses gains
claim_ids so every hypothesis traces back to the claims it tested.
All four new tables are append-only (Law 6 trigger from 0003): a changed
understanding of a paper is a new row, never an edit.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-26
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_APPEND_ONLY = ("paper_extractions", "paper_claims", "claim_concepts", "claim_links")
_RELATIONS = ("SUPPORTS", "CONTRADICTS", "EXTENDS", "SAME_MECHANISM")


def upgrade() -> None:
    op.create_table(
        "paper_extractions",
        sa.Column(
            "paper_id", sa.BigInteger, sa.ForeignKey("research_papers.id"), primary_key=True
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("n_claims", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "paper_claims",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "paper_id", sa.BigInteger, sa.ForeignKey("research_papers.id"), nullable=False
        ),
        sa.Column("mechanism", sa.Text, nullable=False),
        sa.Column("asset_class", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("stated_effect", sa.Text, nullable=False),
        sa.Column("data_period", sa.Text, nullable=False),
        sa.Column("testable", sa.Boolean, nullable=False),
        sa.Column("family_hint", sa.String(64), nullable=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_paper_claims_paper_id", "paper_claims", ["paper_id"])
    op.create_table(
        "claim_concepts",
        sa.Column(
            "claim_id", sa.BigInteger, sa.ForeignKey("paper_claims.id"), primary_key=True
        ),
        sa.Column("concept", sa.String(64), primary_key=True),
    )
    op.create_index("ix_claim_concepts_concept", "claim_concepts", ["concept"])
    op.create_table(
        "claim_links",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("claim_a", sa.BigInteger, sa.ForeignKey("paper_claims.id"), nullable=False),
        sa.Column("claim_b", sa.BigInteger, sa.ForeignKey("paper_claims.id"), nullable=False),
        sa.Column("relation", sa.String(24), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "relation IN (" + ", ".join(f"'{r}'" for r in _RELATIONS) + ")",
            name="ck_claim_links_relation",
        ),
        sa.CheckConstraint("claim_a <> claim_b", name="ck_claim_links_distinct"),
        sa.UniqueConstraint("claim_a", "claim_b", name="uq_claim_links_pair"),
    )
    op.create_index("ix_claim_links_claim_b", "claim_links", ["claim_b"])
    op.add_column("llm_hypotheses", sa.Column("claim_ids", JSONB, nullable=True))

    for table in _APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
            """
        )


def downgrade() -> None:
    op.drop_column("llm_hypotheses", "claim_ids")
    op.drop_index("ix_claim_links_claim_b", table_name="claim_links")
    op.drop_table("claim_links")
    op.drop_index("ix_claim_concepts_concept", table_name="claim_concepts")
    op.drop_table("claim_concepts")
    op.drop_index("ix_paper_claims_paper_id", table_name="paper_claims")
    op.drop_table("paper_claims")
    op.drop_table("paper_extractions")

"""research_papers + llm_hypotheses + llm_usage -- PROMPT 9's LLM research
layer.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-18

All three tables are insert-only by construction (nothing here is ever
UPDATEd) -- same exemption precedent as `ablation_trials`/
`research_violations`, not added to migration 0003's append-only trigger
set (that set names exactly experiments/results/decisions).

`llm_hypotheses.strategy_fingerprint` is `StrategySpec.config_hash()`, NOT
a `strategies.id` foreign key -- at the moment a hypothesis is generated,
its spec has only been enqueued as a run_backtest job (same as an
evolution child), not yet turned into a `Strategy` row. Same reasoning
`validation_results.strategy_fingerprint` already established: the real
join path, once a `Strategy` row exists, is strategies -> its latest
experiment -> that experiment's own config_hash column.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_papers",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("arxiv_id", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("abstract", sa.Text, nullable=False),
        sa.Column("full_text", sa.Text, nullable=False),
        sa.Column("key_sections", sa.Text, nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "llm_hypotheses",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy_fingerprint", sa.String(64), nullable=False),
        sa.Column("paper_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("hypothesis_text", sa.Text, nullable=False),
        sa.Column("expected_effect", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("est_cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_llm_hypotheses_strategy_fingerprint", "llm_hypotheses", ["strategy_fingerprint"]
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("est_cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_llm_hypotheses_strategy_fingerprint", table_name="llm_hypotheses")
    op.drop_table("llm_hypotheses")
    op.drop_table("research_papers")

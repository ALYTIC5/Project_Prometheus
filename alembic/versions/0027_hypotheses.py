"""hypotheses: every backtest is a pre-registered hypothesis (Phase 3).

Written before the job that runs the backtest exists: source, mechanism,
the prediction, the frozen parameter point, the matched benchmark, and the
generator's prior probability of passing the discovery gate. One row per
spec (config_hash UNIQUE -- the first registration is THE pre-registration;
a later generator proposing the same spec cannot restate it). Append-only
(Law 6 trigger from 0003).

hypothesis_gate_stats gives per-source test/discovery COUNTS from the
alpha-wealth ledger for the Laplace priors. It runs with its owner's
privileges, so the research role can read the counts without being able to
read the evaluator schema itself.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-28
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_GATE_STATS = """
CREATE OR REPLACE VIEW hypothesis_gate_stats AS
SELECT h.source,
       count(l.id) AS tests,
       count(l.id) FILTER (WHERE l.discovery) AS discoveries
  FROM hypotheses h
  LEFT JOIN evaluator.alpha_wealth_ledger l ON l.config_hash = h.config_hash
 GROUP BY h.source
"""


def upgrade() -> None:
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("config_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("parent_config_hash", sa.String(64), nullable=True),
        sa.Column("mechanism", sa.Text, nullable=False),
        sa.Column("mechanism_class", sa.String(32), nullable=False),
        sa.Column("predicted_direction", sa.String(32), nullable=False),
        sa.Column("predicted_effect", sa.Text, nullable=True),
        sa.Column("predicted_horizon", sa.Integer, nullable=False),
        sa.Column("parameters", JSONB, nullable=False),
        sa.Column("benchmark", JSONB, nullable=False),
        sa.Column("prior_probability", sa.Float, nullable=False),
        sa.Column("prior_basis", sa.String(32), nullable=False),
        sa.Column("near_duplicate_of", sa.String(64), nullable=True),
        sa.Column("mechanism_aligned", sa.Boolean, nullable=False),
        sa.Column("claim_ids", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "prior_probability > 0 AND prior_probability < 1", name="ck_hypotheses_prior"
        ),
    )
    op.create_index(
        "ix_hypotheses_family_symbol", "hypotheses", ["family", "symbol", "timeframe"]
    )
    op.execute(
        """
        CREATE TRIGGER hypotheses_append_only
        BEFORE UPDATE OR DELETE ON hypotheses
        FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER hypotheses_append_only_truncate
        BEFORE TRUNCATE ON hypotheses
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(_GATE_STATS)
    role = os.environ.get("RESEARCH_DB_ROLE")
    if role:
        op.execute(f'GRANT SELECT, INSERT ON hypotheses TO "{role}"')
        op.execute(f'GRANT SELECT ON hypothesis_gate_stats TO "{role}"')
        op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hypothesis_gate_stats")
    op.drop_index("ix_hypotheses_family_symbol", table_name="hypotheses")
    op.drop_table("hypotheses")

"""ICIR parent fitness, LLM failure refinement, options snapshots.

- breedable_scores gains `icir` (validation_results.metrics->>'icir') so
  parent selection can rank by consistency instead of the composite score.
- breedable_evidence: the latest validation evidence (verdict, reason codes,
  ICIR, IC by horizon, excess return/Sharpe, PBO, DSR) of every canary-free
  PROMISING/EXPERIMENTAL strategy -- what the LLM refinement step reads to
  learn why a strategy failed. Deliberately omits metrics.discovery_gate
  (evaluator state) and runs with its owner's privileges, so the research
  role reads it without any grant on validation_results itself (Law 9).
- llm_hypotheses.parent_config_hash: which strategy a refinement refined,
  so a failed refinement is never billed twice.
- options_daily: one row per (underlying, quote date, expiry) of CBOE
  delayed-quote chain aggregates. Append-only (Law 6); available_at is the
  fetch time (Law 1).

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-28
"""
from __future__ import annotations

import os

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_LATEST_EXPERIMENT = """
WITH latest_experiment AS (
    SELECT DISTINCT ON (e.strategy_id) e.strategy_id, e.config_hash
      FROM experiments e
     WHERE e.strategy_id IN (
         SELECT id FROM breedable_strategies
          WHERE status IN ({statuses})
     )
     ORDER BY e.strategy_id, e.created_at DESC
)
"""

_BREEDABLE_SCORES_V2 = (
    "CREATE OR REPLACE VIEW breedable_scores AS\n"
    + _LATEST_EXPERIMENT.format(statuses="'VALIDATED', 'CHAMPION', 'PROMISING'")
    + """
SELECT le.strategy_id, vr.score, vr.icir
  FROM latest_experiment le
  JOIN LATERAL (
      SELECT score, (metrics->>'icir')::float AS icir FROM validation_results
       WHERE strategy_fingerprint = le.config_hash
       ORDER BY created_at DESC LIMIT 1
  ) vr ON true
"""
)

# 0024's definition, restored on downgrade (a column cannot be dropped from
# a view with CREATE OR REPLACE).
_BREEDABLE_SCORES_V1 = (
    "CREATE VIEW breedable_scores AS\n"
    + _LATEST_EXPERIMENT.format(statuses="'VALIDATED', 'CHAMPION', 'PROMISING'")
    + """
SELECT le.strategy_id, vr.score
  FROM latest_experiment le
  JOIN LATERAL (
      SELECT score FROM validation_results
       WHERE strategy_fingerprint = le.config_hash
       ORDER BY created_at DESC LIMIT 1
  ) vr ON true
"""
)

_BREEDABLE_EVIDENCE = (
    "CREATE OR REPLACE VIEW breedable_evidence AS\n"
    + _LATEST_EXPERIMENT.format(statuses="'PROMISING', 'EXPERIMENTAL'")
    + """
SELECT le.strategy_id, le.config_hash, s.family, s.spec, s.status,
       vr.verdict, vr.score, vr.reason_codes, vr.pbo, vr.deflated_sharpe,
       (vr.metrics->>'icir')::float AS icir,
       vr.metrics->'decay'->'ic_by_horizon' AS ic_by_horizon,
       (vr.metrics->>'excess_return')::float AS excess_return,
       (vr.metrics->>'excess_sharpe')::float AS excess_sharpe,
       vr.created_at AS validated_at
  FROM latest_experiment le
  JOIN breedable_strategies s ON s.id = le.strategy_id
  JOIN LATERAL (
      SELECT verdict, score, reason_codes, pbo, deflated_sharpe, metrics, created_at
        FROM validation_results
       WHERE strategy_fingerprint = le.config_hash
       ORDER BY created_at DESC LIMIT 1
  ) vr ON true
"""
)


def upgrade() -> None:
    op.execute(_BREEDABLE_SCORES_V2)
    op.execute(_BREEDABLE_EVIDENCE)
    op.add_column(
        "llm_hypotheses", sa.Column("parent_config_hash", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_llm_hypotheses_parent_config_hash", "llm_hypotheses", ["parent_config_hash"]
    )

    op.create_table(
        "options_daily",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("underlying", sa.String(16), nullable=False),
        sa.Column("quote_date", sa.Date, nullable=False),
        sa.Column("expiry", sa.Date, nullable=False),
        sa.Column("spot", sa.Float, nullable=False),
        sa.Column("call_volume", sa.Float, nullable=False),
        sa.Column("put_volume", sa.Float, nullable=False),
        sa.Column("call_oi", sa.Float, nullable=False),
        sa.Column("put_oi", sa.Float, nullable=False),
        sa.Column("call_premium", sa.Float, nullable=False),
        sa.Column("put_premium", sa.Float, nullable=False),
        sa.Column("atm_strike", sa.Float, nullable=True),
        sa.Column("atm_call_iv", sa.Float, nullable=True),
        sa.Column("atm_put_iv", sa.Float, nullable=True),
        sa.Column("n_contracts", sa.Integer, nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "underlying", "quote_date", "expiry", name="uq_options_daily_underlying_date_expiry"
        ),
    )
    op.execute(
        """
        CREATE TRIGGER options_daily_append_only
        BEFORE UPDATE OR DELETE ON options_daily
        FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER options_daily_append_only_truncate
        BEFORE TRUNCATE ON options_daily
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
        """
    )

    role = os.environ.get("RESEARCH_DB_ROLE")
    if role:
        op.execute(f'GRANT SELECT ON breedable_evidence TO "{role}"')
        op.execute(f'GRANT SELECT ON breedable_scores TO "{role}"')


def downgrade() -> None:
    op.drop_table("options_daily")
    op.drop_index("ix_llm_hypotheses_parent_config_hash", table_name="llm_hypotheses")
    op.drop_column("llm_hypotheses", "parent_config_hash")
    op.execute("DROP VIEW IF EXISTS breedable_evidence")
    op.execute("DROP VIEW IF EXISTS breedable_scores")
    op.execute(_BREEDABLE_SCORES_V1)
    role = os.environ.get("RESEARCH_DB_ROLE")
    if role:
        op.execute(f'GRANT SELECT ON breedable_scores TO "{role}"')

"""research DB role, evaluator schema, and canary-free breeding views.

Law 9 (the evaluator is out of reach): research/generation code gets its
own non-superuser login role that can read only what research needs --
papers, claims, its own hypotheses and spend, public ablation verdicts,
and the breeding views -- and can write only research inputs (papers,
claims, hypotheses, usage, queued jobs). It has no privilege on
strategies, experiments, results, decisions, validation_results or any
other judging table, and no access to the evaluator or holdout schemas.
Same caveat as 0010: the app's own Railway user is a superuser, so this
isolation holds for code paths that connect as RESEARCH_DATABASE_URL.

The evaluator schema holds what research must never see: which specs are
canaries (known-null strategies injected blind), which strategy rows ran
as canaries, canary breaches, and promotion halts. The last three are
append-only (Law 6 trigger from 0003).

breedable_strategies / breedable_scores are the ONLY way research code
sees the population. They exclude canary rows inside the view, which runs
with its owner's privileges, so the research role can read them without
being able to read the registry -- and without SELECT on strategies it
cannot diff the view against the full table to find the canaries.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-26
"""
from __future__ import annotations

import os

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_RESEARCH_READ = (
    "research_papers", "paper_extractions", "paper_claims", "claim_concepts",
    "claim_links", "llm_hypotheses", "llm_usage", "component_registry", "jobs",
    "id_counters", "breedable_strategies", "breedable_scores",
)
_RESEARCH_INSERT = (
    "research_papers", "paper_extractions", "paper_claims", "claim_concepts",
    "claim_links", "llm_hypotheses", "llm_usage", "jobs", "id_counters",
)
_RESEARCH_UPDATE = ("id_counters",)
_EVALUATOR_APPEND_ONLY = ("canary_strategies", "canary_breaches", "promotion_halts")

_BREEDABLE_STRATEGIES = """
CREATE OR REPLACE VIEW breedable_strategies AS
SELECT s.id, s.family, s.spec, s.status, s.created_at
  FROM strategies s
 WHERE NOT EXISTS (
       SELECT 1 FROM evaluator.canary_strategies c WHERE c.strategy_id = s.id
 )
"""

# Latest validation score for promoted strategies only -- the same scoping
# population.py's latest-fingerprint CTE uses, for the same reason (an
# unscoped walk over every strategy ever created took hours).
_BREEDABLE_SCORES = """
CREATE OR REPLACE VIEW breedable_scores AS
WITH latest_experiment AS (
    SELECT DISTINCT ON (e.strategy_id) e.strategy_id, e.config_hash
      FROM experiments e
     WHERE e.strategy_id IN (
         SELECT id FROM breedable_strategies
          WHERE status IN ('VALIDATED', 'CHAMPION', 'PROMISING')
     )
     ORDER BY e.strategy_id, e.created_at DESC
)
SELECT le.strategy_id, vr.score
  FROM latest_experiment le
  JOIN LATERAL (
      SELECT score FROM validation_results
       WHERE strategy_fingerprint = le.config_hash
       ORDER BY created_at DESC LIMIT 1
  ) vr ON true
"""


def _create_role_if_missing(role: str, password: str) -> None:
    """Verbatim pattern from 0010 -- see its comments for why format() and
    CAST(... AS text)."""
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if exists:
        return
    ddl = conn.execute(
        sa.text(
            "SELECT format("
            "'CREATE ROLE %I LOGIN PASSWORD %L', CAST(:role AS text), CAST(:pw AS text)"
            ")"
        ),
        {"role": role, "pw": password},
    ).scalar_one()
    conn.execute(sa.text(ddl))


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS evaluator")
    op.execute("REVOKE ALL ON SCHEMA evaluator FROM PUBLIC")
    op.create_table(
        "canary_registry",
        sa.Column("config_hash", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_config_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="evaluator",
    )
    op.create_table(
        "canary_strategies",
        sa.Column("strategy_id", sa.String, primary_key=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="evaluator",
    )
    op.create_table(
        "canary_breaches",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String, nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("attempted_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="evaluator",
    )
    op.create_table(
        "promotion_halts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("event IN ('HALT', 'CLEAR')", name="ck_promotion_halts_event"),
        schema="evaluator",
    )
    for table in _EVALUATOR_APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON evaluator.{table}
            FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only_truncate
            BEFORE TRUNCATE ON evaluator.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
            """
        )

    op.execute(_BREEDABLE_STRATEGIES)
    op.execute(_BREEDABLE_SCORES)

    role = os.environ["RESEARCH_DB_ROLE"]
    _create_role_if_missing(role, os.environ["RESEARCH_DB_PASSWORD"])
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
    for table in _RESEARCH_READ:
        op.execute(f'GRANT SELECT ON {table} TO "{role}"')
    for table in _RESEARCH_INSERT:
        op.execute(f'GRANT INSERT ON {table} TO "{role}"')
    for table in _RESEARCH_UPDATE:
        op.execute(f'GRANT UPDATE ON {table} TO "{role}"')


def downgrade() -> None:
    role = os.environ.get("RESEARCH_DB_ROLE")
    if role:
        exists = op.get_bind().execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).first()
        if exists:
            op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{role}"')
            op.execute(f'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM "{role}"')
            op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
    op.execute("DROP VIEW IF EXISTS breedable_scores")
    op.execute("DROP VIEW IF EXISTS breedable_strategies")
    op.drop_table("promotion_halts", schema="evaluator")
    op.drop_table("canary_breaches", schema="evaluator")
    op.drop_table("canary_strategies", schema="evaluator")
    op.drop_table("canary_registry", schema="evaluator")
    op.execute("DROP SCHEMA IF EXISTS evaluator")

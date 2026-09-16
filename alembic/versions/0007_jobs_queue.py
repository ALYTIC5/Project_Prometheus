"""jobs and jobs_dead_letter -- the Postgres SKIP LOCKED job queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

Deliberately NOT added to migration 0003's append-only trigger set (which
names exactly experiments/results/decisions): a job's status, attempts and
progress_pct are current execution state, not a history log, and are meant
to be UPDATEd as that state changes -- same reasoning migration 0005 gives
for `strategies.status`. The permanent record of a job that exhausted its
retries is jobs_dead_letter, which is INSERT-only by convention (nothing
in prometheus/experiments/queue.py ever updates or deletes from it).

status has exactly three values. "failed" is not a resting state: a failed
job is either re-queued as pending with a future run_at, or moved to
jobs_dead_letter -- so nothing is ever counted as pending work that will
never run, which is what makes structures[].queue_depth in the world view
honest.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        # No server_default on priority/expected_information_value/
        # estimated_cost/max_attempts -- CLAUDE.md: inventing numeric
        # thresholds is how the previous blueprint went wrong. The caller
        # (prometheus.experiments.queue.enqueue) requires all four.
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("expected_information_value", sa.Float, nullable=False),
        sa.Column("estimated_cost", sa.Float, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        # The Agent(role, from_location, to_location, progress) shape
        # world/entities.py already defines -- see world/projection.py's
        # agents=[] with its "jobs table does not exist until Prompt 4"
        # comment, and docs/WORLD_MAPPING.md's reservation of this table.
        sa.Column("agent_role", sa.String(16), nullable=False),
        sa.Column("current_stage", sa.String(16), nullable=False),
        sa.Column("next_stage", sa.String(16), nullable=False),
        sa.Column("progress_pct", sa.Float, nullable=False, server_default="0"),
        sa.Column("experiment_id", sa.String(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('pending', 'claimed', 'succeeded')", name="ck_jobs_status"),
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 1", name="ck_jobs_progress_range"
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND attempts >= 0 AND attempts <= max_attempts",
            name="ck_jobs_attempts_bound",
        ),
        sa.CheckConstraint(
            "(status <> 'claimed') OR (claimed_by IS NOT NULL AND heartbeat_at IS NOT NULL)",
            name="ck_jobs_claim_invariant",
        ),
    )
    op.create_index(
        "uq_jobs_idempotency_key", "jobs", ["idempotency_key"], unique=True
    )
    # The claim query's entire WHERE/ORDER BY in one partial index, so
    # claiming is a bounded scan over pending rows only -- see
    # experiments/queue.py's claim() docstring for the exact statement.
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["priority", "expected_information_value", "run_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_stage_pending",
        "jobs",
        ["current_stage"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_reaper",
        "jobs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'claimed'"),
    )

    op.create_table(
        "jobs_dead_letter",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("experiment_id", sa.String(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("last_error", sa.Text, nullable=False),
        sa.Column(
            "died_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("jobs_dead_letter")
    op.drop_index("ix_jobs_reaper", table_name="jobs")
    op.drop_index("ix_jobs_stage_pending", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_index("uq_jobs_idempotency_key", table_name="jobs")
    op.drop_table("jobs")

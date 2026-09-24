"""worker_health -- Step 4's minimal monitoring (2026-09-24). "The
smallest thing that would have caught both bugs on day one": the
_fast/_slow IC bug (this session) and migration 0015's VARCHAR(16)
family-truncation bug before it were BOTH only ever `print()`ed to
stdout, with no counter, no persisted record, and no alert -- the print
scrolled off Railway's log retention and nobody looked until the symptom
(nothing evolving / three families never producing a backtest) was
noticed independently, days later.

One row per (cycle, concern, exception_type) that actually failed --
`prometheus/core/health.py`'s record_failure()/flush_cycle() write this,
called from every except-Exception isolation boundary in worker.py and
the per-spec validate loops in experiments/runner.py that used to only
print(). A measurement record, not a decision history -- same INSERT-
only-by-convention precedent as `paper_findings`/`research_violations`
(not added to Law 6's append-only trigger set, matching those two).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_health",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cycle_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concern", sa.String(32), nullable=False),
        sa.Column("exception_type", sa.String(128), nullable=False),
        sa.Column("failure_count", sa.Integer, nullable=False),
        sa.Column("sample_message", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_worker_health_cycle_started_at", "worker_health", ["cycle_started_at"])
    op.create_index("ix_worker_health_concern", "worker_health", ["concern"])


def downgrade() -> None:
    op.drop_index("ix_worker_health_concern", table_name="worker_health")
    op.drop_index("ix_worker_health_cycle_started_at", table_name="worker_health")
    op.drop_table("worker_health")

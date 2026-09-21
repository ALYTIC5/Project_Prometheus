"""strategies.family VARCHAR(16) -> VARCHAR(32) -- three families shipped
in migration-adjacent code (GRADIENT_BOOSTING, 18 chars; LOGISTIC_REGRESSION,
20 chars; AWESOME_OSCILLATOR, 19 chars) exceed the old 16-char cap.
experiments/runner.py's run_one() does `Strategy(family=spec.family, ...)`
then session.flush() -- every job for these 3 families has been hitting
Postgres's StringDataRightTruncation on every attempt since deployment,
caught by drain_queue's per-job except Exception (so it never crashed the
worker), retried to max_attempts, then dead-lettered. validate_specs then
silently skips them forever (`if row is None: continue  # run_one hasn't
recorded this spec yet`) since no Experiment row was ever written. Net
effect: these 3 families have never produced one successful backtest in
production.

32 chars also gives headroom for upcoming cross-sectional rotation family
names (e.g. SECTOR_MOMENTUM_ROTATION, 24 chars).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-21
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "strategies",
        "family",
        type_=sa.String(32),
        existing_type=sa.String(16),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "strategies",
        "family",
        type_=sa.String(16),
        existing_type=sa.String(32),
        existing_nullable=False,
    )

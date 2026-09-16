"""ablation_trials + component_registry -- PROMPT 6's ablation harness

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16

`ablation_trials`: one row per paired A/B trial (component enabled vs
disabled, same symbol/spec/seed/costs). INSERT-only by convention, same
precedent as `research_violations` (migration 0008) -- a measurement
record, not a decision history, so not added to Law 6's append-only
trigger set.

`component_registry`: current aggregate state per (component, version),
recomputed from `ablation_trials` after every batch -- same mutability
exemption as `strategies.status`/`jobs` (current state, not a log).
Table name matches the frontend's own already-written contract
(frontend/src/mapping/stateToVisual.ts's `ComponentVerdict`/
`mapComponentVerdictToVisual`, and world/construction.py's temple entry
now points `activates_on` here instead of the placeholder "ablation"
string it held before this migration).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ablation_trials",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column("enabled_return_pct", sa.Float, nullable=False),
        sa.Column("disabled_return_pct", sa.Float, nullable=False),
        sa.Column("enabled_sharpe", sa.Float, nullable=True),
        sa.Column("disabled_sharpe", sa.Float, nullable=True),
        sa.Column("enabled_total_costs", sa.Float, nullable=False),
        sa.Column("disabled_total_costs", sa.Float, nullable=False),
        sa.Column("compute_cost_delta", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ablation_trials_component_version",
        "ablation_trials",
        ["component", "version"],
    )

    op.create_table(
        "component_registry",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("families_affected", JSONB, nullable=False, server_default="[]"),
        sa.Column("n_experiments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mean_oos_improvement", sa.Float, nullable=True),
        sa.Column("median_oos_improvement", sa.Float, nullable=True),
        sa.Column("worst_oos_improvement", sa.Float, nullable=True),
        sa.Column("best_oos_improvement", sa.Float, nullable=True),
        sa.Column("ci_low", sa.Float, nullable=True),
        sa.Column("ci_high", sa.Float, nullable=True),
        # "sharpe" or "return_pct" -- which unit mean/median/worst/best/
        # ci_low/ci_high are IN. Decided once per batch, never mixed
        # within one CI (sharpe when every trial's both arms cleared
        # cpz-quant's 30-observation floor, return_pct otherwise) -- this
        # column is what makes the registry row self-describing instead
        # of leaving the reader to guess the unit.
        sa.Column("metric", sa.String(16), nullable=True),
        sa.Column("mean_cost_delta", sa.Float, nullable=True),
        sa.Column("mean_compute_cost_delta", sa.Float, nullable=True),
        sa.Column("failure_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(16), nullable=False, server_default="UNPROVEN"),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("component", "version", name="uq_component_registry_component_version"),
    )


def downgrade() -> None:
    op.drop_table("component_registry")
    op.drop_index("ix_ablation_trials_component_version", table_name="ablation_trials")
    op.drop_table("ablation_trials")

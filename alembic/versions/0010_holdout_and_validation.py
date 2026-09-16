"""holdout schema + restricted role, holdout_access_log, validation_results

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16

Law 3: "the final test slice is physically separated... access audited...
a strategy may touch it once. Second access = automatic REJECT." This is
the first migration in the repo to do role/schema-level DDL (0001/0003 are
the only prior op.execute() users; neither touches roles or schemas).

Two real caveats, found by actually checking the target database before
writing this rather than assuming:

1. Railway provisions this app's own DB user as a Postgres SUPERUSER.
   Superusers bypass every GRANT/REVOKE, so revoking SELECT on the holdout
   schema from the app's own role would be a no-op against the app's
   actual connection -- there is nothing here pretending otherwise. What
   IS real: HOLDOUT_DB_ROLE is a genuinely separate, non-superuser
   credential, SELECT-only on the holdout schema and nothing else, and
   prometheus/validation/holdout.py's access_holdout() is the only code
   path in the application that ever authenticates as it. See
   docs/DEFERRED.md for the residual gap (a different code path could
   still use the superuser app credential to read holdout.ohlcv_bars
   directly) and what closing it would take.
2. `holdout_access_log` deliberately breaks migration 0008's precedent of
   not extending Law 6's append-only trigger set to new tables -- an
   audit log that can be edited after the fact is not an audit log, which
   is a strong enough reason to extend the set this one time. detail
   documented here, not silently.

Idempotent: safe to re-run against an environment where the role/schema
already exist (Railway redeploys re-run `alembic upgrade head` every
deploy, not just once).
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_HOLDOUT_OHLCV_COLUMNS = (
    ("symbol", "VARCHAR(32) NOT NULL"),
    ("timeframe", "VARCHAR(8) NOT NULL"),
    ("event_time", "TIMESTAMPTZ NOT NULL"),
    ("available_at", "TIMESTAMPTZ NOT NULL"),
    ("ingested_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("source", "VARCHAR(32) NOT NULL"),
    ("revision", "INTEGER NOT NULL DEFAULT 1"),
    ("open", "NUMERIC(20, 8) NOT NULL"),
    ("high", "NUMERIC(20, 8) NOT NULL"),
    ("low", "NUMERIC(20, 8) NOT NULL"),
    ("close", "NUMERIC(20, 8) NOT NULL"),
    ("volume", "NUMERIC(28, 8) NOT NULL"),
)


def _create_role_if_missing(role: str, password: str) -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if exists:
        return
    # DDL takes no bind params, so let Postgres's own format() build the
    # statement (%I/%L are injection-safe identifier/literal quoting) and
    # run the *result* as a second statement -- the password itself is
    # still passed as a real bind param, never string-interpolated.
    # CAST(... AS text): format()'s VARIADIC "any" signature leaves an
    # untyped bind param's data type ambiguous to Postgres
    # ("could not determine data type of parameter $1") -- caught by
    # actually running this migration against real Postgres, not by any
    # offline check, same class of bug as this project's earlier JSONB-
    # bindparam fixes. `:role::text` (no space before `::`) was tried
    # first and silently left un-substituted -- SQLAlchemy's text()
    # bindparam tokenizer doesn't split a param name from an immediately
    # adjacent `::` cast -- CAST(... AS ...) has no such ambiguity.
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
    op.create_table(
        "holdout_access_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("strategy_fingerprint", sa.String(64), nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_holdout_access_log_fingerprint", "holdout_access_log", ["strategy_fingerprint"]
    )

    op.create_table(
        "validation_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("strategy_fingerprint", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("reason_codes", JSONB, nullable=False, server_default="[]"),
        sa.Column("pbo", sa.Float, nullable=True),
        sa.Column("deflated_sharpe", sa.Float, nullable=True),
        sa.Column("metrics", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_validation_results_experiment_id", "validation_results", ["experiment_id"]
    )

    # Law 6 extension -- see module docstring point 2.
    op.execute(
        """
        CREATE TRIGGER holdout_access_log_append_only
        BEFORE UPDATE OR DELETE ON holdout_access_log
        FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER holdout_access_log_append_only_truncate
        BEFORE TRUNCATE ON holdout_access_log
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
        """
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS holdout")
    columns_sql = ",\n            ".join(f"{name} {ddl}" for name, ddl in _HOLDOUT_OHLCV_COLUMNS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS holdout.ohlcv_bars (
            id BIGSERIAL PRIMARY KEY,
            {columns_sql},
            CONSTRAINT uq_holdout_ohlcv_bar_revision
                UNIQUE (symbol, timeframe, event_time, revision)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_holdout_ohlcv_bars_available_at "
        "ON holdout.ohlcv_bars (available_at)"
    )

    role = os.environ["HOLDOUT_DB_ROLE"]
    password = os.environ["HOLDOUT_DB_PASSWORD"]
    _create_role_if_missing(role, password)
    conn = op.get_bind()
    conn.execute(sa.text(f'GRANT USAGE ON SCHEMA holdout TO "{role}"'))
    conn.execute(sa.text(f'GRANT SELECT ON holdout.ohlcv_bars TO "{role}"'))
    # Any table added to the holdout schema later is readable by the
    # restricted role without a follow-up migration remembering to grant it.
    conn.execute(
        sa.text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA holdout GRANT SELECT ON TABLES TO "{role}"')
    )


def downgrade() -> None:
    # The role itself is intentionally NOT dropped: DROP ROLE fails outright
    # if it owns anything else in the cluster, and a login role is exactly
    # the kind of object other migrations/config should not have to worry
    # about being yanked out from under a live credential.
    role = os.environ.get("HOLDOUT_DB_ROLE")
    if role:
        conn = op.get_bind()
        conn.execute(
            sa.text(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA holdout FROM "{role}"')
        )
        conn.execute(sa.text(f'REVOKE USAGE ON SCHEMA holdout FROM "{role}"'))
    op.execute("DROP SCHEMA IF EXISTS holdout CASCADE")

    op.execute(
        "DROP TRIGGER IF EXISTS holdout_access_log_append_only_truncate ON holdout_access_log"
    )
    op.execute("DROP TRIGGER IF EXISTS holdout_access_log_append_only ON holdout_access_log")

    op.drop_index("ix_validation_results_experiment_id", table_name="validation_results")
    op.drop_table("validation_results")
    op.drop_index("ix_holdout_access_log_fingerprint", table_name="holdout_access_log")
    op.drop_table("holdout_access_log")

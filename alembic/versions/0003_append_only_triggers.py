"""append-only enforcement on experiments, results, decisions (Law 6)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLES = ("experiments", "results", "decisions")

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION prevent_history_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'LAW VIOLATION: % on % is forbidden — history is append-only (Law 6)',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_TRIGGER_FN)
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
            """
        )
    # Row-level triggers do not fire on TRUNCATE, so the loop above alone
    # would leave `TRUNCATE experiments, results, decisions CASCADE;` as a
    # silent, complete bypass of Law 6. TRUNCATE triggers must be
    # statement-level. prevent_history_mutation() needs no change: TG_OP
    # reports 'TRUNCATE' and the existing message format handles it.
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION prevent_history_mutation();
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_truncate ON {table};")
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS prevent_history_mutation();")

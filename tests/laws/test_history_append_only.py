"""Law 6: history is append-only. UPDATE, DELETE and TRUNCATE on
experiments, results, decisions raise — enforced by real Postgres
triggers, not application code, per the migration in
alembic/versions/0003_*. TRUNCATE needs its own statement-level trigger:
row-level triggers do not fire on it.

Requires a live Postgres with migrations applied. Skipped (not xfail —
this is missing infrastructure, not missing code) when TEST_DATABASE_URL
isn't set. CI provides it via a postgres service container.

WARNING: rows inserted by the fixtures below accumulate forever — the
append-only trigger forbids the DELETE that would clean them up. That is
harmless against CI's ephemeral per-run Postgres service container, but
would grow without bound if TEST_DATABASE_URL ever pointed at a
long-lived shared database.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0003 applied)",
)


@pytest.fixture()
def engine():
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture()
def experiment_id(engine) -> str:
    # Conforms to prometheus.core.ids.EXPERIMENT_ID_RE (^EXP-\d{4}-\d{6}$).
    # Year 9999 marks it as fixture data and can never collide with a real year.
    exp_id = f"EXP-9999-{uuid.uuid4().int % 1_000_000:06d}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO experiments (id, status) VALUES (:id, 'pending')"),
            {"id": exp_id},
        )
    return exp_id


def test_update_experiments_raises(engine, experiment_id: str) -> None:
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"), engine.begin() as conn:
        conn.execute(
            text("UPDATE experiments SET status = 'changed' WHERE id = :id"),
            {"id": experiment_id},
        )


def test_delete_experiments_raises(engine, experiment_id: str) -> None:
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"), engine.begin() as conn:
        conn.execute(text("DELETE FROM experiments WHERE id = :id"), {"id": experiment_id})


@pytest.mark.parametrize("table", ["results", "decisions"])
def test_update_child_tables_raises(engine, experiment_id: str, table: str) -> None:
    value_col = "payload" if table == "results" else "decision"
    with engine.begin() as conn:
        row_id = conn.execute(
            text(
                f"INSERT INTO {table} (experiment_id, {value_col}) "
                f"VALUES (:eid, '{{}}'::jsonb) RETURNING id"
            ),
            {"eid": experiment_id},
        ).scalar_one()
    with (
        pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"),
        engine.begin() as conn,
    ):
        conn.execute(
            text(f"UPDATE {table} SET {value_col} = CAST(:new_value AS jsonb) WHERE id = :id"),
            {"new_value": '{"x": 1}', "id": row_id},
        )


@pytest.mark.parametrize("table", ["results", "decisions"])
def test_delete_child_tables_raises(engine, experiment_id: str, table: str) -> None:
    value_col = "payload" if table == "results" else "decision"
    with engine.begin() as conn:
        row_id = conn.execute(
            text(
                f"INSERT INTO {table} (experiment_id, {value_col}) "
                f"VALUES (:eid, '{{}}'::jsonb) RETURNING id"
            ),
            {"eid": experiment_id},
        ).scalar_one()
    with (
        pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"),
        engine.begin() as conn,
    ):
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})


# TRUNCATE is not covered by the row-level BEFORE UPDATE OR DELETE trigger —
# it needs the separate statement-level BEFORE TRUNCATE trigger added in
# migration 0003. CASCADE is used deliberately: Postgres checks the
# foreign-key truncate restriction before firing BEFORE TRUNCATE triggers,
# so a bare `TRUNCATE experiments` would fail on the FK check rather than on
# the law. CASCADE is also the form that actually destroys the corpus.
@pytest.mark.parametrize("table", ["experiments", "results", "decisions"])
def test_truncate_raises(engine, experiment_id: str, table: str) -> None:
    with (
        pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"),
        engine.begin() as conn,
    ):
        conn.execute(text(f"TRUNCATE {table} CASCADE"))


def test_truncate_all_history_tables_in_one_statement_raises(
    engine, experiment_id: str
) -> None:
    """The specific whole-corpus bypass: one statement, all three tables."""
    with (
        pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"),
        engine.begin() as conn,
    ):
        conn.execute(text("TRUNCATE experiments, results, decisions CASCADE"))

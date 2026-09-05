"""Law 6: history is append-only. UPDATE and DELETE on experiments,
results, decisions raise — enforced by a real Postgres trigger, not
application code, per the migration in alembic/versions/0003_*.

Requires a live Postgres with migrations applied. Skipped (not xfail —
this is missing infrastructure, not missing code) when TEST_DATABASE_URL
isn't set. CI provides it via a postgres service container.
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
    exp_id = f"EXP-TEST-{uuid.uuid4().hex[:8]}"
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
            text(f"UPDATE {table} SET {value_col} = '{{\"x\":1}}'::jsonb WHERE id = :id"),
            {"id": row_id},
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

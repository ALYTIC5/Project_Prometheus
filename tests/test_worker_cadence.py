import pytest
from sqlalchemy import text

from prometheus.worker import is_due, mark_run

pytestmark = [pytest.mark.db]


async def test_is_due_true_when_no_prior_run(db_session):
    assert await is_due(db_session, concern="test_concern_1", interval_seconds=900) is True


async def test_is_due_false_immediately_after_mark_run(db_session):
    await mark_run(db_session, concern="test_concern_2")
    assert await is_due(db_session, concern="test_concern_2", interval_seconds=900) is False


async def test_is_due_true_after_interval_elapses(db_session):
    await db_session.execute(
        text(
            "INSERT INTO worker_cadence (concern, last_run_at) "
            "VALUES ('test_concern_3', now() - interval '20 minutes')"
        )
    )
    await db_session.commit()
    assert await is_due(db_session, concern="test_concern_3", interval_seconds=900) is True

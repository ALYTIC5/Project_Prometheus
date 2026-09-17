"""Test paper order ID generation.

Paper order IDs follow the same per-day scoping and 6-digit headroom as
job IDs -- PAPER-YYYYMMDD-NNNNNN. A live champion polling every 15 minutes
can plausibly submit or re-check many orders a day.
"""
from __future__ import annotations

import os
import re
from datetime import date

import pytest

from prometheus.core.ids import next_paper_order_id

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0012 applied)",
    ),
]


@pytest.fixture(autouse=True)
def _setup_database_url() -> None:
    """Ensure DATABASE_URL is set from TEST_DATABASE_URL for get_engine().

    next_paper_order_id() calls get_engine() internally, which reads
    DATABASE_URL from the environment. This fixture sets it up for test
    execution and cleans up afterwards.
    """
    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    try:
        yield
    finally:
        if old_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_db_url


async def test_next_paper_order_id_format() -> None:
    order_id = await next_paper_order_id(day=date(2026, 9, 17))
    assert re.match(r"^PAPER-20260917-\d{6}$", order_id)


async def test_next_paper_order_id_increments() -> None:
    first = await next_paper_order_id(day=date(2026, 9, 18))
    second = await next_paper_order_id(day=date(2026, 9, 18))
    assert first != second

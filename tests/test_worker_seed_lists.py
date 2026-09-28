"""The one-time curated-list seed against a real database: it stores the
papers it finds, writes its completion marker, and does nothing on the
next run. Production 2026-09-26..28: a 36-character marker overflowed
worker_cadence.concern (varchar(16)), the marker never saved, and the seed
re-ran and broke paper ingestion on every tick."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from prometheus.core.db import get_session
from prometheus.research.llm.seed_lists import SeedPaper
from prometheus.worker import _SEED_LIST_MARKER, _run_seed_lists

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("RESEARCH_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL and RESEARCH_DATABASE_URL",
    ),
]


def test_marker_fits_worker_cadence_concern_column() -> None:
    assert len(_SEED_LIST_MARKER) <= 16


async def test_seed_stores_found_papers_writes_marker_and_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    async with get_session() as session:
        await session.execute(
            text("DELETE FROM worker_cadence WHERE concern = :c"), {"c": _SEED_LIST_MARKER}
        )
        await session.commit()
    paper_id = f"doi:10.9/{uuid.uuid4().hex[:12]}"
    found = SeedPaper(paper_id, "The Investment CAPM", "an abstract")
    find = AsyncMock(side_effect=[found, None])

    with (
        patch("prometheus.worker.fetch_readme", new=AsyncMock(return_value="")),
        patch("prometheus.worker.strategy_titles", return_value=["The Investment CAPM", "Other"]),
        patch("prometheus.worker.find_paper", new=find),
        patch("prometheus.worker._ARXIV_CALL_SPACING_SECONDS", 0.0),
    ):
        first = await _run_seed_lists()
        second = await _run_seed_lists()

    assert first == 1
    assert second == 0
    assert find.await_count == 2  # the second run did no lookups at all
    async with get_session() as session:
        stored = (
            await session.execute(
                text("SELECT abstract FROM research_papers WHERE arxiv_id = :a"), {"a": paper_id}
            )
        ).scalar_one()
        marker = (
            await session.execute(
                text("SELECT 1 FROM worker_cadence WHERE concern = :c"), {"c": _SEED_LIST_MARKER}
            )
        ).first()
    assert stored == "an abstract"
    assert marker is not None

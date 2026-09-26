"""tests/test_worker_paper_knowledge.py -- the worker's paper-knowledge
step against a real database with a fake Anthropic client."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.worker import _run_paper_knowledge

pytestmark = pytest.mark.db


def _message(payload: Any) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock(type="text", text=payload)]
    message.stop_reason = "end_turn"
    message.usage.input_tokens = 400
    message.usage.output_tokens = 300
    return message


def _fake_client() -> MagicMock:
    claim = {
        "mechanism": "Underreaction makes trends persist.",
        "asset_class": "equity", "horizon": "monthly", "direction": "long_short",
        "stated_effect": "positive spread", "data_period": "1990-2020",
        "testable": True, "family_hint": "TSMOM", "concepts": ["momentum"],
    }

    def create(**kwargs: Any) -> MagicMock:
        user = kwargs["messages"][0]["content"]
        if "EXISTING claims" not in user:
            return _message(json.dumps({"claims": [claim]}))
        target = int(re.search(r"EXISTING claims:\n(\d+)\.", user).group(1))  # type: ignore[union-attr]
        return _message(
            json.dumps(
                {"links": [{"id": target, "relation": "SUPPORTS", "rationale": "same result"}]}
            )
        )

    client = MagicMock()
    client.messages.create.side_effect = create
    return client


async def _insert_paper(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text(
                    "INSERT INTO research_papers "
                    "(arxiv_id, title, abstract, full_text, key_sections) "
                    "VALUES (:a, 't', 'momentum abstract', '', 'momentum abstract') RETURNING id"
                ),
                {"a": f"test.{uuid.uuid4().hex[:10]}"},
            )
        ).scalar_one()
    )


async def test_paper_knowledge_extracts_claims_and_links_across_papers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAPERS_PER_DAY", "200")
    await db_session.execute(
        text(
            "INSERT INTO paper_extractions (paper_id, model, n_claims) "
            "SELECT p.id, 'test-preexisting', 0 FROM research_papers p "
            "LEFT JOIN paper_extractions e ON e.paper_id = p.id WHERE e.paper_id IS NULL"
        )
    )
    first = await _insert_paper(db_session)
    second = await _insert_paper(db_session)
    client = _fake_client()
    usage_sql = text(
        "SELECT purpose, count(*) FROM llm_usage "
        "WHERE purpose IN ('paper_extraction', 'claim_linking') GROUP BY purpose"
    )
    before = dict((await db_session.execute(usage_sql)).all())

    with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")):
        papers, claims, links = await _run_paper_knowledge(db_session, client=client)

    assert (papers, claims, links) == (2, 2, 1)
    link = (
        await db_session.execute(
            text(
                "SELECT a.paper_id AS pa, b.paper_id AS pb, l.relation FROM claim_links l "
                "JOIN paper_claims a ON a.id = l.claim_a JOIN paper_claims b ON b.id = l.claim_b "
                "WHERE a.paper_id IN (:first, :second)"
            ),
            {"first": first, "second": second},
        )
    ).one()
    assert (link.pa, link.pb, link.relation) == (first, second, "SUPPORTS")
    after = dict((await db_session.execute(usage_sql)).all())
    assert after.get("paper_extraction", 0) - before.get("paper_extraction", 0) == 2
    assert after.get("claim_linking", 0) - before.get("claim_linking", 0) == 1


async def test_unparseable_extraction_is_logged_and_not_retried(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAPERS_PER_DAY", "200")
    await db_session.execute(
        text(
            "INSERT INTO paper_extractions (paper_id, model, n_claims) "
            "SELECT p.id, 'test-preexisting', 0 FROM research_papers p "
            "LEFT JOIN paper_extractions e ON e.paper_id = p.id WHERE e.paper_id IS NULL"
        )
    )
    paper_id = await _insert_paper(db_session)
    client = MagicMock()
    client.messages.create.return_value = _message("not json")

    with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")):
        first_run = await _run_paper_knowledge(db_session, client=client)
        second_run = await _run_paper_knowledge(db_session, client=client)

    assert first_run == (1, 0, 0)
    assert second_run == (0, 0, 0)
    marker = (
        await db_session.execute(
            text("SELECT model FROM paper_extractions WHERE paper_id = :p"), {"p": paper_id}
        )
    ).scalar_one()
    assert marker.endswith(":unparseable")

"""The worker's research steps run as migration 0024's research role:
ingest -> extract -> link -> hypothesis -> enqueued job, with every write
permitted by the role's grants (Law 9 positive case). Commits real rows,
like the other role tests; CI's database is fresh per run."""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from prometheus.core.db import get_research_session
from prometheus.research.llm.hypothesis import LLMHypothesis
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import _run_llm_hypothesis_step, _run_paper_knowledge

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("RESEARCH_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL and RESEARCH_DATABASE_URL",
    ),
]


def _message(payload: str) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock(type="text", text=payload)]
    message.stop_reason = "end_turn"
    message.usage.input_tokens = 100
    message.usage.output_tokens = 100
    return message


def _client(marker: str) -> MagicMock:
    claim = {
        "mechanism": f"trend persistence {marker}", "asset_class": "crypto",
        "horizon": "monthly", "direction": "long", "stated_effect": "e",
        "data_period": "d", "testable": True, "family_hint": "MOMENTUM",
        "concepts": [f"concept-{marker}"],
    }

    def create(**kwargs: Any) -> MagicMock:
        user = kwargs["messages"][0]["content"]
        if "EXISTING claims" not in user:
            return _message(json.dumps({"claims": [claim]}))
        target = int(re.search(r"EXISTING claims:\n(\d+)\.", user).group(1))  # type: ignore[union-attr]
        return _message(
            json.dumps({"links": [{"id": target, "relation": "SUPPORTS", "rationale": "r"}]})
        )

    client = MagicMock()
    client.messages.create.side_effect = create
    return client


async def test_research_role_can_run_the_whole_paper_to_job_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAPERS_PER_DAY", "200")
    marker = uuid.uuid4().hex[:8]
    async with get_research_session() as session:
        # Only this test's papers are unprocessed.
        await session.execute(
            text(
                "INSERT INTO paper_extractions (paper_id, model, n_claims) "
                "SELECT p.id, 'test-preexisting', 0 FROM research_papers p "
                "LEFT JOIN paper_extractions e ON e.paper_id = p.id WHERE e.paper_id IS NULL"
            )
        )
        for i in range(2):
            await session.execute(
                text(
                    "INSERT INTO research_papers "
                    "(arxiv_id, title, abstract, full_text, key_sections) "
                    "VALUES (:a, 't', 'a', '', 'a')"
                ),
                {"a": f"role.{marker}.{i}"},
            )
        await session.commit()

        with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")):
            papers, claims, links = await _run_paper_knowledge(session, client=_client(marker))
        assert (papers, claims, links) == (2, 2, 1)

        spec = StrategySpec(
            family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
            fast_window=11, slow_window=47, expected_horizon=5,
            source="llm_hypothesis", description=f"role test {marker}",
        )
        hypothesis = LLMHypothesis(
            spec=spec, hypothesis_text="h", expected_effect="e", paper_ids=[1],
            model="claude-sonnet-5", input_tokens=10, output_tokens=10, est_cost_usd=0.001,
        )
        with (
            patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
            patch("prometheus.worker.generate_hypothesis", new=AsyncMock(return_value=hypothesis)),
        ):
            job_id = await _run_llm_hypothesis_step(session, client=MagicMock())
        await session.commit()

    assert job_id is not None

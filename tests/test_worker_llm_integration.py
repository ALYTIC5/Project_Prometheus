"""tests/test_worker_llm_integration.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.hypothesis import LLMHypothesis
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import _run_llm_hypothesis_step

pytestmark = pytest.mark.db


def _fake_hypothesis() -> LLMHypothesis:
    spec = StrategySpec(
        family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5,
        source="llm_hypothesis", description="test hypothesis",
    )
    return LLMHypothesis(
        spec=spec, hypothesis_text="test", expected_effect="test",
        paper_ids=[1], model="claude-sonnet-5",
        input_tokens=100, output_tokens=50, est_cost_usd=0.001,
    )


async def test_llm_step_enqueues_job_and_logs_usage_when_full_tier(
    db_session: AsyncSession,
) -> None:
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.model_for_tier", return_value="claude-sonnet-5"),
        patch("prometheus.worker.search_arxiv", new=AsyncMock(return_value=[])),
        patch("prometheus.worker._select_recent_papers", new=AsyncMock(return_value=[
            MagicMock(id=1, key_sections="momentum literature")
        ])),
        patch(
            "prometheus.worker.generate_hypothesis",
            new=AsyncMock(return_value=_fake_hypothesis()),
        ),
    ):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())

    assert job_id is not None
    usage_row = (
        await db_session.execute(
            text("SELECT model FROM llm_usage WHERE model = 'claude-sonnet-5'")
        )
    ).first()
    assert usage_row is not None
    hypothesis_row = (
        await db_session.execute(text("SELECT hypothesis_text FROM llm_hypotheses"))
    ).first()
    assert hypothesis_row is not None


async def test_llm_step_does_nothing_when_halted(db_session: AsyncSession) -> None:
    with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="halted")):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())
    assert job_id is None


async def test_llm_ingestion_calls_ingest_paper_for_each_search_result(
    db_session: AsyncSession,
) -> None:
    from contextlib import asynccontextmanager

    from prometheus.research.llm.ingestion import ArxivPaper
    from prometheus.worker import _run_llm_ingestion

    fake_paper = ArxivPaper(
        arxiv_id="2401.00099", title="Fake Paper", abstract="fake abstract",
        pdf_url="https://arxiv.org/pdf/2401.00099",
    )

    @asynccontextmanager
    async def _fake_get_session():
        # _run_llm_ingestion opens its own session via get_session()
        # (matching _run_ingest's shape, see the implementation below) --
        # patched here to hand it the test's own db_session so the
        # inserted rows are visible to assertions in the SAME
        # transaction, same technique this test file needs precisely
        # because that function takes no session parameter.
        yield db_session

    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch("prometheus.worker.search_arxiv", new=AsyncMock(return_value=[fake_paper])),
        patch("prometheus.worker.ingest_paper", new=AsyncMock(
            return_value=MagicMock(arxiv_id="2401.00099")
        )) as mock_ingest,
    ):
        ingested = await _run_llm_ingestion()

    assert ingested == ["2401.00099"]
    mock_ingest.assert_awaited_once_with(db_session, "2401.00099")

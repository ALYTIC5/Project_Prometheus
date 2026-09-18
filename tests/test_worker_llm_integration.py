"""tests/test_worker_llm_integration.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.hypothesis import LLMHypothesis, LLMResponseError
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import _enqueue_child, _run_llm_hypothesis_step

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


async def _idempotency_key_for_source(source: str) -> str:
    """Runs _enqueue_child with enqueue() patched out, so this exercises the
    real key derivation without needing a database."""
    spec = StrategySpec(
        family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5, source=source,
    )
    with patch("prometheus.worker.enqueue", new=AsyncMock(return_value="job-1")) as mock_enqueue:
        await _enqueue_child(
            MagicMock(), child=spec, parent_experiment_id=None,
            hypothesis="h", change_set={}, expected_information_value_=0.0,
        )
    key = mock_enqueue.await_args.kwargs["idempotency_key"]
    assert isinstance(key, str)
    return key


async def test_idempotency_key_separates_specs_by_source() -> None:
    """I1 (final-review fix wave): config_hash() excludes `source` by
    design (it identifies behavior, not provenance), so an LLM hypothesis
    landing on an existing grid point used to dedup straight into the
    grid's job -- no strategy row with source='llm_hypothesis' was ever
    created while Anthropic was billed anyway."""
    grid_key = await _idempotency_key_for_source("deterministic_grid")
    mutation_key = await _idempotency_key_for_source("mutation")
    llm_key = await _idempotency_key_for_source("llm_hypothesis")

    assert len({grid_key, mutation_key, llm_key}) == 3


async def test_idempotency_key_is_stable_for_the_same_source() -> None:
    """The dedup that matters is still intact: re-running the SAME
    generator on the same parameters produces the same key, so a mutation
    re-proposed next cycle does not create a duplicate job."""
    assert await _idempotency_key_for_source("mutation") == await _idempotency_key_for_source(
        "mutation"
    )


async def test_llm_step_logs_usage_even_when_the_response_is_invalid(
    db_session: AsyncSession,
) -> None:
    """I3 (final-review fix wave): the API call was billed before the
    response failed validation, so the spend MUST still reach llm_usage --
    otherwise the monthly budget cap systematically under-counts exactly
    the calls that produced nothing."""
    failure = LLMResponseError(
        "bad spec", input_tokens=4242, output_tokens=2121, model="claude-sonnet-5"
    )
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.model_for_tier", return_value="claude-sonnet-5"),
        patch("prometheus.worker._select_recent_papers", new=AsyncMock(return_value=[
            MagicMock(id=1, key_sections="momentum literature")
        ])),
        patch("prometheus.worker.generate_hypothesis", new=AsyncMock(side_effect=failure)),
    ):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())

    assert job_id is None
    usage_row = (
        await db_session.execute(
            text(
                "SELECT input_tokens, output_tokens, est_cost_usd FROM llm_usage "
                "WHERE input_tokens = 4242"
            )
        )
    ).first()
    assert usage_row is not None
    assert usage_row.output_tokens == 2121
    assert float(usage_row.est_cost_usd) > 0
    # No hypothesis record for a response that never produced a valid spec.
    hypothesis_row = (
        await db_session.execute(text("SELECT id FROM llm_hypotheses"))
    ).first()
    assert hypothesis_row is None


async def test_llm_step_commits_usage_before_enqueue_can_fail(
    db_session: AsyncSession,
) -> None:
    """I3: the usage row is committed in its OWN transaction, so a later
    failure (the llm_hypotheses insert, or _enqueue_child) can no longer
    roll back the record of money already spent."""
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.model_for_tier", return_value="claude-sonnet-5"),
        patch("prometheus.worker._select_recent_papers", new=AsyncMock(return_value=[
            MagicMock(id=1, key_sections="momentum literature")
        ])),
        patch(
            "prometheus.worker.generate_hypothesis",
            new=AsyncMock(return_value=_fake_hypothesis()),
        ),
        patch("prometheus.worker.enqueue", new=AsyncMock(side_effect=RuntimeError("queue down"))),
        pytest.raises(RuntimeError),
    ):
        await _run_llm_hypothesis_step(db_session, client=MagicMock())

    await db_session.rollback()
    usage_row = (
        await db_session.execute(
            text("SELECT model FROM llm_usage WHERE model = 'claude-sonnet-5'")
        )
    ).first()
    assert usage_row is not None


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

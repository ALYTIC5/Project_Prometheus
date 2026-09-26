"""tests/test_worker_llm_integration.py"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.hypothesis import LLMHypothesis, LLMResponseError, PaperContext
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import (
    _ClaimContext,
    _enqueue_child,
    _hypotheses_per_cycle,
    _next_untested_claim,
    _run_llm_hypothesis_step,
)

pytestmark = pytest.mark.db

_CLAIM = _ClaimContext(
    claim_id=7, symbol="BTC/USDT",
    paper=PaperContext(paper_id=1, key_sections="Claim under test: momentum"),
)


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
        patch("prometheus.worker._next_untested_claim", new=AsyncMock(return_value=_CLAIM)),
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
        patch("prometheus.worker._next_untested_claim", new=AsyncMock(return_value=_CLAIM)),
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
    # The failed attempt is recorded against its claim (so the claim is not
    # re-billed next cycle) but carries no strategy fingerprint.
    hypothesis_row = (
        await db_session.execute(
            text("SELECT strategy_fingerprint, claim_ids FROM llm_hypotheses")
        )
    ).one()
    assert hypothesis_row.strategy_fingerprint == "unparseable"
    assert hypothesis_row.claim_ids == [7]


async def test_llm_step_commits_usage_before_enqueue_can_fail(
    db_session: AsyncSession,
) -> None:
    """I3: the usage row is committed in its OWN transaction, so a later
    failure (the llm_hypotheses insert, or _enqueue_child) can no longer
    roll back the record of money already spent."""
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.model_for_tier", return_value="claude-sonnet-5"),
        patch("prometheus.worker._next_untested_claim", new=AsyncMock(return_value=_CLAIM)),
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


async def _paper_with_claim(
    session: AsyncSession, *, asset_class: str = "crypto", testable: bool = True
) -> int:
    import uuid

    paper_id = (
        await session.execute(
            text(
                "INSERT INTO research_papers (arxiv_id, title, abstract, full_text, key_sections) "
                "VALUES (:a, 'title', 'abstract', '', 'abstract') RETURNING id"
            ),
            {"a": f"test.{uuid.uuid4().hex[:10]}"},
        )
    ).scalar_one()
    return int(
        (
            await session.execute(
                text(
                    "INSERT INTO paper_claims (paper_id, mechanism, asset_class, horizon, "
                    "direction, stated_effect, data_period, testable, family_hint, model) "
                    "VALUES (:p, 'trend persists', :ac, 'monthly', 'long', 'e', 'd', :t, "
                    ":fh, 'x') RETURNING id"
                ),
                {"p": paper_id, "ac": asset_class, "t": testable,
                 "fh": "TSMOM" if testable else None},
            )
        ).scalar_one()
    )


async def _hide_existing_claims(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO llm_hypotheses (strategy_fingerprint, paper_ids, claim_ids, "
            "hypothesis_text, expected_effect, model, input_tokens, output_tokens, est_cost_usd) "
            "SELECT 'test-hidden', '[]'::jsonb, jsonb_build_array(c.id), '', '', 'x', 0, 0, 0 "
            "FROM paper_claims c"
        )
    )


async def test_next_untested_claim_prefers_supported_claims_and_skips_tested_ones(
    db_session: AsyncSession,
) -> None:
    await _hide_existing_claims(db_session)
    lonely = await _paper_with_claim(db_session)
    supported = await _paper_with_claim(db_session, asset_class="equity")
    supporter = await _paper_with_claim(db_session)
    await _paper_with_claim(db_session, testable=False)
    await _paper_with_claim(db_session, asset_class="other")
    await db_session.execute(
        text(
            "INSERT INTO claim_links (claim_a, claim_b, relation, rationale, model) "
            "VALUES (:a, :b, 'SUPPORTS', 'r', 'x')"
        ),
        {"a": supporter, "b": supported},
    )

    first = await _next_untested_claim(db_session)
    assert first is not None
    assert first.claim_id in (supported, supporter)
    assert first.symbol in ("SPY", "BTC/USDT")

    await db_session.execute(
        text(
            "INSERT INTO llm_hypotheses (strategy_fingerprint, paper_ids, claim_ids, "
            "hypothesis_text, expected_effect, model, input_tokens, output_tokens, est_cost_usd) "
            "VALUES ('f', '[]'::jsonb, CAST(:ids AS jsonb), '', '', 'x', 0, 0, 0)"
        ),
        {"ids": f"[{supported}, {supporter}]"},
    )
    remaining = await _next_untested_claim(db_session)
    assert remaining is not None and remaining.claim_id == lonely


async def test_hypotheses_per_cycle_is_one_until_llm_generation_is_valuable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_HYPOTHESES_PER_CYCLE", "4")
    await db_session.execute(
        text("DELETE FROM component_registry WHERE component = 'llm_generation'")
    )
    assert await _hypotheses_per_cycle(db_session) == 1

    await db_session.execute(
        text(
            "INSERT INTO component_registry (component, version, verdict) "
            "VALUES ('llm_generation', 'v-test', 'NEUTRAL')"
        )
    )
    assert await _hypotheses_per_cycle(db_session) == 1

    await db_session.execute(
        text(
            "INSERT INTO component_registry (component, version, verdict, updated_at) "
            "VALUES ('llm_generation', 'v-test-2', 'VALUABLE', now() + interval '1 second')"
        )
    )
    assert await _hypotheses_per_cycle(db_session) == 4


async def test_llm_step_does_nothing_when_halted(db_session: AsyncSession) -> None:
    with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="halted")):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())
    assert job_id is None


async def test_llm_ingestion_stores_new_search_results_abstract_only(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from prometheus.research.llm.ingestion import ArxivPaper
    from prometheus.worker import _run_llm_ingestion

    monkeypatch.setenv("PAPERS_PER_DAY", "200")
    fake_paper = ArxivPaper(
        arxiv_id="2401.00099v1", title="Fake Paper", abstract="fake abstract",
        pdf_url="https://arxiv.org/pdf/2401.00099v1",
    )

    @asynccontextmanager
    async def _fake_get_session():
        # _run_llm_ingestion opens its own session; hand it the test's
        # db_session so inserted rows are visible in the same transaction.
        yield db_session

    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch(
            "prometheus.worker.search_arxiv",
            new=AsyncMock(side_effect=[[fake_paper], []]),
        ),
        patch("prometheus.worker._ARXIV_CALL_SPACING_SECONDS", 0.0),
    ):
        ingested = await _run_llm_ingestion()

    assert ingested == ["2401.00099v1"]
    row = (
        await db_session.execute(
            text(
                "SELECT abstract, full_text, key_sections FROM research_papers "
                "WHERE arxiv_id = '2401.00099v1'"
            )
        )
    ).one()
    assert row.abstract == "fake abstract"
    assert row.full_text == ""
    assert row.key_sections == "fake abstract"


def _paper(arxiv_id: str) -> Any:
    from prometheus.research.llm.ingestion import ArxivPaper

    return ArxivPaper(
        arxiv_id=arxiv_id, title=f"t {arxiv_id}", abstract=f"a {arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def _fake_ingestion_session(known_ids: list[str], last_24h: int) -> MagicMock:
    session = MagicMock()
    known_result = MagicMock()
    known_result.scalars.return_value = iter(known_ids)
    count_result = MagicMock()
    count_result.scalar_one.return_value = last_24h
    session.execute = AsyncMock(side_effect=[known_result, count_result])
    session.commit = AsyncMock()
    return session


async def _run_ingestion_with(
    session: MagicMock, search: AsyncMock, papers_per_day: str,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    from contextlib import asynccontextmanager

    from prometheus.worker import _run_llm_ingestion

    monkeypatch.setenv("PAPERS_PER_DAY", papers_per_day)

    @asynccontextmanager
    async def _fake_get_session():
        yield session

    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch("prometheus.worker.search_arxiv", new=search),
        patch("prometheus.worker._ARXIV_CALL_SPACING_SECONDS", 0.0),
    ):
        return await _run_llm_ingestion()


async def test_llm_ingestion_skips_known_papers_across_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_ingestion_session(["2401.00001v1"], last_24h=0)
    search = AsyncMock(side_effect=[[_paper("2401.00001v2"), _paper("2401.00002v1")], []])

    ingested = await _run_ingestion_with(session, search, "200", monkeypatch)

    assert ingested == ["2401.00002v1"]
    assert session.add.call_count == 1


async def test_llm_ingestion_jumps_to_backlog_depth_once_newest_page_is_all_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known = [f"2401.{i:05d}v1" for i in range(250)]
    session = _fake_ingestion_session(known, last_24h=0)
    search = AsyncMock(
        side_effect=[[_paper("2401.00000v1")], [_paper("1901.00001v1")], []]
    )

    ingested = await _run_ingestion_with(session, search, "200", monkeypatch)

    assert ingested == ["1901.00001v1"]
    starts = [call.kwargs["start"] for call in search.await_args_list]
    assert starts[:2] == [0, 250]


async def test_llm_ingestion_respects_the_24h_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fake_ingestion_session([], last_24h=199)
    search = AsyncMock(side_effect=[[_paper("2401.00001v1"), _paper("2401.00002v1")]])

    ingested = await _run_ingestion_with(session, search, "200", monkeypatch)

    assert ingested == ["2401.00001v1"]


async def test_llm_ingestion_does_nothing_when_quota_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_ingestion_session([], last_24h=200)
    search = AsyncMock()

    ingested = await _run_ingestion_with(session, search, "200", monkeypatch)

    assert ingested == []
    search.assert_not_awaited()


async def test_llm_ingestion_spreads_the_daily_target_across_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_ingestion_session([], last_24h=0)
    page = [_paper(f"2401.{i:05d}v1") for i in range(100)]
    search = AsyncMock(side_effect=[page])

    ingested = await _run_ingestion_with(session, search, "200", monkeypatch)

    assert len(ingested) == 17  # ceil(200 / 12 two-hour runs)

"""The /research-papers queries on seeded data: links read from both
papers' side, and learned joins claim -> hypothesis -> strategy."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.api.routes.papers import _SELECT_LEARNED, _SELECT_PAPER_LINKS

pytestmark = pytest.mark.db


async def _paper_and_claim(session: AsyncSession) -> tuple[int, int]:
    paper_id = (
        await session.execute(
            text(
                "INSERT INTO research_papers (arxiv_id, title, abstract, full_text, key_sections) "
                "VALUES (:a, 'title', 'abstract', '', 'abstract') RETURNING id"
            ),
            {"a": f"test.{uuid.uuid4().hex[:10]}"},
        )
    ).scalar_one()
    claim_id = (
        await session.execute(
            text(
                "INSERT INTO paper_claims (paper_id, mechanism, asset_class, horizon, "
                "direction, stated_effect, data_period, testable, family_hint, model) "
                "VALUES (:p, 'trend', 'crypto', 'monthly', 'long', 'e', 'd', true, 'TSMOM', 'x') "
                "RETURNING id"
            ),
            {"p": paper_id},
        )
    ).scalar_one()
    return int(paper_id), int(claim_id)


async def test_links_are_visible_from_both_papers(db_session: AsyncSession) -> None:
    paper_a, claim_a = await _paper_and_claim(db_session)
    paper_b, claim_b = await _paper_and_claim(db_session)
    await db_session.execute(
        text(
            "INSERT INTO claim_links (claim_a, claim_b, relation, rationale, model) "
            "VALUES (:a, :b, 'CONTRADICTS', 'opposite sign', 'x')"
        ),
        {"a": claim_a, "b": claim_b},
    )

    from_a = (await db_session.execute(_SELECT_PAPER_LINKS, {"id": paper_a})).one()
    from_b = (await db_session.execute(_SELECT_PAPER_LINKS, {"id": paper_b})).one()

    assert (from_a.direction, from_a.claim_id, from_a.other_paper_id) == (
        "outgoing", claim_a, paper_b
    )
    assert (from_b.direction, from_b.claim_id, from_b.other_paper_id) == (
        "incoming", claim_b, paper_a
    )


async def test_learned_joins_claim_hypothesis_and_strategy(db_session: AsyncSession) -> None:
    paper_id, claim_id = await _paper_and_claim(db_session)
    fingerprint = uuid.uuid4().hex
    strategy_id = f"TSMOM-{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, 'TSMOM', CAST(:spec AS jsonb), 'REJECTED')"
        ),
        {"id": strategy_id, "spec": json.dumps({"source": "llm_hypothesis"})},
    )
    await db_session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:id, 'succeeded', '{}'::jsonb, :s, :h)"
        ),
        {"id": f"EXP-{uuid.uuid4().hex[:8]}", "s": strategy_id, "h": fingerprint},
    )
    await db_session.execute(
        text(
            "INSERT INTO llm_hypotheses (strategy_fingerprint, paper_ids, claim_ids, "
            "hypothesis_text, expected_effect, model, input_tokens, output_tokens, est_cost_usd) "
            "VALUES (:h, CAST(:p AS jsonb), CAST(:c AS jsonb), 'trend works', 'sharpe', 'x', "
            "1, 1, 0.0)"
        ),
        {"h": fingerprint, "p": f"[{paper_id}]", "c": f"[{claim_id}]"},
    )

    rows = (await db_session.execute(_SELECT_LEARNED, {"limit": 500})).all()
    mine = [r for r in rows if r.strategy_fingerprint == fingerprint]

    assert len(mine) == 1
    assert (mine[0].claim_id, mine[0].paper_id) == (claim_id, paper_id)
    assert (mine[0].strategy_id, mine[0].strategy_status) == (strategy_id, "REJECTED")

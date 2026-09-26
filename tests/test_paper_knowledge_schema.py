"""Migration 0023: paper claims, concepts and claim links are append-only
and hold only the four declared relation types."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db


async def _paper(session: AsyncSession) -> int:
    arxiv_id = f"test.{uuid.uuid4().hex[:10]}"
    return int(
        (
            await session.execute(
                text(
                    "INSERT INTO research_papers "
                    "(arxiv_id, title, abstract, full_text, key_sections) "
                    "VALUES (:a, 't', 'a', '', 'a') RETURNING id"
                ),
                {"a": arxiv_id},
            )
        ).scalar_one()
    )


async def _claim(session: AsyncSession, paper_id: int) -> int:
    return int(
        (
            await session.execute(
                text(
                    "INSERT INTO paper_claims (paper_id, mechanism, asset_class, horizon, "
                    "direction, stated_effect, data_period, testable, family_hint, model) "
                    "VALUES (:p, 'm', 'equity', 'monthly', 'long', 'e', 'd', true, NULL, 'x') "
                    "RETURNING id"
                ),
                {"p": paper_id},
            )
        ).scalar_one()
    )


async def test_paper_claims_reject_update(db_session: AsyncSession) -> None:
    claim_id = await _claim(db_session, await _paper(db_session))
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE paper_claims SET mechanism = 'x' WHERE id = :id"), {"id": claim_id}
            )


async def test_claim_links_reject_unknown_relations(db_session: AsyncSession) -> None:
    paper_id = await _paper(db_session)
    a, b = await _claim(db_session, paper_id), await _claim(db_session, paper_id)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO claim_links (claim_a, claim_b, relation, rationale, model) "
                    "VALUES (:a, :b, 'INSPIRES', 'r', 'x')"
                ),
                {"a": a, "b": b},
            )


async def test_claim_links_reject_self_links(db_session: AsyncSession) -> None:
    claim_id = await _claim(db_session, await _paper(db_session))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO claim_links (claim_a, claim_b, relation, rationale, model) "
                    "VALUES (:a, :a, 'SUPPORTS', 'r', 'x')"
                ),
                {"a": claim_id},
            )


async def test_llm_hypotheses_accepts_claim_ids(db_session: AsyncSession) -> None:
    columns = (
        await db_session.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'llm_hypotheses' AND column_name = 'claim_ids'"
            )
        )
    ).scalar_one()
    assert columns == "jsonb"

"""Research papers API -- the ingested papers, the claims extracted from
each one, the typed links between claims across papers, and what the
system has learned from them (which claims became hypotheses, and how the
resulting strategies fared). Read-only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/research-papers", tags=["research-papers"])

_SELECT_PAGE = text(
    """
    SELECT p.id, p.arxiv_id, p.title, p.abstract, p.ingested_at,
           e.n_claims, e.created_at AS extracted_at
      FROM research_papers p
      LEFT JOIN paper_extractions e ON e.paper_id = p.id
     ORDER BY p.ingested_at DESC, p.id DESC
     LIMIT :limit OFFSET :offset
    """
)
_COUNT_PAPERS = text("SELECT count(*) FROM research_papers")

_SELECT_SUMMARY = text(
    """
    SELECT
      (SELECT count(*) FROM research_papers) AS papers,
      (SELECT count(DISTINCT paper_id) FROM paper_extractions
        WHERE model NOT LIKE '%\\:unparseable' AND model <> 'relevance-filter')
        AS papers_extracted,
      (SELECT count(DISTINCT paper_id) FROM paper_extractions
        WHERE model = 'relevance-filter') AS papers_skipped_off_topic,
      (SELECT count(*) FROM paper_claims) AS claims,
      (SELECT count(*) FROM paper_claims WHERE testable) AS testable_claims,
      (SELECT count(*) FROM claim_links) AS links,
      (SELECT count(*) FROM llm_hypotheses WHERE claim_ids IS NOT NULL
                                           AND strategy_fingerprint <> 'unparseable')
        AS hypotheses_from_claims
    """
)
_SELECT_LINKS_BY_RELATION = text(
    "SELECT relation, count(*) AS n FROM claim_links GROUP BY relation"
)

_SELECT_PAPER = text(
    "SELECT id, arxiv_id, title, abstract, ingested_at FROM research_papers WHERE id = :id"
)
_SELECT_PAPER_CLAIMS = text(
    """
    SELECT c.id, c.mechanism, c.asset_class, c.horizon, c.direction, c.stated_effect,
           c.data_period, c.testable, c.family_hint,
           COALESCE(array_agg(cc.concept ORDER BY cc.concept)
                    FILTER (WHERE cc.concept IS NOT NULL), '{}') AS concepts
      FROM paper_claims c
      LEFT JOIN claim_concepts cc ON cc.claim_id = c.id
     WHERE c.paper_id = :id
     GROUP BY c.id
     ORDER BY c.id
    """
)
_SELECT_PAPER_LINKS = text(
    """
    SELECT l.relation, l.rationale,
           CASE WHEN a.paper_id = :id THEN 'outgoing' ELSE 'incoming' END AS direction,
           mine.id AS claim_id,
           other.id AS other_claim_id, other.mechanism AS other_mechanism,
           op.id AS other_paper_id, op.arxiv_id AS other_arxiv_id, op.title AS other_title
      FROM claim_links l
      JOIN paper_claims a ON a.id = l.claim_a
      JOIN paper_claims b ON b.id = l.claim_b
      JOIN paper_claims mine ON mine.id = CASE WHEN a.paper_id = :id THEN a.id ELSE b.id END
      JOIN paper_claims other ON other.id = CASE WHEN a.paper_id = :id THEN b.id ELSE a.id END
      JOIN research_papers op ON op.id = other.paper_id
     WHERE a.paper_id = :id OR b.paper_id = :id
     ORDER BY l.id
    """
)

# Claim -> hypothesis -> the llm_hypothesis strategy built from it, with its
# current status. A hypothesis whose backtest hasn't run yet has no strategy.
_SELECT_LEARNED = text(
    """
    SELECT h.id AS hypothesis_id, h.created_at, h.hypothesis_text, h.expected_effect,
           h.strategy_fingerprint,
           c.id AS claim_id, c.mechanism, c.asset_class, c.family_hint,
           p.id AS paper_id, p.arxiv_id, p.title,
           s.id AS strategy_id, s.status AS strategy_status
      FROM llm_hypotheses h
      CROSS JOIN LATERAL jsonb_array_elements_text(h.claim_ids) AS hc(claim_id)
      JOIN paper_claims c ON c.id = hc.claim_id::bigint
      JOIN research_papers p ON p.id = c.paper_id
      LEFT JOIN LATERAL (
            SELECT s.id, s.status
              FROM experiments e
              JOIN strategies s ON s.id = e.strategy_id
             WHERE e.config_hash = h.strategy_fingerprint
               AND s.spec->>'source' = 'llm_hypothesis'
             ORDER BY e.created_at DESC
             LIMIT 1
      ) s ON true
     WHERE h.strategy_fingerprint <> 'unparseable'
     ORDER BY h.created_at DESC
     LIMIT :limit
    """
)


@router.get("/")
async def list_research_papers(
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)
) -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                _SELECT_PAGE, {"limit": page_size, "offset": (page - 1) * page_size}
            )
        ).all()
        total = int((await session.execute(_COUNT_PAPERS)).scalar_one())
    papers = [
        {
            "id": r.id,
            "arxiv_id": r.arxiv_id,
            "title": r.title,
            "abstract": r.abstract,
            "ingested_at": r.ingested_at.isoformat(),
            "extracted": r.extracted_at is not None,
            "n_claims": r.n_claims,
        }
        for r in rows
    ]
    return {"papers": papers, "total": total, "page": page, "page_size": page_size}


@router.get("/summary")
async def research_summary() -> dict[str, Any]:
    async with get_session_factory()() as session:
        summary = (await session.execute(_SELECT_SUMMARY)).one()
        by_relation = (await session.execute(_SELECT_LINKS_BY_RELATION)).all()
    return {
        **dict(summary._mapping),
        "links_by_relation": {r.relation: r.n for r in by_relation},
    }


@router.get("/learned")
async def learned(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = (await session.execute(_SELECT_LEARNED, {"limit": limit})).all()
    return {
        "learned": [
            {
                "hypothesis_id": r.hypothesis_id,
                "created_at": r.created_at.isoformat(),
                "hypothesis_text": r.hypothesis_text,
                "expected_effect": r.expected_effect,
                "claim": {
                    "id": r.claim_id,
                    "mechanism": r.mechanism,
                    "asset_class": r.asset_class,
                    "family_hint": r.family_hint,
                },
                "paper": {"id": r.paper_id, "arxiv_id": r.arxiv_id, "title": r.title},
                "strategy": (
                    {"id": r.strategy_id, "status": r.strategy_status}
                    if r.strategy_id is not None
                    else None
                ),
            }
            for r in rows
        ]
    }


@router.get("/{paper_id}")
async def paper_detail(paper_id: int) -> dict[str, Any]:
    async with get_session_factory()() as session:
        paper = (await session.execute(_SELECT_PAPER, {"id": paper_id})).first()
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        claims = (await session.execute(_SELECT_PAPER_CLAIMS, {"id": paper_id})).all()
        links = (await session.execute(_SELECT_PAPER_LINKS, {"id": paper_id})).all()
    return {
        "id": paper.id,
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "ingested_at": paper.ingested_at.isoformat(),
        "claims": [
            {
                "id": c.id,
                "mechanism": c.mechanism,
                "asset_class": c.asset_class,
                "horizon": c.horizon,
                "direction": c.direction,
                "stated_effect": c.stated_effect,
                "data_period": c.data_period,
                "testable": c.testable,
                "family_hint": c.family_hint,
                "concepts": list(c.concepts),
            }
            for c in claims
        ],
        "links": [
            {
                "relation": link.relation,
                "direction": link.direction,
                "rationale": link.rationale,
                "claim_id": link.claim_id,
                "other_claim": {"id": link.other_claim_id, "mechanism": link.other_mechanism},
                "other_paper": {
                    "id": link.other_paper_id,
                    "arxiv_id": link.other_arxiv_id,
                    "title": link.other_title,
                },
            }
            for link in links
        ],
    }

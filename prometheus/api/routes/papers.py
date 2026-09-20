"""Research papers API endpoint -- surfaces research_papers (PROMPT 9's
daily arXiv ingestion) for the dashboard's "paper ingested" feed row.
Small dataset by design (llm_ingestion runs once a day, a handful of
papers per run -- see worker.py), so a flat LIMIT is enough; no
pagination.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/research-papers", tags=["research-papers"])

_SELECT_RECENT = text(
    """
    SELECT id, arxiv_id, title, abstract, ingested_at
      FROM research_papers
     ORDER BY ingested_at DESC
     LIMIT 50
    """
)


@router.get("/")
async def list_research_papers() -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = (await session.execute(_SELECT_RECENT)).all()
    papers = [
        {
            "id": r.id,
            "arxiv_id": r.arxiv_id,
            "title": r.title,
            "abstract": r.abstract,
            "ingested_at": r.ingested_at.isoformat(),
        }
        for r in rows
    ]
    return {"papers": papers, "total": len(papers)}

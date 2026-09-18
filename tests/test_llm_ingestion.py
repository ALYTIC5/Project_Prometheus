"""tests/test_llm_ingestion.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.ingestion import _extract_key_sections, ingest_paper

pytestmark = pytest.mark.db

_FAKE_PDF_TEXT = (
    "Abstract\nThis paper studies momentum.\n"
    "1 Introduction\nMomentum has been studied since Jegadeesh.\n"
    "2 Methodology\nWe use a 12-month lookback.\n"
    "3 Results\nMomentum earns positive returns.\n"
    "4 Conclusion\nMomentum works.\n"
    "References\n[1] Jegadeesh, N. (1993)."
)

_FAKE_TEI_XML = """<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body>
    <div><head>Introduction</head><p>Momentum has been studied since Jegadeesh.</p></div>
    <div><head>Methodology</head><p>We use a 12-month lookback.</p></div>
    <div><head>Results</head><p>Momentum earns positive returns.</p></div>
    <div><head>Conclusion</head><p>Momentum works.</p></div>
    <div><head>References</head><p>[1] Jegadeesh, N. (1993).</p></div>
  </body></text>
</TEI>"""


def test_extract_key_sections_excludes_references_via_grobid_tei() -> None:
    sections = _extract_key_sections(abstract="This paper studies momentum.", tei_xml=_FAKE_TEI_XML)
    assert "12-month lookback" in sections
    assert "Momentum earns positive returns" in sections
    assert "Jegadeesh, N. (1993)" not in sections


def test_extract_key_sections_falls_back_to_full_text_without_tei() -> None:
    sections = _extract_key_sections(abstract="This paper studies momentum.", tei_xml=None)
    assert "This paper studies momentum." in sections


async def test_ingest_paper_is_idempotent_on_arxiv_id(db_session: AsyncSession) -> None:
    with (
        patch(
            "prometheus.research.llm.ingestion._download_pdf",
            new=AsyncMock(return_value=b"%PDF-fake"),
        ),
        patch(
            "prometheus.research.llm.ingestion._extract_full_text",
            return_value=_FAKE_PDF_TEXT,
        ),
        patch(
            "prometheus.research.llm.ingestion._fetch_arxiv_metadata",
            new=AsyncMock(
                return_value={
                    "title": "Momentum Study",
                    "abstract": "This paper studies momentum.",
                }
            ),
        ),
        patch(
            "prometheus.research.llm.ingestion._call_grobid",
            new=AsyncMock(return_value=_FAKE_TEI_XML),
        ),
    ):
        first = await ingest_paper(db_session, "2401.00003")
        second = await ingest_paper(db_session, "2401.00003")

    # Second call returns the EXISTING row, does not raise on the
    # arxiv_id unique constraint and does not insert a duplicate.
    assert first.id == second.id
    count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM research_papers WHERE arxiv_id = :id"),
            {"id": "2401.00003"},
        )
    ).scalar_one()
    assert count == 1


async def test_ingest_paper_stores_row_using_grobid(db_session: AsyncSession) -> None:
    with (
        patch(
            "prometheus.research.llm.ingestion._download_pdf",
            new=AsyncMock(return_value=b"%PDF-fake"),
        ),
        patch(
            "prometheus.research.llm.ingestion._extract_full_text",
            return_value=_FAKE_PDF_TEXT,
        ),
        patch(
            "prometheus.research.llm.ingestion._fetch_arxiv_metadata",
            new=AsyncMock(
                return_value={
                    "title": "Momentum Study",
                    "abstract": "This paper studies momentum.",
                }
            ),
        ),
        patch(
            "prometheus.research.llm.ingestion._call_grobid",
            new=AsyncMock(return_value=_FAKE_TEI_XML),
        ),
    ):
        paper = await ingest_paper(db_session, "2401.00001")

    assert paper.arxiv_id == "2401.00001"
    assert "12-month lookback" in paper.key_sections
    row = (
        await db_session.execute(
            text("SELECT arxiv_id FROM research_papers WHERE arxiv_id = :id"),
            {"id": "2401.00001"},
        )
    ).first()
    assert row is not None


async def test_ingest_paper_falls_back_when_grobid_unreachable(
    db_session: AsyncSession,
) -> None:
    with (
        patch(
            "prometheus.research.llm.ingestion._download_pdf",
            new=AsyncMock(return_value=b"%PDF-fake"),
        ),
        patch(
            "prometheus.research.llm.ingestion._extract_full_text",
            return_value=_FAKE_PDF_TEXT,
        ),
        patch(
            "prometheus.research.llm.ingestion._fetch_arxiv_metadata",
            new=AsyncMock(
                return_value={
                    "title": "Momentum Study",
                    "abstract": "This paper studies momentum.",
                }
            ),
        ),
        patch(
            "prometheus.research.llm.ingestion._call_grobid",
            new=AsyncMock(side_effect=ConnectionError),
        ),
    ):
        paper = await ingest_paper(db_session, "2401.00002")

    # Soft failure -- still a complete, storable row, not a raised exception.
    assert paper.arxiv_id == "2401.00002"
    assert paper.full_text == _FAKE_PDF_TEXT
    assert len(paper.key_sections) > 0

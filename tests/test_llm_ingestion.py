"""tests/test_llm_ingestion.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.ingestion import (
    _extract_key_sections,
    base_arxiv_id,
    ingest_paper,
    search_arxiv,
)

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


# I4 (final-review fix wave): a REAL GROBID paragraph, with an inline
# <ref> child. ElementTree's `p.text` stops at the first child element, so
# the pre-fix code kept only "Momentum was first documented by " and threw
# away everything after the citation -- i.e. most of every paragraph.
_TEI_XML_WITH_INLINE_REFS = """<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body>
    <div><head>Introduction</head><p>Momentum was first documented by \
<ref type="bibr">[1]</ref> and confirmed out of sample much later.</p></div>
  </body></text>
</TEI>"""


def test_extract_key_sections_captures_text_after_inline_refs() -> None:
    sections = _extract_key_sections(abstract="abstract text", tei_xml=_TEI_XML_WITH_INLINE_REFS)
    assert "Momentum was first documented by" in sections
    assert "[1]" in sections
    # The half that `p.text` silently dropped before the fix.
    assert "confirmed out of sample much later" in sections


_FAKE_ARXIV_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00123v1</id>
    <title>A Recent Quant Paper</title>
    <summary>An abstract.</summary>
  </entry>
</feed>"""


def _mock_httpx_client(response_text: str) -> tuple[MagicMock, MagicMock]:
    response = MagicMock()
    response.text = response_text
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx, client


async def test_search_arxiv_sorts_by_submission_date_descending() -> None:
    """I5 (final-review fix wave): without an explicit sort, arXiv returns
    relevance order, which is static for a fixed category query -- the
    daily ingestion concern would refetch the same top-N papers forever
    and research_papers would never grow."""
    client_ctx, client = _mock_httpx_client(_FAKE_ARXIV_FEED)
    with patch(
        "prometheus.research.llm.ingestion.httpx.AsyncClient", return_value=client_ctx
    ):
        papers = await search_arxiv("cat:q-fin.*", 5)

    assert [p.arxiv_id for p in papers] == ["2401.00123v1"]
    params = client.get.await_args.kwargs["params"]
    assert params["sortBy"] == "submittedDate"
    assert params["sortOrder"] == "descending"
    assert params["search_query"] == "cat:q-fin.*"
    assert params["max_results"] == 5
    assert params["start"] == 0


async def test_search_arxiv_passes_the_page_offset() -> None:
    client_ctx, client = _mock_httpx_client(_FAKE_ARXIV_FEED)
    with patch(
        "prometheus.research.llm.ingestion.httpx.AsyncClient", return_value=client_ctx
    ):
        await search_arxiv("cat:q-fin.*", 100, start=300)

    assert client.get.await_args.kwargs["params"]["start"] == 300


def test_base_arxiv_id_strips_the_version_suffix() -> None:
    assert base_arxiv_id("2401.00123v2") == "2401.00123"
    assert base_arxiv_id("2401.00123") == "2401.00123"
    assert base_arxiv_id("q-fin/0601001v1") == "q-fin/0601001"


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

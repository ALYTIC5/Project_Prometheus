"""prometheus/research/llm/ingestion.py -- PROMPT 9's arXiv paper
ingestion. No repo named "VibeQuant" with paper-extraction functionality
was found (web search turned up several unrelated small finance-data
libraries sharing that name, none with any PDF/paper parsing code) -- see
docs/DEPENDENCIES.md. Built in-house, same posture as tools/art/'s own
2026-09-09 build-vs-adopt evaluation.

Section extraction uses GROBID (kermitt2/grobid, 5.1k GitHub stars,
Apache 2.0) -- a real, production-proven ML-based structured-extraction
tool (used by ResearchGate, CERN, Mendeley), not a hand-rolled heading
regex. GROBID runs as its own Railway service with scale-to-zero enabled
(configured directly in Railway's dashboard, not this repo) -- GROBID_URL
points at it over Railway's private network. If GROBID is unreachable
(cold-start timeout, service down), this is a soft failure: falls back to
the raw pypdf-extracted full_text, truncated to a section-sized budget,
logged as a warning -- a paper with worse extraction beats no paper
ingested this cycle.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import ResearchPaper

logger = logging.getLogger(__name__)

_ARXIV_API_BASE = "https://export.arxiv.org/api/query"
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# Sections worth feeding to the hypothesis prompt -- excludes references/
# acknowledgments/appendix, matching this plan's spec decision (full text
# stored for archival, only these sections feed the LLM to control cost).
_WANTED_SECTION_HEADS = re.compile(
    r"^(introduction|method(ology)?|model|results?|conclusion)s?$", re.IGNORECASE
)

# Fallback budget when GROBID is unavailable and only raw pypdf text
# exists -- roughly matches the token budget the wanted sections above
# would occupy in practice, not an arbitrary number (a full paper is
# typically 15-40k characters; the wanted sections are usually under a
# third of that).
_FALLBACK_CHAR_BUDGET = 12_000


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    abstract: str
    pdf_url: str


async def _fetch_arxiv_metadata(arxiv_id: str) -> dict[str, str]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            _ARXIV_API_BASE, params={"id_list": arxiv_id}, timeout=30.0
        )
        response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    entry = root.find("atom:entry", _ARXIV_NS)
    if entry is None:
        raise ValueError(f"arXiv id not found: {arxiv_id}")
    title = (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip()
    abstract = (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip()
    return {"title": title, "abstract": abstract}


async def search_arxiv(query: str, max_results: int) -> list[ArxivPaper]:
    """Public arXiv API, no key required. `query` is caller-supplied for
    testability; production always passes a fixed category filter
    (see worker.py's own call site) -- never anything derived from
    strategy state, which would make ingestion depend on research
    outcomes rather than the other way around.

    I5 (final-review fix wave): sorted by submission date, newest first.
    arXiv's default sort is by relevance, which is STATIC for a fixed
    category query -- the daily ingestion concern would have refetched
    the same top-N papers forever and research_papers would never have
    grown past its first day's results."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            _ARXIV_API_BASE,
            params={
                "search_query": query,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    papers: list[ArxivPaper] = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        raw_id = (entry.findtext("atom:id", default="", namespaces=_ARXIV_NS) or "").strip()
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        title = (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip()
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            )
        )
    return papers


async def _download_pdf(pdf_url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.get(pdf_url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
    return response.content


def _extract_full_text(pdf_bytes: bytes) -> str:
    import io

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def _call_grobid(pdf_bytes: bytes) -> str:
    """Calls GROBID's processFulltextDocument endpoint directly (not the
    grobid-client-python batch client, which is designed for
    directory-of-files batch jobs, not this one-paper-at-a-time call
    shape) over Railway's private network. Raises on any failure --
    the caller (ingest_paper) decides what a failure means, this
    function does not swallow errors itself."""
    grobid_url = os.environ["GROBID_URL"]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{grobid_url}/api/processFulltextDocument",
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            timeout=120.0,  # cold-start-tolerant -- scale-to-zero means the
                             # first call after idle can take a while to wake
        )
        response.raise_for_status()
    return response.text


def _extract_key_sections(*, abstract: str, tei_xml: str | None) -> str:
    """abstract + introduction + methodology + results/conclusion, via
    GROBID's TEI-XML div/head structure when available. Falls back to a
    plain abstract-plus-truncated-full-text shape when tei_xml is None
    (GROBID unreachable) -- the caller supplies full_text separately in
    that case; this function only ever sees the abstract on its own."""
    if tei_xml is None:
        return abstract
    root = ElementTree.fromstring(tei_xml)
    parts = [abstract]
    for div in root.findall(".//tei:body/tei:div", _TEI_NS):
        head = div.findtext("tei:head", default="", namespaces=_TEI_NS)
        if not head or not _WANTED_SECTION_HEADS.match(head.strip()):
            continue
        # I4 (final-review fix wave): itertext(), not `.text` -- real
        # GROBID paragraphs carry inline <ref>/<formula> children, and
        # `.text` is only the run of text BEFORE the first child element,
        # so most of a paragraph was being silently dropped.
        paragraphs = ["".join(p.itertext()) for p in div.findall("tei:p", _TEI_NS)]
        parts.append(" ".join(paragraphs))
    return "\n\n".join(parts)


async def ingest_paper(session: AsyncSession, arxiv_id: str) -> ResearchPaper:
    """Idempotent on arxiv_id: a re-ingestion request for a paper already
    in research_papers returns the existing row unchanged rather than
    raising on the arxiv_id unique constraint or inserting a duplicate.
    Check-then-insert, not an ON CONFLICT upsert -- this worker's single
    scheduled process has no concurrent-writer race to guard against
    (unlike ConfigSnapshot's genuine upsert-on-conflict use case)."""
    existing = (
        await session.execute(
            select(ResearchPaper).where(ResearchPaper.arxiv_id == arxiv_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    metadata = await _fetch_arxiv_metadata(arxiv_id)
    pdf_bytes = await _download_pdf(f"https://arxiv.org/pdf/{arxiv_id}")
    full_text = _extract_full_text(pdf_bytes)

    try:
        tei_xml = await _call_grobid(pdf_bytes)
        key_sections = _extract_key_sections(abstract=metadata["abstract"], tei_xml=tei_xml)
    except Exception:
        logger.warning("GROBID unreachable for %s, falling back to pypdf-only extraction", arxiv_id)
        key_sections = metadata["abstract"] + "\n\n" + full_text[:_FALLBACK_CHAR_BUDGET]

    paper = ResearchPaper(
        arxiv_id=arxiv_id,
        title=metadata["title"],
        abstract=metadata["abstract"],
        full_text=full_text,
        key_sections=key_sections,
    )
    session.add(paper)
    await session.flush()
    return paper

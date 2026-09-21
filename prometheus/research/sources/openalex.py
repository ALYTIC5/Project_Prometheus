"""OpenAlex paper source (second research-paper source alongside the
existing arXiv ingestion in research/llm/ingestion.py).

Verified live against the real API before this module was written:
- The naive `filter=doi:10.2139` PREFIX filter does NOT work -- OpenAlex's
  `doi` filter requires one exact, full DOI. SSRN-scoped search instead
  uses `filter=primary_location.source.id:S4210172589` (SSRN's own
  OpenAlex source id, found via GET /sources?search=SSRN).
- `abstract_inverted_index` (word -> list of positions) is present for
  only ~4% of a 25-paper SSRN-hosted sample, vs ~64% for a general
  finance-query sample of the same size -- absence is the common case
  for this source, not a bug to route around.
- Some SSRN-hosted records' `open_access.oa_url` points directly at
  papers.ssrn.com rather than a real open-access mirror. SSRN's terms of
  use prohibit automated queries, so any such URL is filtered to None
  here, at the source adapter, rather than left for a downstream
  fetcher to remember not to touch.
"""
from __future__ import annotations

import os
from datetime import date

import httpx

from prometheus.research.sources.base import PaperCandidate

_OPENALEX_API_BASE = "https://api.openalex.org/works"

# SSRN's own OpenAlex source id (GET https://api.openalex.org/sources?search=SSRN).
# Kept as a named constant, not inlined, since it's meaningless on sight.
SSRN_SOURCE_ID = "S4210172589"

_SSRN_DOMAIN = "ssrn.com"


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """None (never "") when OpenAlex has no abstract for this record --
    an empty string would read as "abstract present but blank" to a
    caller deciding whether to spend an LLM call extracting from it."""
    if not inverted_index:
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for position in positions:
            positioned.append((position, word))
    positioned.sort(key=lambda pair: pair[0])
    return " ".join(word for _, word in positioned)


def _clean_oa_pdf_url(open_access: dict[str, object] | None) -> str | None:
    if not open_access:
        return None
    oa_url = open_access.get("oa_url")
    if not isinstance(oa_url, str) or not oa_url:
        return None
    if _SSRN_DOMAIN in oa_url:
        return None
    return oa_url


def _bare_doi(raw_doi: str | None) -> str | None:
    if not raw_doi:
        return None
    return raw_doi.removeprefix("https://doi.org/")


def _parse_work(work: dict[str, object]) -> PaperCandidate | None:
    raw_doi = work.get("doi")
    doi = _bare_doi(raw_doi if isinstance(raw_doi, str) else None)
    if doi is None:
        return None
    title = work.get("title")
    if not isinstance(title, str) or not title:
        return None
    publication_date_raw = work.get("publication_date")
    if not isinstance(publication_date_raw, str) or not publication_date_raw:
        return None
    publication_date = date.fromisoformat(publication_date_raw)
    cited_by_count = work.get("cited_by_count")
    if not isinstance(cited_by_count, int):
        cited_by_count = 0
    abstract_inverted_index = work.get("abstract_inverted_index")
    abstract = _reconstruct_abstract(
        abstract_inverted_index if isinstance(abstract_inverted_index, dict) else None
    )
    open_access = work.get("open_access")
    oa_pdf_url = _clean_oa_pdf_url(open_access if isinstance(open_access, dict) else None)
    return PaperCandidate(
        doi=doi,
        title=title,
        abstract=abstract,
        publication_date=publication_date,
        cited_by_count=cited_by_count,
        oa_pdf_url=oa_pdf_url,
        source="openalex",
    )


async def search_openalex(
    query: str,
    max_results: int,
    *,
    source_id: str | None = None,
) -> list[PaperCandidate]:
    """`source_id` restricts to one OpenAlex source (e.g. SSRN_SOURCE_ID)
    via `primary_location.source.id` -- omit for an unrestricted finance
    search across all indexed sources.

    An optional OPENALEX_CONTACT_EMAIL env var joins OpenAlex's "polite
    pool" (faster, more reliable rate limits) via the documented `mailto`
    param -- deliberately not hardcoded to any individual's email; unset
    by default, and this call works fine without it, just in the slower
    common pool.
    """
    params: dict[str, str | int] = {"search": query, "per_page": max_results}
    if source_id is not None:
        params["filter"] = f"primary_location.source.id:{source_id}"
    contact_email = os.environ.get("OPENALEX_CONTACT_EMAIL")
    if contact_email:
        params["mailto"] = contact_email

    async with httpx.AsyncClient() as client:
        response = await client.get(_OPENALEX_API_BASE, params=params, timeout=30.0)
        response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    candidates: list[PaperCandidate] = []
    for work in results:
        if not isinstance(work, dict):
            continue
        candidate = _parse_work(work)
        if candidate is not None:
            candidates.append(candidate)
    return candidates

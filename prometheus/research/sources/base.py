"""The source-agnostic paper shape every research paper source returns
-- one dataclass (PaperCandidate), many sources (OpenAlex today;
research/llm/ingestion.py's arXiv path predates this interface and is
not retrofitted onto it here, since its own ArxivPaper shape already
works and nothing currently needs both sources behind one call site).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PaperCandidate:
    """`doi` is the bare identifier (e.g. "10.2139/ssrn.2089463"), not
    the full "https://doi.org/..." URL -- matching every other bare-
    identifier convention this codebase already uses (FRED's series_id,
    arXiv's arxiv_id).

    `abstract` is None (never an empty string) when the source genuinely
    has no abstract for this record -- OpenAlex's own
    abstract_inverted_index is absent for the large majority of SSRN-
    hosted records (verified directly against the real API before this
    module was built: ~4% of a 25-paper SSRN sample had one, vs ~64%
    for a general finance-query sample of the same size). An honest
    "nothing to extract from" must never be silently coerced into "" --
    a caller that tries to build a hypothesis from an empty string would
    get a nonsensical extraction rather than skipping the paper.

    `oa_pdf_url` is None when the source has no legitimate open-access
    PDF, OR when the only URL available points at a domain this
    project must never fetch directly (ssrn.com -- SSRN's terms of use
    prohibit automated queries of any kind; OpenAlex's own oa_url field
    for an SSRN-hosted record can itself be a direct ssrn.com URL, not
    just a DOI redirect, confirmed directly against the real API: 2/25
    sampled SSRN records had this shape). Filtering happens at the
    source adapter, not left to callers to remember.
    """

    doi: str
    title: str
    abstract: str | None
    publication_date: date
    cited_by_count: int
    oa_pdf_url: str | None
    source: str

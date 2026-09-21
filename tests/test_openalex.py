"""tests/test_openalex.py -- OpenAlex paper source (research/sources/).

No pytestmark: unlike test_llm_ingestion.py's DB-backed tests, nothing
here touches a database -- OpenAlex ingestion's DB-write path is blocked
on a research_papers schema migration (see docs/DEFERRED.md), so these
tests only cover the source adapter itself.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prometheus.research.sources.base import PaperCandidate
from prometheus.research.sources.openalex import (
    SSRN_SOURCE_ID,
    _bare_doi,
    _clean_oa_pdf_url,
    _reconstruct_abstract,
    search_openalex,
)


def _mock_httpx_client(json_payload: dict[str, object]) -> tuple[MagicMock, MagicMock]:
    response = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx, client


def test_reconstruct_abstract_from_inverted_index() -> None:
    # "returns momentum returns" -- "returns" appears twice (positions 0, 2)
    inverted = {"returns": [0, 2], "momentum": [1]}
    assert _reconstruct_abstract(inverted) == "returns momentum returns"


def test_reconstruct_abstract_none_when_absent() -> None:
    """The large majority of SSRN-hosted OpenAlex records have no
    abstract_inverted_index at all (verified: ~4% of a 25-paper sample) --
    None must stay None, never coerced to ""."""
    assert _reconstruct_abstract(None) is None
    assert _reconstruct_abstract({}) is None


def test_clean_oa_pdf_url_filters_ssrn_domain() -> None:
    """SSRN's terms of use prohibit automated queries -- a direct
    papers.ssrn.com URL must never be returned as a fetchable oa_pdf_url,
    even when OpenAlex's own open_access.oa_url field points there."""
    assert _clean_oa_pdf_url({"oa_url": "https://papers.ssrn.com/sol3/abc.pdf"}) is None


def test_clean_oa_pdf_url_keeps_legitimate_url() -> None:
    assert (
        _clean_oa_pdf_url({"oa_url": "https://example.edu/repo/paper.pdf"})
        == "https://example.edu/repo/paper.pdf"
    )


def test_clean_oa_pdf_url_none_when_missing() -> None:
    assert _clean_oa_pdf_url(None) is None
    assert _clean_oa_pdf_url({}) is None


def test_bare_doi_strips_url_prefix() -> None:
    assert _bare_doi("https://doi.org/10.2139/ssrn.2089463") == "10.2139/ssrn.2089463"
    assert _bare_doi("10.2139/ssrn.2089463") == "10.2139/ssrn.2089463"
    assert _bare_doi(None) is None


_FAKE_OPENALEX_PAYLOAD = {
    "results": [
        {
            "doi": "https://doi.org/10.1016/j.jfineco.2020.01.001",
            "title": "Momentum Everywhere",
            "publication_date": "2020-03-15",
            "cited_by_count": 42,
            "abstract_inverted_index": {"Momentum": [0], "works.": [1]},
            "open_access": {"oa_url": "https://example.edu/momentum.pdf"},
        },
        {
            # No DOI -- must be dropped, not returned with a fabricated one.
            "doi": None,
            "title": "Untitled Working Paper",
            "publication_date": "2021-01-01",
            "cited_by_count": 0,
        },
    ]
}


async def test_search_openalex_parses_results_and_drops_missing_doi() -> None:
    client_ctx, client = _mock_httpx_client(_FAKE_OPENALEX_PAYLOAD)
    with patch(
        "prometheus.research.sources.openalex.httpx.AsyncClient", return_value=client_ctx
    ):
        candidates = await search_openalex("momentum anomaly", 10)

    assert candidates == [
        PaperCandidate(
            doi="10.1016/j.jfineco.2020.01.001",
            title="Momentum Everywhere",
            abstract="Momentum works.",
            publication_date=date(2020, 3, 15),
            cited_by_count=42,
            oa_pdf_url="https://example.edu/momentum.pdf",
            source="openalex",
        )
    ]


async def test_search_openalex_passes_source_id_filter() -> None:
    client_ctx, client = _mock_httpx_client({"results": []})
    with patch(
        "prometheus.research.sources.openalex.httpx.AsyncClient", return_value=client_ctx
    ):
        await search_openalex("algorithmic trading", 10, source_id=SSRN_SOURCE_ID)

    params = client.get.await_args.kwargs["params"]
    assert params["filter"] == f"primary_location.source.id:{SSRN_SOURCE_ID}"


async def test_search_openalex_no_filter_when_source_id_omitted() -> None:
    client_ctx, client = _mock_httpx_client({"results": []})
    with patch(
        "prometheus.research.sources.openalex.httpx.AsyncClient", return_value=client_ctx
    ):
        await search_openalex("momentum anomaly", 10)

    params = client.get.await_args.kwargs["params"]
    assert "filter" not in params


async def test_search_openalex_uses_contact_email_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENALEX_CONTACT_EMAIL joins the polite pool -- must never be the
    user's own personal email hardcoded into this module."""
    monkeypatch.setenv("OPENALEX_CONTACT_EMAIL", "research-bot@example.com")
    client_ctx, client = _mock_httpx_client({"results": []})
    with patch(
        "prometheus.research.sources.openalex.httpx.AsyncClient", return_value=client_ctx
    ):
        await search_openalex("momentum anomaly", 10)

    params = client.get.await_args.kwargs["params"]
    assert params["mailto"] == "research-bot@example.com"


async def test_search_openalex_omits_mailto_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_CONTACT_EMAIL", raising=False)
    client_ctx, client = _mock_httpx_client({"results": []})
    with patch(
        "prometheus.research.sources.openalex.httpx.AsyncClient", return_value=client_ctx
    ):
        await search_openalex("momentum anomaly", 10)

    params = client.get.await_args.kwargs["params"]
    assert "mailto" not in params

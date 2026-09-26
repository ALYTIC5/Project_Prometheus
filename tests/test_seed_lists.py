"""Curated strategy-list seeding: titles are parsed from the list, and a
paper is only accepted on an exact (normalised) title match with an
abstract."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

from prometheus.research.llm.ingestion import ArxivPaper
from prometheus.research.llm.seed_lists import find_paper, same_title, strategy_titles
from prometheus.research.sources.base import PaperCandidate

_README = """
| Strategy | Sharpe |
|---|---|
| [The Investment CAPM](https://paperswithbacktest.com/strategies/c1) | 1.8 |
| [Understanding Momentum and Reversal?](https://paperswithbacktest.com/strategies/u) | 0.5 |
| [A library, not a strategy](https://github.com/some/library) | |
| [The Investment CAPM](https://paperswithbacktest.com/strategies/c2) | 1.1 |
"""


def test_strategy_titles_reads_only_strategy_rows_once_each() -> None:
    assert strategy_titles(_README) == [
        "The Investment CAPM",
        "Understanding Momentum and Reversal?",
    ]


def test_same_title_ignores_case_and_punctuation_only() -> None:
    assert same_title(
        "Understanding Momentum and Reversal?", "understanding momentum, and reversal"
    )
    assert not same_title("The Investment CAPM", "The Investment CAPM Revisited")


def _candidate(title: str, abstract: str | None, doi: str = "10.1/x") -> PaperCandidate:
    return PaperCandidate(
        doi=doi, title=title, abstract=abstract, publication_date=date(2020, 1, 1),
        cited_by_count=0, oa_pdf_url=None, source="openalex",
    )


async def test_find_paper_prefers_arxiv_then_openalex_and_needs_an_abstract() -> None:
    arxiv_hit = ArxivPaper("2101.00001v1", "The Investment CAPM", "abs", "u")
    with (
        patch(
            "prometheus.research.llm.seed_lists.search_arxiv",
            new=AsyncMock(return_value=[arxiv_hit]),
        ),
        patch("prometheus.research.llm.seed_lists.search_openalex", new=AsyncMock()) as oa,
    ):
        found = await find_paper("The Investment CAPM")
    assert found is not None and found.paper_id == "2101.00001v1"
    oa.assert_not_awaited()

    with (
        patch("prometheus.research.llm.seed_lists.search_arxiv", new=AsyncMock(return_value=[])),
        patch(
            "prometheus.research.llm.seed_lists.search_openalex",
            new=AsyncMock(
                return_value=[
                    _candidate("The Investment CAPM", None, doi="10.1/none"),
                    _candidate("The Investment CAPM Revisited", "abs", doi="10.1/near"),
                    _candidate("The Investment CAPM", "abstract", doi="10.1/good"),
                ]
            ),
        ) as oa,
    ):
        found = await find_paper("The Investment CAPM?")
    assert found is not None and found.paper_id == "doi:10.1/good"
    assert oa.await_args.args[0] == "the investment capm"  # punctuation stripped for OpenAlex


async def test_find_paper_returns_none_when_nothing_matches_exactly() -> None:
    with (
        patch("prometheus.research.llm.seed_lists.search_arxiv", new=AsyncMock(return_value=[])),
        patch(
            "prometheus.research.llm.seed_lists.search_openalex",
            new=AsyncMock(return_value=[_candidate("Something else", "abs")]),
        ),
    ):
        assert await find_paper("The Investment CAPM") is None

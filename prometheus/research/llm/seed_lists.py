"""prometheus/research/llm/seed_lists.py -- papers named by curated
strategy lists, found by exact title on arXiv or OpenAlex.

The paperswithbacktest/awesome-systematic-trading README lists ~61
strategies, each titled after its source paper but linking only to the
list owner's site. Only the titles are read from it; each paper is then
looked up by title on arXiv (abstract from the arXiv API) or, failing
that, on OpenAlex (abstract only when OpenAlex has one; SSRN itself is
never fetched -- its terms forbid automated access). The list's own
backtest numbers are not stored: they are the list owner's claims, not
evidence (Law 9 keeps the evaluator independent of them).

No DB access here; the worker stores what this returns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from prometheus.research.llm.ingestion import search_arxiv
from prometheus.research.sources.openalex import search_openalex

AWESOME_SYSTEMATIC_TRADING_README = (
    "https://raw.githubusercontent.com/paperswithbacktest/awesome-systematic-trading/main/README.md"
)
_STRATEGY_ROW = re.compile(
    r"^\|\s*\[(?P<title>[^\]]+)\]\(https://paperswithbacktest\.com/strategies/[^)]+\)",
    re.MULTILINE,
)
_WORD = re.compile(r"[a-z0-9]+")
_MAX_ID_LENGTH = 32  # research_papers.arxiv_id is String(32)


@dataclass(frozen=True)
class SeedPaper:
    paper_id: str  # arXiv id, or "doi:<doi>" for a non-arXiv paper
    title: str
    abstract: str


def strategy_titles(readme: str) -> list[str]:
    return list(dict.fromkeys(m.group("title").strip() for m in _STRATEGY_ROW.finditer(readme)))


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def same_title(a: str, b: str) -> bool:
    """Exact after normalising case, punctuation and whitespace -- a
    near-miss title is a different paper, not the one the list named."""
    return _words(a) == _words(b)


async def fetch_readme(url: str = AWESOME_SYSTEMATIC_TRADING_README) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
    return response.text


async def find_paper(title: str) -> SeedPaper | None:
    phrase = " ".join(_words(title))
    for paper in await search_arxiv(f'ti:"{phrase}"', 5):
        if same_title(paper.title, title) and paper.abstract:
            return SeedPaper(paper.arxiv_id, paper.title, paper.abstract)
    # Punctuation in the query (a trailing "?") makes OpenAlex return 400.
    for candidate in await search_openalex(phrase, 5):
        paper_id = f"doi:{candidate.doi}"
        if (
            same_title(candidate.title, title)
            and candidate.abstract
            and len(paper_id) <= _MAX_ID_LENGTH
        ):
            return SeedPaper(paper_id, candidate.title, candidate.abstract)
    return None

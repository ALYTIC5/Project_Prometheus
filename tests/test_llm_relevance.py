"""The free relevance gate in front of claim extraction.

Measured 2026-09-26 against 136 distinct production papers: it kept all 5
that yielded a testable claim and all 46 that yielded any claim, and
dropped 22 of the 90 that yielded none (16% of LLM calls saved).
Deliberately loose -- 5 positives is too few to tune a tighter rule
without overfitting, and a dropped testable paper is lost knowledge while
an extra extraction costs ~$0.001."""
from __future__ import annotations

import pytest

from prometheus.research.llm.relevance import is_relevant


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        ("Simple Dynamic Stock/Bond/Gold Portfolios", "We study allocation rules."),
        ("Loss Choice or Model Choice?", "Cryptocurrency volatility forecasting."),
        ("Time-series momentum everywhere", "Past returns predict future returns."),
        ("Order flow imbalance", "Market microstructure and short-horizon price moves."),
    ],
)
def test_keeps_papers_about_returns_trading_or_prediction(title: str, abstract: str) -> None:
    assert is_relevant(title, abstract)


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        ("Existence of viscosity solutions for an HJB equation", "We prove uniqueness."),
        ("A note on Malliavin calculus", "We derive a new integration-by-parts formula."),
    ],
)
def test_drops_pure_mathematics(title: str, abstract: str) -> None:
    assert not is_relevant(title, abstract)

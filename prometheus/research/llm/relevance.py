"""prometheus/research/llm/relevance.py -- a free, rule-based gate in front
of claim extraction.

Most arXiv q-fin papers are pricing theory, stochastic calculus or
econometric method; an LLM call on them returns no testable claim. This
gate keeps a paper only if its title or abstract mentions returns,
trading, portfolios, predictability, a known anomaly or a traded market.
It is deliberately loose: dropping a paper with a testable claim loses
knowledge, extracting an
irrelevant one only costs a cheap call. Measured against production
extractions before enabling (tests/test_llm_relevance.py records the
numbers).
"""
from __future__ import annotations

import re

_SIGNAL = re.compile(
    r"\b("
    r"returns?|excess return|risk premi\w*|alpha|sharpe|"
    r"trading|trader|trade|strateg\w*|backtest\w*|"
    r"portfolio\w*|asset allocation|rebalanc\w*|"
    r"predict\w*|forecast\w*|anomal\w*|"
    r"momentum|reversal|mean[- ]revers\w*|trend[- ]follow\w*|carry|value premium|"
    r"volatility|drawdown|liquidity|order flow|market microstructure|"
    r"factor model|cross[- ]section\w*|stock market|equit\w*|crypto\w*|bitcoin|"
    r"etf|futures|commodit\w*|exchange rate|bond yields?"
    r")\b",
    re.IGNORECASE,
)


def is_relevant(title: str, abstract: str) -> bool:
    return bool(_SIGNAL.search(f"{title}\n{abstract}"))

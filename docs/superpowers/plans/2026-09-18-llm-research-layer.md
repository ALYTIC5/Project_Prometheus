# LLM Research Layer (PROMPT 9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-driven strategy hypothesis generator (Anthropic API,
arXiv-paper-informed) that is budget-capped, cannot reach the holdout set or
evaluate its own output, and ships disabled-by-default until it proves
itself against the Prompt 7 deterministic baseline via the existing
ablation harness.

**Architecture:** Three new modules under `research/llm/` (`ingestion.py`,
`budget.py`, `hypothesis.py`), one migration (three insert-only tables), one
bounded step added to `worker.py`'s existing research cycle, and one new
ablation-registration function reusing 100% of the existing
`experiments/ablation.py` machinery. The LLM path reuses the 3 existing
`StrategySpec` families — no new DSL, no new backtest engine code.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x async, Alembic, pydantic-settings,
Anthropic Python SDK, pypdf, grobid-client-python, pytest (TDD).

**Spec:** `docs/superpowers/specs/2026-09-18-llm-research-layer-design.md`

## Global Constraints

- Law 3 (holdout is sacred): `research/llm/hypothesis.py` takes NO database
  session parameter anywhere in its public API. It cannot open
  `get_holdout_session()` or `validation.holdout.access_holdout()` because
  it has no path to a session at all.
- Law 6 (append-only): `research_papers`, `llm_hypotheses`, `llm_usage` are
  insert-only by construction (nothing here is ever UPDATEd) — same
  exemption precedent as `ablation_trials`/`research_violations`, not added
  to migration 0003's trigger set.
- Cost discipline: no new always-on service in THIS repo's own deploy
  (GROBID is a separate Railway service with scale-to-zero — $0 idle,
  configured directly in Railway's dashboard, not part of this repo's
  Dockerfile/CI).
- `docs/DEPENDENCIES.md`: every new dependency gets a row (what it does,
  what it replaces, why not stdlib) before or in the same task it's first
  imported.
- Pin every new dependency to an exact version in `pyproject.toml`:
  `anthropic==1.6.0`, `pypdf==6.19.0` (confirmed current on PyPI as of
  2026-09-18). GROBID itself is called directly over HTTP (`httpx`,
  already a dependency) against its `processFulltextDocument` REST
  endpoint — NOT via the `grobid-client-python` package, which is built
  for directory-of-files batch jobs, a different call shape than this
  plan's one-paper-at-a-time ingestion (see Task 3).
- Anthropic pricing (cited, Anthropic's published rates as of 2026-09-18 —
  re-verify against Anthropic's live pricing page before merging, since
  this is time-sensitive data, not a fixed constant): Claude Sonnet 5 —
  $2.00 / 1M input tokens, $10.00 / 1M output tokens. Claude Haiku 4.5 —
  $1.00 / 1M input tokens, $5.00 / 1M output tokens.
- No invented numeric thresholds: the 80%/100% budget-tier boundaries come
  from PROMPTS.md's own text ("At 80% switch to a cheaper model; at 100%
  LLM generation halts"), not invented here.
- `strategies.spec` reconstructs via `StrategySpec.model_validate(row.spec)`
  — the established pattern (`research/population.py`), never hand-parsed.

---

## Task 1: Migration 0013 — data model

**Files:**
- Create: `alembic/versions/0013_llm_research.py`

**Interfaces:**
- Produces: `research_papers` (id, arxiv_id, title, abstract, full_text,
  key_sections, ingested_at), `llm_hypotheses` (id, strategy_fingerprint,
  paper_ids, hypothesis_text, expected_effect, model, input_tokens,
  output_tokens, est_cost_usd, created_at), `llm_usage` (id, model,
  input_tokens, output_tokens, est_cost_usd, purpose, created_at) — exact
  columns below. Every later task in this plan reads/writes these tables.

- [ ] **Step 1: Write the migration**

```python
"""research_papers + llm_hypotheses + llm_usage -- PROMPT 9's LLM research
layer.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-18

All three tables are insert-only by construction (nothing here is ever
UPDATEd) -- same exemption precedent as `ablation_trials`/
`research_violations`, not added to migration 0003's append-only trigger
set (that set names exactly experiments/results/decisions).

`llm_hypotheses.strategy_fingerprint` is `StrategySpec.config_hash()`, NOT
a `strategies.id` foreign key -- at the moment a hypothesis is generated,
its spec has only been enqueued as a run_backtest job (same as an
evolution child), not yet turned into a `Strategy` row. Same reasoning
`validation_results.strategy_fingerprint` already established: the real
join path, once a `Strategy` row exists, is strategies -> its latest
experiment -> that experiment's own config_hash column.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_papers",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("arxiv_id", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("abstract", sa.Text, nullable=False),
        sa.Column("full_text", sa.Text, nullable=False),
        sa.Column("key_sections", sa.Text, nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "llm_hypotheses",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("strategy_fingerprint", sa.String(64), nullable=False),
        sa.Column("paper_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("hypothesis_text", sa.Text, nullable=False),
        sa.Column("expected_effect", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("est_cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_llm_hypotheses_strategy_fingerprint", "llm_hypotheses", ["strategy_fingerprint"]
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("est_cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_llm_hypotheses_strategy_fingerprint", table_name="llm_hypotheses")
    op.drop_table("llm_hypotheses")
    op.drop_table("research_papers")
```

- [ ] **Step 2: Add the three SQLAlchemy models**

Modify `prometheus/core/db.py` — add after the `ComponentRegistry` class
(before `PaperOrder`, matching the file's chronological-by-migration
ordering):

```python
class ResearchPaper(Base):
    """One ingested arXiv paper. Insert-only by convention, same
    exemption as ResearchViolation/AblationTrial -- a source record, not
    a decision history."""

    __tablename__ = "research_papers"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    arxiv_id: Mapped[str] = mapped_column(sa.String(32), unique=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text)
    key_sections: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class LLMHypothesis(Base):
    """One LLM-generated strategy hypothesis. strategy_fingerprint is
    StrategySpec.config_hash(), matching validation_results' own
    strategy_fingerprint idiom -- not a strategies.id FK, since no
    Strategy row exists yet when this is written (the spec is enqueued
    as a run_backtest job first, same as an evolution child)."""

    __tablename__ = "llm_hypotheses"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    strategy_fingerprint: Mapped[str] = mapped_column(sa.String(64))
    paper_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    hypothesis_text: Mapped[str] = mapped_column(Text)
    expected_effect: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(sa.String(64))
    input_tokens: Mapped[int] = mapped_column(sa.Integer)
    output_tokens: Mapped[int] = mapped_column(sa.Integer)
    est_cost_usd: Mapped[float] = mapped_column(sa.Numeric(10, 6, asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class LLMUsage(Base):
    """Every LLM API call, successful or not -- CLAUDE.md's cost
    discipline: 'Every LLM call logs (model, input_tokens, output_tokens,
    est_cost_usd) to llm_usage.' Insert-only, same exemption as above."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(sa.String(64))
    input_tokens: Mapped[int] = mapped_column(sa.Integer)
    output_tokens: Mapped[int] = mapped_column(sa.Integer)
    est_cost_usd: Mapped[float] = mapped_column(sa.Numeric(10, 6, asdecimal=False))
    purpose: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )
```

Check `prometheus/core/db.py`'s existing imports already cover `Text`,
`func`, `JSONB`, `Mapped`, `mapped_column`, `datetime` (they do — every
other model in the file already uses them); add nothing new.

- [ ] **Step 3: Verify the migration applies cleanly**

Run: `alembic upgrade head` against a scratch Postgres (or rely on CI's
`db-tests` job, which runs every migration from empty — same verification
every prior migration task in this project has used; there is no local
Postgres in this dev environment).

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/0013_llm_research.py prometheus/core/db.py
git commit -m "feat(llm): add research_papers/llm_hypotheses/llm_usage tables"
```

---

## Task 2: `research/llm/budget.py`

**Files:**
- Create: `prometheus/research/llm/__init__.py` (empty)
- Create: `prometheus/research/llm/budget.py`
- Test: `tests/test_llm_budget.py`

**Interfaces:**
- Consumes: `LLMUsage` (Task 1, `prometheus.core.db`).
- Produces: `BudgetSettings` (pydantic-settings class), `get_budget_settings()
  -> BudgetSettings`, `async def current_tier(session: AsyncSession) ->
  Literal["full", "cheap", "halted"]`, `def model_for_tier(tier:
  Literal["full", "cheap", "halted"]) -> str`, `def estimate_cost(model:
  str, input_tokens: int, output_tokens: int) -> float`. Tasks 3 and 4
  import all four.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_llm_budget.py"""
from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import LLMUsage
from prometheus.research.llm.budget import (
    BudgetSettings,
    current_tier,
    estimate_cost,
    model_for_tier,
)

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _budget_env() -> None:
    os.environ["LLM_MONTHLY_BUDGET_USD"] = "100.0"


async def _log_usage(session: AsyncSession, cost: float) -> None:
    session.add(
        LLMUsage(
            model="claude-sonnet-5",
            input_tokens=1000,
            output_tokens=500,
            est_cost_usd=cost,
            purpose="hypothesis_generation",
        )
    )
    await session.flush()


async def test_current_tier_is_full_under_80_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 79.0)
    assert await current_tier(db_session) == "full"


async def test_current_tier_is_cheap_between_80_and_100_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 85.0)
    assert await current_tier(db_session) == "cheap"


async def test_current_tier_is_halted_at_or_over_100_percent(db_session: AsyncSession) -> None:
    await _log_usage(db_session, 100.0)
    assert await current_tier(db_session) == "halted"


def test_model_for_tier_maps_full_to_sonnet_and_cheap_to_haiku() -> None:
    assert model_for_tier("full") == "claude-sonnet-5"
    assert model_for_tier("cheap") == "claude-haiku-4-5"
    with pytest.raises(ValueError):
        model_for_tier("halted")  # type: ignore[arg-type]


def test_estimate_cost_uses_cited_per_model_rates() -> None:
    # Sonnet: $2/1M input, $10/1M output (see this plan's Global Constraints)
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(2.0 + 10.0)


def test_budget_settings_raises_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MONTHLY_BUDGET_USD", raising=False)
    with pytest.raises(Exception):
        BudgetSettings()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.research.llm'`

- [ ] **Step 3: Write the implementation**

```python
"""prometheus/research/llm/budget.py -- PROMPT 9's monthly LLM spend cap.

Not instantiated at import time (same lazy pattern as
experiments.queue.get_queue_settings/QueueSettings): most processes never
touch the LLM path, so requiring LLM_MONTHLY_BUDGET_USD to be set for
every import of prometheus.research.llm would break every environment
that hasn't opted into this feature yet.

Tier boundaries (80%/100%) are PROMPTS.md's own literal words ("At 80%
switch to a cheaper model; at 100% LLM generation halts"), not invented
here. Per-model pricing is Anthropic's own published rate card (cited in
this plan's Global Constraints) -- re-verify against Anthropic's live
pricing page if this ever needs updating; token prices are not a fixed
constant like z=1.96, they change with the market.
"""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Tier = Literal["full", "cheap", "halted"]

_MODEL_FOR_TIER: dict[str, str] = {
    "full": "claude-sonnet-5",
    "cheap": "claude-haiku-4-5",
}

# (usd_per_1k_input, usd_per_1k_output) -- Anthropic's published per-model
# rate card, 2026-09-18. See this plan's Global Constraints for the
# per-million-token figures this is derived from.
_PRICING_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (0.002, 0.010),
    "claude-haiku-4-5": (0.001, 0.005),
}

_FULL_TIER_CEILING = 0.8
_CHEAP_TIER_CEILING = 1.0

_SELECT_MONTH_TO_DATE_SPEND = text(
    """
    SELECT COALESCE(SUM(est_cost_usd), 0) AS total
      FROM llm_usage
     WHERE created_at >= date_trunc('month', now())
    """
)


class BudgetSettings(BaseSettings):
    """Env-only, frozen -- same fail-fast-on-missing posture as
    core.config.RiskLimits (a silently-defaulted budget is worse than a
    crash for a cost-control feature)."""

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    LLM_MONTHLY_BUDGET_USD: float


_budget_settings: BudgetSettings | None = None


def get_budget_settings() -> BudgetSettings:
    """Lazy, like experiments.queue.get_queue_settings -- LLM env is only
    required once a caller actually checks/spends budget, not at
    import time."""
    global _budget_settings
    if _budget_settings is None:
        _budget_settings = BudgetSettings()
    return _budget_settings


async def current_tier(session: AsyncSession) -> Tier:
    settings = get_budget_settings()
    spend = float((await session.execute(_SELECT_MONTH_TO_DATE_SPEND)).scalar_one())
    fraction = spend / settings.LLM_MONTHLY_BUDGET_USD
    if fraction >= _CHEAP_TIER_CEILING:
        return "halted"
    if fraction >= _FULL_TIER_CEILING:
        return "cheap"
    return "full"


def model_for_tier(tier: Tier) -> str:
    try:
        return _MODEL_FOR_TIER[tier]
    except KeyError:
        raise ValueError(f"no model for tier {tier!r} (LLM generation is halted)") from None


def estimate_cost(model: str, *, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = _PRICING_PER_1K_TOKENS[model]
    return (input_tokens / 1000) * input_rate + (output_tokens / 1000) * output_rate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_budget.py -v`
Expected: PASS (5 tests skip with "requires TEST_DATABASE_URL" locally, all
run in CI's `db-tests` job; the two non-db tests —
`test_model_for_tier_maps_full_to_sonnet_and_cheap_to_haiku`,
`test_estimate_cost_uses_cited_per_model_rates`,
`test_budget_settings_raises_when_env_missing` — run and pass locally.)

Fix the `estimate_cost` call signature mismatch in the test above if
`ruff`/`mypy` flags positional-vs-keyword args — the implementation uses
keyword-only `input_tokens`/`output_tokens` intentionally (readability at
call sites with two same-typed int args); update the test call to
`estimate_cost("claude-sonnet-5", input_tokens=1_000_000,
output_tokens=1_000_000)` if not already matching (it is, above).

- [ ] **Step 5: Run ruff + mypy**

Run: `ruff check prometheus/research/llm/ tests/test_llm_budget.py && mypy prometheus/research/llm/budget.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add prometheus/research/llm/__init__.py prometheus/research/llm/budget.py tests/test_llm_budget.py
git commit -m "feat(llm): add budget.py -- monthly spend cap, Sonnet/Haiku tiers"
```

---

## Task 3: `research/llm/ingestion.py`

**Files:**
- Create: `prometheus/research/llm/ingestion.py`
- Test: `tests/test_llm_ingestion.py`

**Interfaces:**
- Consumes: `ResearchPaper` (Task 1).
- Produces: `ArxivPaper` (dataclass: `arxiv_id, title, abstract, pdf_url`),
  `async def search_arxiv(query: str, max_results: int) -> list[ArxivPaper]`,
  `async def ingest_paper(session: AsyncSession, arxiv_id: str) ->
  ResearchPaper`. Task 5 (worker integration) calls both.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_llm_ingestion.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
        patch("prometheus.research.llm.ingestion._download_pdf", new=AsyncMock(return_value=b"%PDF-fake")),
        patch("prometheus.research.llm.ingestion._extract_full_text", return_value=_FAKE_PDF_TEXT),
        patch("prometheus.research.llm.ingestion._fetch_arxiv_metadata", new=AsyncMock(
            return_value={"title": "Momentum Study", "abstract": "This paper studies momentum."}
        )),
        patch("prometheus.research.llm.ingestion._call_grobid", new=AsyncMock(return_value=_FAKE_TEI_XML)),
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
        patch("prometheus.research.llm.ingestion._download_pdf", new=AsyncMock(return_value=b"%PDF-fake")),
        patch("prometheus.research.llm.ingestion._extract_full_text", return_value=_FAKE_PDF_TEXT),
        patch("prometheus.research.llm.ingestion._fetch_arxiv_metadata", new=AsyncMock(
            return_value={"title": "Momentum Study", "abstract": "This paper studies momentum."}
        )),
        patch("prometheus.research.llm.ingestion._call_grobid", new=AsyncMock(return_value=_FAKE_TEI_XML)),
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


async def test_ingest_paper_falls_back_when_grobid_unreachable(db_session: AsyncSession) -> None:
    with (
        patch("prometheus.research.llm.ingestion._download_pdf", new=AsyncMock(return_value=b"%PDF-fake")),
        patch("prometheus.research.llm.ingestion._extract_full_text", return_value=_FAKE_PDF_TEXT),
        patch("prometheus.research.llm.ingestion._fetch_arxiv_metadata", new=AsyncMock(
            return_value={"title": "Momentum Study", "abstract": "This paper studies momentum."}
        )),
        patch("prometheus.research.llm.ingestion._call_grobid", new=AsyncMock(side_effect=ConnectionError)),
    ):
        paper = await ingest_paper(db_session, "2401.00002")

    # Soft failure -- still a complete, storable row, not a raised exception.
    assert paper.arxiv_id == "2401.00002"
    assert paper.full_text == _FAKE_PDF_TEXT
    assert len(paper.key_sections) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_ingestion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prometheus.research.llm.ingestion'`

- [ ] **Step 3: Write the implementation**

```python
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

_ARXIV_API_BASE = "http://export.arxiv.org/api/query"
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
    outcomes rather than the other way around."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            _ARXIV_API_BASE,
            params={"search_query": query, "max_results": max_results},
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
        paragraphs = [p.text or "" for p in div.findall("tei:p", _TEI_NS)]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_ingestion.py -v`
Expected: the two `_extract_key_sections` tests PASS locally (no DB
needed); the three `ingest_paper` tests (idempotency, GROBID success,
GROBID fallback) skip locally (`requires TEST_DATABASE_URL`), run in
CI's `db-tests` job.

- [ ] **Step 5: Add `httpx` usage check and dependency**

`httpx` is already a dev-only dependency (`pyproject.toml`'s
`[project.optional-dependencies]`, used by `TestClient`) — this task
promotes it to a main runtime dependency since `ingestion.py` imports it
at runtime, not just in tests. Move `"httpx==0.27.2"` from the dev/test
extra into the main `dependencies = [...]` list in `pyproject.toml`, and
update its `docs/DEPENDENCIES.md` row to note the new runtime use
alongside its existing `TestClient`-only justification.

- [ ] **Step 6: Run ruff + mypy**

Run: `ruff check prometheus/research/llm/ingestion.py tests/test_llm_ingestion.py && mypy prometheus/research/llm/ingestion.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add prometheus/research/llm/ingestion.py tests/test_llm_ingestion.py pyproject.toml docs/DEPENDENCIES.md
git commit -m "feat(llm): add ingestion.py -- arXiv fetch + GROBID section extraction"
```

---

## Task 4: `research/llm/hypothesis.py` + holdout-safety test

**Files:**
- Create: `prometheus/research/llm/hypothesis.py`
- Test: `tests/test_llm_hypothesis.py`
- Test: `tests/test_llm_hypothesis_holdout_safety.py`

**Interfaces:**
- Consumes: `StrategySpec`, `FAMILIES` (`prometheus.strategy.spec`);
  `budget.estimate_cost` (Task 2).
- Produces: `PaperContext` (dataclass: `paper_id: int, key_sections: str`),
  `LLMHypothesis` (dataclass: `spec: StrategySpec, hypothesis_text: str,
  expected_effect: str, paper_ids: list[int], model: str, input_tokens: int,
  output_tokens: int, est_cost_usd: float`), `async def generate_hypothesis
  (client, model: str, symbol: str, timeframe: str, paper_context:
  list[PaperContext]) -> LLMHypothesis`. Task 5 (worker) calls this and
  persists the result.

- [ ] **Step 1: Write the holdout-safety structural test (write first — it
  encodes the actual safety property before any implementation exists to
  accidentally violate it)**

```python
"""tests/test_llm_hypothesis_holdout_safety.py -- Law 3. Structural, not a
runtime mock: proves research/llm/hypothesis.py has NO import of anything
that could open a holdout connection, so there is no code path to miss,
not just no path this test happened to exercise."""
from __future__ import annotations

import ast
from pathlib import Path

_HYPOTHESIS_MODULE_PATH = Path("prometheus/research/llm/hypothesis.py")

_FORBIDDEN_MODULES = {
    "prometheus.validation.holdout",
    "prometheus.core.db",
}


def test_hypothesis_module_imports_nothing_that_can_reach_holdout() -> None:
    tree = ast.parse(_HYPOTHESIS_MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_hit = imported_modules & _FORBIDDEN_MODULES
    assert not forbidden_hit, (
        f"research/llm/hypothesis.py imports {forbidden_hit} -- this module "
        "must never be able to reach validation.holdout.access_holdout or "
        "open a raw DB session (Law 3)"
    )


def test_generate_hypothesis_signature_takes_no_session_parameter() -> None:
    tree = ast.parse(_HYPOTHESIS_MODULE_PATH.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_hypothesis"
    )
    param_names = {arg.arg for arg in func.args.args}
    assert "session" not in param_names
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_hypothesis_holdout_safety.py -v`
Expected: FAIL — `FileNotFoundError` (module doesn't exist yet).

- [ ] **Step 3: Write the hypothesis-generation tests**

```python
"""tests/test_llm_hypothesis.py"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from prometheus.research.llm.hypothesis import PaperContext, generate_hypothesis

_VALID_RESPONSE_JSON = json.dumps(
    {
        "family": "MOMENTUM",
        "fast_window": 10,
        "slow_window": 50,
        "expected_horizon": 5,
        "hypothesis_text": "Faster momentum crossovers may capture short-term trend continuation.",
        "expected_effect": "Higher turnover, similar or better risk-adjusted return.",
    }
)

_MALFORMED_RESPONSE_JSON = json.dumps(
    {
        "family": "MOMENTUM",
        "fast_window": 50,
        "slow_window": 10,  # invalid: slow_window must exceed fast_window
        "expected_horizon": 5,
        "hypothesis_text": "bad",
        "expected_effect": "bad",
    }
)


def _mock_client(response_text: str, *, input_tokens: int = 500, output_tokens: int = 200) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = [MagicMock(text=response_text)]
    message.usage.input_tokens = input_tokens
    message.usage.output_tokens = output_tokens
    client.messages.create.return_value = message
    return client


async def test_generate_hypothesis_produces_valid_spec() -> None:
    client = _mock_client(_VALID_RESPONSE_JSON)
    result = await generate_hypothesis(
        client, "claude-sonnet-5", "BTC/USDT", "1d",
        [PaperContext(paper_id=1, key_sections="momentum literature review")],
    )
    assert result.spec.family == "MOMENTUM"
    assert result.spec.fast_window == 10
    assert result.spec.slow_window == 50
    assert result.spec.source == "llm_hypothesis"
    assert result.paper_ids == [1]
    assert result.input_tokens == 500
    assert result.output_tokens == 200
    assert result.est_cost_usd > 0


async def test_generate_hypothesis_raises_on_invalid_spec_rather_than_coercing() -> None:
    client = _mock_client(_MALFORMED_RESPONSE_JSON)
    with pytest.raises(ValueError):
        await generate_hypothesis(
            client, "claude-sonnet-5", "BTC/USDT", "1d",
            [PaperContext(paper_id=1, key_sections="momentum literature review")],
        )
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_llm_hypothesis.py -v`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 5: Write the implementation**

```python
"""prometheus/research/llm/hypothesis.py -- PROMPT 9's LLM hypothesis
generator. NO function here takes a database session -- Law 3 requires
this module to be structurally incapable of opening
validation.holdout.access_holdout() or evaluating its own output
(tests/test_llm_hypothesis_holdout_safety.py enforces both properties by
static inspection, not by trusting a mock to catch every path).

Reuses the 3 EXISTING StrategySpec families (MOMENTUM/BOLLINGER/
VOL_BREAKOUT) -- no new DSL. A malformed LLM response fails
StrategySpec's own model_validator and raises; it is never silently
coerced into an invalid spec.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from prometheus.research.llm.budget import estimate_cost
from prometheus.strategy.spec import FAMILIES, StrategySpec

_SYSTEM_PROMPT = f"""You are a quantitative strategy research assistant.
Given research paper excerpts, propose ONE new trading strategy hypothesis
using EXACTLY one of these families: {", ".join(FAMILIES)}.

Respond with ONLY a JSON object with these exact keys:
- "family": one of {list(FAMILIES)}
- family-specific parameter fields (MOMENTUM: fast_window, slow_window;
  BOLLINGER: lookback_window, band_multiplier; VOL_BREAKOUT: breakout_window,
  exit_window)
- "expected_horizon": integer, bars ahead this signal is claimed to matter
- "hypothesis_text": a one-paragraph explanation grounded in the provided papers
- "expected_effect": what measurable effect you expect (e.g. "higher Sharpe",
  "lower drawdown") and why

No other text, no markdown fences, just the JSON object."""


@dataclass(frozen=True)
class PaperContext:
    paper_id: int
    key_sections: str


@dataclass(frozen=True)
class LLMHypothesis:
    spec: StrategySpec
    hypothesis_text: str
    expected_effect: str
    paper_ids: list[int]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class _AnthropicClientProtocol(Protocol):
    """Structural type for the Anthropic client -- lets tests pass a
    MagicMock without importing the real anthropic package's own types,
    and keeps this module's public signature honest about what it
    actually needs (a `.messages.create(...)` call), not the whole SDK."""

    messages: Any


def _build_user_prompt(symbol: str, timeframe: str, paper_context: list[PaperContext]) -> str:
    excerpts = "\n\n".join(
        f"[Paper {p.paper_id}]\n{p.key_sections}" for p in paper_context
    )
    return (
        f"Symbol: {symbol}\nTimeframe: {timeframe}\n\n"
        f"Research excerpts:\n{excerpts}"
    )


async def generate_hypothesis(
    client: _AnthropicClientProtocol,
    model: str,
    symbol: str,
    timeframe: str,
    paper_context: list[PaperContext],
) -> LLMHypothesis:
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(symbol, timeframe, paper_context)}],
    )
    raw_text = message.content[0].text
    parsed = json.loads(raw_text)

    family = parsed["family"]
    param_fields = {
        "MOMENTUM": ("fast_window", "slow_window"),
        "BOLLINGER": ("lookback_window", "band_multiplier"),
        "VOL_BREAKOUT": ("breakout_window", "exit_window"),
    }[family]
    params = {field: parsed[field] for field in param_fields}

    # StrategySpec's own model_validator raises ValueError on an invalid
    # combination (e.g. slow_window <= fast_window) -- deliberately not
    # caught here, so a malformed LLM response surfaces as a real error
    # to the caller rather than being silently dropped or coerced.
    spec = StrategySpec(
        family=family,
        symbol=symbol,
        timeframe=timeframe,
        expected_horizon=parsed["expected_horizon"],
        source="llm_hypothesis",
        description=parsed["hypothesis_text"],
        **params,
    )

    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    return LLMHypothesis(
        spec=spec,
        hypothesis_text=parsed["hypothesis_text"],
        expected_effect=parsed["expected_effect"],
        paper_ids=[p.paper_id for p in paper_context],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(model, input_tokens=input_tokens, output_tokens=output_tokens),
    )
```

- [ ] **Step 6: Run all three test files to verify they pass**

Run: `pytest tests/test_llm_hypothesis.py tests/test_llm_hypothesis_holdout_safety.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 7: Add the `anthropic` dependency**

Add `"anthropic==1.6.0"` to `pyproject.toml`'s `dependencies = [...]` list.
Add a `docs/DEPENDENCIES.md` row: purpose "PROMPT 9's LLM hypothesis
generation (research/llm/hypothesis.py)", replaces "no prior LLM
integration existed", why not stdlib "stdlib has no HTTP client suited to
a typed streaming API surface, and hand-rolling the Messages API's
request/response shapes would just be a worse reimplementation of the
official SDK."

- [ ] **Step 8: Run ruff + mypy**

Run: `ruff check prometheus/research/llm/hypothesis.py tests/test_llm_hypothesis.py tests/test_llm_hypothesis_holdout_safety.py && mypy prometheus/research/llm/hypothesis.py`
Expected: both clean.

- [ ] **Step 9: Commit**

```bash
git add prometheus/research/llm/hypothesis.py tests/test_llm_hypothesis.py tests/test_llm_hypothesis_holdout_safety.py pyproject.toml docs/DEPENDENCIES.md
git commit -m "feat(llm): add hypothesis.py -- Anthropic-backed strategy hypotheses, no DB access"
```

---

## Task 5: Worker integration

**Files:**
- Modify: `prometheus/worker.py`
- Test: `tests/test_worker_llm_integration.py`

**Interfaces:**
- Consumes: `budget.current_tier`, `budget.model_for_tier` (Task 2);
  `ingestion.search_arxiv`, `ingestion.ingest_paper` (Task 3);
  `hypothesis.generate_hypothesis`, `hypothesis.PaperContext` (Task 4);
  `_enqueue_child`, `is_due`, `mark_run` (existing, `prometheus/worker.py`).
- Produces: `_run_llm_hypothesis_step(session, client) -> str | None`
  (returns the enqueued job id, or `None` if halted/no papers/generation
  failed) — called from `_run_research()`. `_run_llm_ingestion() ->
  list[str]` (returns ingested arxiv_ids) — a NEW cadence-gated concern
  in `run_once()`, separate from `research`'s 30-min cadence, since paper
  ingestion (PDF download + GROBID call) is comparatively expensive and
  papers don't change fast enough to justify checking every cycle.
  Without this step, `research_papers` stays empty forever in
  production and `_run_llm_hypothesis_step` never has any papers to work
  with — this is the piece that actually calls Task 3's `ingestion.py`,
  which otherwise has no production caller at all.

- [ ] **Step 1: Read the exact insertion point**

Read `prometheus/worker.py`'s `_run_research()` (lines 256-298),
`_run_evolution_step`/`_enqueue_child` (lines 139-244), `_run_ingest()`
(lines 247-253), and `run_once()`'s full cadence-gating block (lines
405-467) before editing — the new hypothesis step reuses
`_enqueue_child`'s exact shape, and the new ingestion concern reuses
`_run_ingest()`'s exact no-session shape plus `run_once()`'s exact
is_due/mark_run/try-except pattern for wiring in a fourth concern.

- [ ] **Step 2: Write the failing test**

```python
"""tests/test_worker_llm_integration.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.hypothesis import LLMHypothesis
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import _run_llm_hypothesis_step

pytestmark = pytest.mark.db


def _fake_hypothesis() -> LLMHypothesis:
    spec = StrategySpec(
        family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5,
        source="llm_hypothesis", description="test hypothesis",
    )
    return LLMHypothesis(
        spec=spec, hypothesis_text="test", expected_effect="test",
        paper_ids=[1], model="claude-sonnet-5",
        input_tokens=100, output_tokens=50, est_cost_usd=0.001,
    )


async def test_llm_step_enqueues_job_and_logs_usage_when_full_tier(db_session: AsyncSession) -> None:
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.model_for_tier", return_value="claude-sonnet-5"),
        patch("prometheus.worker.search_arxiv", new=AsyncMock(return_value=[])),
        patch("prometheus.worker._select_recent_papers", new=AsyncMock(return_value=[
            MagicMock(id=1, key_sections="momentum literature")
        ])),
        patch("prometheus.worker.generate_hypothesis", new=AsyncMock(return_value=_fake_hypothesis())),
    ):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())

    assert job_id is not None
    usage_row = (
        await db_session.execute(text("SELECT model FROM llm_usage WHERE model = 'claude-sonnet-5'"))
    ).first()
    assert usage_row is not None
    hypothesis_row = (
        await db_session.execute(text("SELECT hypothesis_text FROM llm_hypotheses"))
    ).first()
    assert hypothesis_row is not None


async def test_llm_step_does_nothing_when_halted(db_session: AsyncSession) -> None:
    with patch("prometheus.worker.current_tier", new=AsyncMock(return_value="halted")):
        job_id = await _run_llm_hypothesis_step(db_session, client=MagicMock())
    assert job_id is None


async def test_llm_ingestion_calls_ingest_paper_for_each_search_result(db_session: AsyncSession) -> None:
    from contextlib import asynccontextmanager

    from prometheus.research.llm.ingestion import ArxivPaper
    from prometheus.worker import _run_llm_ingestion

    fake_paper = ArxivPaper(
        arxiv_id="2401.00099", title="Fake Paper", abstract="fake abstract",
        pdf_url="https://arxiv.org/pdf/2401.00099",
    )

    @asynccontextmanager
    async def _fake_get_session():
        # _run_llm_ingestion opens its own session via get_session()
        # (matching _run_ingest's shape, see the implementation below) --
        # patched here to hand it the test's own db_session so the
        # inserted rows are visible to assertions in the SAME
        # transaction, same technique this test file needs precisely
        # because that function takes no session parameter.
        yield db_session

    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch("prometheus.worker.search_arxiv", new=AsyncMock(return_value=[fake_paper])),
        patch("prometheus.worker.ingest_paper", new=AsyncMock(
            return_value=MagicMock(arxiv_id="2401.00099")
        )) as mock_ingest,
    ):
        ingested = await _run_llm_ingestion()

    assert ingested == ["2401.00099"]
    mock_ingest.assert_awaited_once_with(db_session, "2401.00099")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_worker_llm_integration.py -v`
Expected: FAIL — `ImportError: cannot import name '_run_llm_hypothesis_step'`

- [ ] **Step 4: Implement the worker integration**

Modify `prometheus/worker.py`. Add imports (alongside the existing
`from prometheus.research...` imports, same block):

```python
from prometheus.research.llm.budget import current_tier, model_for_tier
from prometheus.research.llm.hypothesis import PaperContext, generate_hypothesis
from prometheus.research.llm.ingestion import ingest_paper, search_arxiv
```

Add near the top-level constants (alongside `_EVOLUTION_EXPLOITATION_PARENTS`):

```python
# One bounded LLM hypothesis per research cycle -- same "bounded work per
# tick" reasoning as _EVOLUTION_EXPLOITATION_PARENTS/_EVOLUTION_EXPLORATION_
# PARENTS above, not a statistical choice. Fixed arXiv category filter
# (Quantitative Finance), never a query derived from strategy state --
# ingestion must not depend on research outcomes.
_LLM_ARXIV_QUERY = "cat:q-fin.*"
_LLM_RECENT_PAPERS_LIMIT = 3
_LLM_SYMBOL = "BTC/USDT"
_LLM_INGESTION_MAX_RESULTS = 5

# Ingestion (PDF download + GROBID call) is comparatively expensive and
# papers don't change fast enough to justify checking every 30-min
# research cycle -- a separate, coarser worker_cadence concern, same
# "different concerns, different rates from one entrypoint" pattern
# ingest/research/paper already use. Daily, not weekly: arXiv publishes
# new quant-finance papers daily, and a $0-idle scale-to-zero GROBID
# service means checking daily costs nothing when there's nothing new.
_LLM_INGESTION_INTERVAL_SECONDS = 86400.0  # daily
```

Add near `_SELECT_STRATEGY_FILLED_ORDER_IDS` (a private query constant,
same section style):

```python
_SELECT_RECENT_PAPERS = text(
    "SELECT id, key_sections FROM research_papers ORDER BY ingested_at DESC LIMIT :limit"
)


async def _select_recent_papers(session: AsyncSession, limit: int) -> list[PaperContext]:
    rows = (await session.execute(_SELECT_RECENT_PAPERS, {"limit": limit})).fetchall()
    return [PaperContext(paper_id=r.id, key_sections=r.key_sections) for r in rows]
```

Add the step function (after `_run_evolution_step`, before `_run_paper`):

```python
_INSERT_LLM_USAGE = text(
    """
    INSERT INTO llm_usage (model, input_tokens, output_tokens, est_cost_usd, purpose)
    VALUES (:model, :input_tokens, :output_tokens, :est_cost_usd, :purpose)
    """
)
_INSERT_LLM_HYPOTHESIS = text(
    """
    INSERT INTO llm_hypotheses
        (strategy_fingerprint, paper_ids, hypothesis_text, expected_effect,
         model, input_tokens, output_tokens, est_cost_usd)
    VALUES
        (:strategy_fingerprint, :paper_ids, :hypothesis_text, :expected_effect,
         :model, :input_tokens, :output_tokens, :est_cost_usd)
    """
).bindparams(bindparam("paper_ids", type_=JSONB))


async def _run_llm_ingestion() -> list[str]:
    """The daily-cadence concern that actually populates research_papers
    -- without this, ingestion.py has no production caller and
    research_papers stays empty forever, starving
    _run_llm_hypothesis_step of any context to work with. Fixed arXiv
    category query, never derived from strategy/research state (see
    ingestion.search_arxiv's own docstring). ingest_paper is idempotent
    on arxiv_id, so re-discovering an already-ingested paper in a later
    search is a safe no-op, not a duplicate.

    Takes no session parameter and manages its own -- same shape as
    _run_ingest() above (backfill() manages its own session
    internally), not _run_research()/_run_paper()'s shape (which open
    their own sessions per internal step). One session for this whole
    concern is enough: ingestion has no cross-step state that needs
    isolating the way research's grid/validate/evolve steps do."""
    candidates = await search_arxiv(_LLM_ARXIV_QUERY, _LLM_INGESTION_MAX_RESULTS)
    ingested: list[str] = []
    async with get_session() as session:
        for candidate in candidates:
            paper = await ingest_paper(session, candidate.arxiv_id)
            ingested.append(paper.arxiv_id)
        await session.commit()
    return ingested


async def _run_llm_hypothesis_step(session: AsyncSession, *, client: object) -> str | None:
    """One bounded LLM hypothesis per research cycle, gated by budget.
    current_tier(). Deterministic generation (grid + evolution, see
    _run_research below) is completely separate code and is never gated
    on this -- a halted LLM budget stops exactly this function, nothing
    else. Returns the enqueued run_backtest job id, or None if halted, no
    papers are available yet, or the LLM's response failed StrategySpec
    validation (an honest 'no hypothesis this cycle', not a crashed
    worker cycle)."""
    tier = await current_tier(session)
    if tier == "halted":
        return None

    papers = await _select_recent_papers(session, _LLM_RECENT_PAPERS_LIMIT)
    if not papers:
        return None

    model = model_for_tier(tier)
    try:
        result = await generate_hypothesis(client, model, _LLM_SYMBOL, _TIMEFRAME, papers)
    except (ValueError, KeyError) as exc:
        print(f"worker: LLM hypothesis generation produced an invalid spec, skipping: {exc}")
        return None

    await session.execute(
        _INSERT_LLM_USAGE,
        {
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "est_cost_usd": result.est_cost_usd,
            "purpose": "hypothesis_generation",
        },
    )
    await session.execute(
        _INSERT_LLM_HYPOTHESIS,
        {
            "strategy_fingerprint": result.spec.config_hash(),
            "paper_ids": result.paper_ids,
            "hypothesis_text": result.hypothesis_text,
            "expected_effect": result.expected_effect,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "est_cost_usd": result.est_cost_usd,
        },
    )

    return await _enqueue_child(
        session,
        child=result.spec,
        parent_experiment_id=None,
        hypothesis=result.hypothesis_text,
        change_set={"mutation_type": "LLM_HYPOTHESIS", "field": "family", "old_value": None, "new_value": result.spec.family},
        expected_information_value_=0.0,
    )
```

Add the required `bindparam`/`JSONB` imports at the top of `worker.py`
(check the existing import block — `sqlalchemy.text` is already imported;
add `bindparam` to that same line, and `from sqlalchemy.dialects.postgresql
import JSONB` as a new line, matching `ablation.py`'s own import style for
the identical pattern).

Wire it into `_run_research()` — add after the existing evolution-step
block, before the `return ran + validated` line:

```python
    # PROMPT 9: one bounded LLM hypothesis, budget-gated. Anthropic client
    # construction is deferred to run_once() (see below) so this function
    # stays testable without a real API key in every test that imports it.
    llm_job_id = await _run_llm_hypothesis_step(session, client=_anthropic_client())
    if llm_job_id is not None:
        print(f"worker: enqueued LLM hypothesis job: {llm_job_id}")
```

(This runs inside the `async with get_session() as session:` block that
already wraps the evolution step — reuse that same session, do not open a
new one.)

Wire `_run_llm_ingestion` into `run_once()` as a fourth cadence-gated
concern, following the EXACT existing pattern for `ingest`/`research`/
`paper` (lines 425-467 — read this block in full before editing; note
that `_run_ingest()` also takes no session parameter and manages its own
internally via `backfill()`, the same shape `_run_llm_ingestion` uses,
and its own `mark_run` call afterward always opens a SEPARATE fresh
session — that is the pattern to match exactly, not a session shared
between the work and the cadence-stamp). Add to the `is_due` block
(alongside `ingest_due`/`research_due`/`paper_due`):

```python
        llm_ingestion_due = await is_due(
            session, concern="llm_ingestion", interval_seconds=_LLM_INGESTION_INTERVAL_SECONDS
        )
```

And its own isolated try/except block, placed after the existing
`paper_due` block, before `return ran`:

```python
    if llm_ingestion_due:
        try:
            ingested = await _run_llm_ingestion()
            async with get_session() as session:
                await mark_run(session, concern="llm_ingestion")
            if ingested:
                print(f"worker: ingested {len(ingested)} paper(s): {ingested}")
        except Exception as exc:
            print(f"worker: llm_ingestion concern failed: {exc!r}")
```

Add the client constructor near the top of the file (after imports):

```python
def _anthropic_client() -> object:
    """Constructed lazily, once per worker cycle -- not at import time,
    so importing worker.py (e.g. from tests) never requires
    ANTHROPIC_API_KEY to be set. Returns `object` in this module's own
    type surface deliberately: worker.py does not need to know the real
    anthropic.Anthropic type, only that hypothesis.generate_hypothesis
    accepts whatever this returns (see hypothesis.py's own
    _AnthropicClientProtocol)."""
    import anthropic

    return anthropic.Anthropic()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_worker_llm_integration.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 6: Run the full existing test suite to confirm no regression**

Run: `pytest -q`
Expected: same pass/skip/xfail counts as before this task, plus the new
tests — no existing test broken by the `worker.py` edit.

- [ ] **Step 7: Run ruff + mypy**

Run: `ruff check prometheus/worker.py tests/test_worker_llm_integration.py`
Expected: clean. (mypy is not required on `worker.py` — outside CI's
`core/`+`validation/` scope — but run it anyway for your own confidence:
`mypy prometheus/worker.py`, non-blocking.)

- [ ] **Step 8: Commit**

```bash
git add prometheus/worker.py tests/test_worker_llm_integration.py
git commit -m "feat(llm): wire budget-gated LLM hypothesis step into worker's research cycle"
```

---

## Task 6: Ablation registration — `register_llm_component`

**Files:**
- Modify: `prometheus/experiments/ablation.py`
- Test: `tests/test_ablation_llm_component.py`

**Interfaces:**
- Consumes: `record_trial`, `_recompute_registry` (existing, same file);
  `run_backtest`, `load_point_in_time`, `FAMILIES`, `StrategySpec`
  (existing imports already in `ablation.py`).
- Produces: `async def register_llm_component(session, *, symbols:
  list[str], timeframe: str, start: datetime, end: datetime, version:
  str, cost_model: CostModel = apply_cost) -> BatchResult`.

- [ ] **Step 1: Read `register_evolution_component` in full**

Read `prometheus/experiments/ablation.py` lines 545-631 (already shown in
this session) — `register_llm_component` mirrors its exact shape: per
symbol, score the best baseline-grid spec and the best candidate spec
(here: best LLM-sourced spec instead of best evolved spec), record one
paired trial, recompute the registry.

- [ ] **Step 2: Write the failing test**

No existing test covers `register_evolution_component` either — this is a
new test written from the established db-test conventions
(`tests/test_paper_ids.py`'s `db_session` fixture usage), not a mirror of
a pre-existing one.

```python
"""tests/test_ablation_llm_component.py"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.ablation import register_llm_component
from prometheus.strategy.spec import StrategySpec

pytestmark = pytest.mark.db


async def _seed_llm_strategy(session: AsyncSession, *, strategy_id: str, symbol: str) -> None:
    spec = StrategySpec(
        family="MOMENTUM", symbol=symbol, timeframe="1d",
        fast_window=5, slow_window=20, expected_horizon=5,
        source="llm_hypothesis", description="seeded for ablation test",
    )
    # Spec JSON embedded literally in the query text, not bound as a
    # parameter -- matches this codebase's own established pattern for
    # seeding strategies.spec (a JSONB column) in tests
    # (tests/test_paper_divergence.py's _seed_strategy), avoiding a
    # driver-level jsonb-cast-from-bound-string question entirely. Safe
    # here: spec.model_dump_json()'s content is fully controlled test
    # fixture data, not external input.
    await session.execute(
        text(
            f"INSERT INTO strategies (id, family, spec, status) "
            f"VALUES (:id, :family, '{spec.model_dump_json()}', 'pending')"
        ),
        {"id": strategy_id, "family": spec.family},
    )
    await session.commit()


async def test_register_llm_component_produces_a_real_verdict(
    db_session: AsyncSession,
) -> None:
    await _seed_llm_strategy(db_session, strategy_id="MOMENTUM-900", symbol="BTC/USDT")
    result = await register_llm_component(
        db_session,
        symbols=["BTC/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.component == "llm_generation"
    assert result.verdict in {"UNPROVEN", "VALUABLE", "NEUTRAL", "HARMFUL"}


async def test_register_llm_component_with_no_llm_strategies_is_unproven(
    db_session: AsyncSession,
) -> None:
    result = await register_llm_component(
        db_session,
        symbols=["ETH/USDT"],
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        version="v1",
    )
    assert result.verdict == "UNPROVEN"
    assert result.n_experiments == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ablation_llm_component.py -v`
Expected: FAIL — `ImportError: cannot import name 'register_llm_component'`

- [ ] **Step 4: Implement `register_llm_component`**

Modify `prometheus/experiments/ablation.py` — add after
`register_evolution_component` (after line 631), before
`pairwise_interactions`:

```python
_SELECT_LLM_SPECS_FOR_SYMBOL = text(
    "SELECT spec FROM strategies WHERE symbol = :symbol AND spec->>'source' = 'llm_hypothesis'"
)


async def register_llm_component(
    session: AsyncSession,
    *,
    symbols: list[str],
    timeframe: str,
    start: datetime,
    end: datetime,
    version: str,
    cost_model: CostModel = apply_cost,
) -> BatchResult:
    """PROMPT 9: does the LLM hypothesis generator (research/llm/
    hypothesis.py) find anything the deterministic baseline grid
    (research/generate.generate_baseline_grid) doesn't, on real
    out-of-sample data. Same shape as register_evolution_component: per
    symbol, scores every baseline-grid spec and every LLM-sourced spec
    (spec.source == "llm_hypothesis", found directly in `strategies` --
    llm_hypotheses is provenance/audit only, never needed for scoring)
    with the real backtest engine, records one paired trial (enabled =
    best LLM score, disabled = best grid score) via record_trial, then
    reuses _recompute_registry for the real verdict -- reported honestly,
    including a NEUTRAL or HARMFUL one, and displayed prominently in the
    Temple of Knowledge either way via the existing component_registry ->
    world/projection.py wiring."""
    component = "llm_generation"
    n_trials = 0
    n_failed = 0

    def _score(pit: PointInTimeFrame, spec: StrategySpec) -> float | None:
        try:
            return run_backtest(pit, spec, end, cost_model=cost_model).total_return_pct
        except ValueError:
            return None

    for symbol in symbols:
        pit, _data_version_hash = await load_point_in_time(
            session, [symbol], timeframe, start, end
        )
        scored_grid = [
            (spec, score)
            for spec in generate_baseline_grid(symbol, timeframe)
            if (score := _score(pit, spec)) is not None
        ]
        llm_rows = (
            await session.execute(_SELECT_LLM_SPECS_FOR_SYMBOL, {"symbol": symbol})
        ).fetchall()
        llm_specs = [StrategySpec.model_validate(row.spec) for row in llm_rows]
        scored_llm = [
            (spec, score)
            for spec in llm_specs
            if (score := _score(pit, spec)) is not None
        ]
        if not scored_grid or not scored_llm:
            n_failed += 1
            continue

        _best_grid_spec, best_grid_score = max(scored_grid, key=lambda pair: pair[1])
        best_llm_spec, best_llm_score = max(scored_llm, key=lambda pair: pair[1])

        await record_trial(
            session,
            component=component,
            version=version,
            symbol=symbol,
            config_hash=best_llm_spec.config_hash(),
            seed=derive_seed(component, version, symbol),
            enabled_return_pct=best_llm_score,
            disabled_return_pct=best_grid_score,
        )
        n_trials += 1

    result = await _recompute_registry(
        session,
        component,
        version,
        list(FAMILIES),
        n_trials_this_batch=n_trials,
        n_failed_this_batch=n_failed,
    )
    await session.commit()
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ablation_llm_component.py -v`
Expected: PASS, both tests.

- [ ] **Step 6: Run the full existing ablation test suite**

Run: `pytest tests/test_ablation_registry.py tests/test_ablation_placebo.py tests/test_ablation_interactions.py tests/test_ablation_llm_component.py -v`
Expected: all PASS, no regression.

- [ ] **Step 7: Run ruff + mypy**

Run: `ruff check prometheus/experiments/ablation.py tests/test_ablation_llm_component.py`
Expected: clean. (`ablation.py` is outside CI's mypy scope too — run for
confidence, non-blocking: `mypy prometheus/experiments/ablation.py`.)

- [ ] **Step 8: Commit**

```bash
git add prometheus/experiments/ablation.py tests/test_ablation_llm_component.py
git commit -m "feat(llm): register_llm_component -- ablate LLM hypotheses against the grid baseline"
```

---

## Task 7: Documentation — DEPENDENCIES.md, DEFERRED.md, Railway GROBID service

**Files:**
- Modify: `docs/DEPENDENCIES.md`
- Modify: `docs/DEFERRED.md`

**Interfaces:**
- Consumes: nothing (documentation-only task; the `anthropic`/`httpx`
  rows were already added in Tasks 3/4 — this task adds `pypdf` and
  documents the GROBID/VibeQuant findings).

- [ ] **Step 1: Add the `pypdf` row to `docs/DEPENDENCIES.md`**

Add a row to the dependency table (alongside `pillow`/`numpy`'s existing
rows, same table):

```markdown
| pypdf | 6.19.0 | Full-text extraction from downloaded arXiv PDFs (`research/llm/ingestion.py`) -- archival `full_text` storage and the fallback path when GROBID is unreachable. | Hand-rolled PDF parsing | stdlib has no PDF codec at all. Pure-Python, permissive (BSD-3-Clause) license, no compiled-extension risk -- simpler and lighter than PyMuPDF (AGPL-licensed) for this project's needs, which don't require PyMuPDF's layout-precision. |
```

- [ ] **Step 2: Document GROBID and the VibeQuant non-finding**

Add a new prose entry after the existing "PixelLab character import"
entry, before "Isometric math attribution" (matching that section's
existing narrative-entry style, not the tabular dependency rows above —
GROBID is infrastructure, not a Python package this repo imports):

```markdown
**GROBID for paper section extraction, VibeQuant does not exist as
claimed (2026-09-18):** PROMPTS.md PROMPT 9 names "VibeQuant" as a
reference for arXiv/paper extraction ideas. Web search found several
small, unrelated repos sharing that name (a `yfinance`-wrapping finance
analysis library, a couple of near-empty forks) -- none has any
paper/PDF extraction functionality, the same "named repo doesn't fit
reality" outcome already documented for Qubx (PROMPT 8). Instead,
`kermitt2/grobid` (5.1k GitHub stars, Apache 2.0) was evaluated and
adopted: a real, production-proven ML-based structured-extraction tool
for exactly this job (title/abstract/section segmentation from scientific
PDFs), used in production by ResearchGate, CERN, and Mendeley among
others. It is a Java service, not a Python library -- deployed as its own
Railway service with scale-to-zero enabled (configured directly in
Railway's dashboard; no committed config in this repo, same posture as
every other Railway-console-only setting) rather than an always-on third
service, keeping CLAUDE.md's "two always-on services + one worker" cost
target intact. `research/llm/ingestion.py` calls it over Railway's private
network (`GROBID_URL` env var) and falls back to `pypdf`-only extraction
if it's unreachable -- a soft failure, never a hard one.
```

- [ ] **Step 3: Add the AgentQuant/QuantEvolve deferral to `docs/DEFERRED.md`**

Add a new section (matching the file's existing `## PROMPT N (...)`
heading convention, placed after the most recent PROMPT 8 section):

```markdown
## PROMPT 9 (LLM research layer)

- **AgentQuant and QuantEvolve evaluation** — PROMPTS.md marks both
  optional ("Optionally evaluate AgentQuant and QuantEvolve as
  components"). Deferred, not evaluated: the core LLM hypothesis
  generator itself (`research/llm/hypothesis.py`) has no evidence yet
  that it beats the Prompt 7 deterministic baseline (its ablation
  verdict starts UNPROVEN, same honest starting state as every other
  component) — evaluating two more external repos before the simpler
  question is answered would be scope creep, same posture as the Qubx
  evaluation in Prompt 8. **Trigger:** if `register_llm_component`'s
  verdict reaches VALUABLE with enough experiments to be meaningful,
  revisit whether either repo's approach would extend that result
  further; if it stays NEUTRAL/HARMFUL/UNPROVEN indefinitely, there is no
  reason to evaluate either.
- **A general restricted DSL beyond the 3 existing `StrategySpec`
  families** — `strategy/spec.py`'s own docstring names a bigger surface
  (`features/signals/entry_rules/exit_rules/position_sizing/risk_rules`)
  as the eventual Prompt 9 target; this implementation reuses the 3
  existing families instead (see
  `docs/superpowers/specs/2026-09-18-llm-research-layer-design.md`'s own
  reasoning: prove the cheap version first, CLAUDE.md's own null
  hypothesis about LLM research). **Trigger:** revisit only if
  `llm_generation`'s ablation verdict is VALUABLE enough that expanding
  its expressiveness looks worth a whitelisted-grammar-plus-interpreter
  project of its own.
```

- [ ] **Step 4: Commit**

```bash
git add docs/DEPENDENCIES.md docs/DEFERRED.md
git commit -m "docs(llm): record pypdf, GROBID/VibeQuant findings, and DSL/AgentQuant deferrals"
```

---

## Final checkpoint (before finishing-a-development-branch)

- [ ] Run the full test suite: `pytest -q` — expect all previous
  pass/skip/xfail counts preserved plus every new test from Tasks 1-6.
- [ ] Run `ruff check .` — must be clean repo-wide (not just touched files
  — this plan's own Task history includes a real incident this session
  where an unrelated pre-existing lint break sat undetected on `main` for
  two pushes; check the whole repo, not just the diff).
- [ ] Run `mypy prometheus/core/ prometheus/validation/` — must be clean
  (CI's exact scope; this plan's new code lives outside it, but nothing
  in Tasks 1-6 should have touched `core/`/`validation/` files anyway
  except `core/db.py`'s three new model classes in Task 1 — verify those
  typecheck: `mypy prometheus/core/`).
- [ ] Confirm `GROBID_URL` and `LLM_MONTHLY_BUDGET_USD` are documented as
  required production env vars somewhere a deployer will see them (the
  spec doc and this plan both name them; add a one-line note to
  `docs/DEPENDENCIES.md`'s GROBID entry or a project README env-var list
  if one exists — check for one before adding a new file).
- [ ] Manual step for the user (like PROMPT 8's Railway cron change): spin
  up the GROBID service in Railway (official `lfoppiano/grobid` Docker
  image), enable scale-to-zero, set `GROBID_URL` on the api/worker
  services to its private-network address, and set
  `ANTHROPIC_API_KEY`/`LLM_MONTHLY_BUDGET_USD` — none of this is
  automatable from inside this repo.
- [ ] Whole-branch review per `superpowers:subagent-driven-development`'s
  final step (dispatch the most capable available model), covering:
  Law 3 enforcement end-to-end (not just the structural test — trace that
  nothing in Task 5's worker wiring ever passes a session anywhere near
  `hypothesis.py`), the `strategy_fingerprint` vs `strategy_id` join
  correctness in Task 6, and that `_run_llm_hypothesis_step`'s failure
  modes (no papers, invalid spec, halted budget) all degrade to "skip
  this cycle" rather than crashing `_run_research()`.

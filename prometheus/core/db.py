"""Async engine, session factory, and the ORM models for the
append-only history tables plus the id-counter table.

Column types here are spelled out explicitly (BigInteger, String(64),
DateTime(timezone=True)) rather than left to SQLAlchemy's default mapping
for bare `Mapped[int]` / `Mapped[datetime]`. alembic/env.py points
`target_metadata` at this metadata, so any drift between these models and
the DDL in alembic/versions/0002_* becomes a spurious autogenerate diff —
one that would propose narrowing BIGINT primary keys to INTEGER and
stripping timezone awareness, on tables Law 6 forbids correcting by UPDATE
afterwards.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    """Migration 0006 adds the lineage/reproducibility columns below, all
    nullable -- migration 0003's trigger forbids UPDATE, so rows written
    before 0006 can never be backfilled and read as lineage roots
    (parent_experiment_id IS NULL), which is true of them. New writes
    populate every column; see prometheus.experiments.runner.run_one.
    """

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )
    parent_experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    strategy_id: Mapped[str | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)
    data_version_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    code_sha: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    seed: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    compute_cost: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_set: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    raw_yaml: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class IdCounter(Base):
    __tablename__ = "id_counters"

    scope: Mapped[str] = mapped_column(primary_key=True)
    # Holds the LAST value issued, not literally "next" — core/ids.py's
    # upsert increments and returns in one statement, so the returned value
    # is the id suffix immediately. Column name kept to avoid migration churn.
    next_value: Mapped[int] = mapped_column(sa.BigInteger, default=0)


class Strategy(Base):
    """A strategy's current lifecycle state (PROMISING/REJECTED/... --
    mirrors frontend/src/mapping/stateToVisual.ts's StrategyState verbatim,
    never a UI-invented value). Deliberately mutable: migration 0003's
    append-only trigger names exactly experiments/results/decisions --
    `status` here is current state, not a history log, so it is not
    protected by that trigger and may be UPDATEd as a strategy's status
    changes."""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(primary_key=True)
    family: Mapped[str] = mapped_column(sa.String(32))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class BenchmarkEquity(Base):
    """The Law 8 buy-and-hold curve. Not append-only (same reasoning as
    Strategy above) -- a rerun legitimately upserts a date's value rather
    than accumulating duplicate history for what is a recomputed curve,
    not an event log."""

    __tablename__ = "benchmark_equity"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    # benchmark.universe_key() -- one curve per universe (migration 0018).
    universe_key: Mapped[str] = mapped_column(sa.String())
    date: Mapped[date] = mapped_column(sa.Date)
    equity: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class ConfigSnapshot(Base):
    """One row per distinct content of a tracked config file (deduplicated
    by the (path, content_hash) unique index, migration 0006) -- the
    substrate experiments.violations.UNIVERSE_CHANGED_AFTER_RESULTS needs
    to tell "the universe changed" from "we re-ran ingestion unchanged".
    Not trigger-protected: a snapshot table's job is deduplicated presence,
    not an event log.
    """

    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(sa.String(255))
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    """Deliberately mutable -- same exemption Strategy and BenchmarkEquity
    document above. status/attempts/progress_pct/claimed_by/heartbeat_at
    are current execution state, not a history log, so migration 0007
    does NOT add this table to migration 0003's append-only trigger set.
    The permanent record of a job that exhausted retries is
    JobDeadLetter, which prometheus.experiments.queue never UPDATEs.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    priority: Mapped[int] = mapped_column(sa.Integer)
    expected_information_value: Mapped[float] = mapped_column(sa.Float)
    estimated_cost: Mapped[float] = mapped_column(sa.Float)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(sa.Integer)
    run_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )
    claimed_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    agent_role: Mapped[str] = mapped_column(sa.String(16))
    current_stage: Mapped[str] = mapped_column(sa.String(16))
    next_stage: Mapped[str] = mapped_column(sa.String(16))
    progress_pct: Mapped[float] = mapped_column(sa.Float, default=0.0)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class JobDeadLetter(Base):
    __tablename__ = "jobs_dead_letter"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(sa.String(24))
    kind: Mapped[str] = mapped_column(sa.String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(sa.String(64))
    attempts: Mapped[int] = mapped_column(sa.Integer)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text)
    died_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class ResearchViolation(Base):
    """A Law 7 finding. INSERT-only by convention -- experiments.violations
    never UPDATEs or DELETEs a row here -- but not added to migration
    0003's trigger set, which names exactly experiments/results/decisions;
    see migration 0008 for why extending that list quietly would itself
    be the kind of thing Law 7 is suspicious of.
    """

    __tablename__ = "research_violations"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    violation_type: Mapped[str] = mapped_column(sa.String(64))
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class HoldoutAccessLog(Base):
    """Law 3's audit trail: one row per attempted access to the holdout
    vault, granted or not. Covered by Law 6's append-only trigger
    (migration 0010) -- an audit log that can be edited after the fact is
    not an audit log."""

    __tablename__ = "holdout_access_log"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    strategy_fingerprint: Mapped[str] = mapped_column(sa.String(64))
    granted: Mapped[bool] = mapped_column(sa.Boolean)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    accessed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class ValidationResult(Base):
    """One verdict per validated strategy. Row COUNT here is what flips
    the Oracle from SCAFFOLDING to ACTIVE (world/construction.py's
    manifest already names this table as oracle.activates_on) -- no
    world/projection.py change needed for that half of PROMPT 5."""

    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    strategy_fingerprint: Mapped[str] = mapped_column(sa.String(64))
    verdict: Mapped[str] = mapped_column(sa.String(32))
    score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    pbo: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    deflated_sharpe: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class AblationTrial(Base):
    """One paired A/B trial (component enabled vs disabled, same symbol/
    spec/seed/costs) -- migration 0011. INSERT-only by convention, same
    precedent as ResearchViolation: a measurement record, not a decision
    history, so not added to Law 6's append-only trigger set."""

    __tablename__ = "ablation_trials"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(sa.String(64))
    version: Mapped[str] = mapped_column(sa.String(32))
    symbol: Mapped[str] = mapped_column(sa.String(32))
    config_hash: Mapped[str] = mapped_column(sa.String(64))
    seed: Mapped[int] = mapped_column(sa.BigInteger)
    enabled_return_pct: Mapped[float] = mapped_column(sa.Float)
    disabled_return_pct: Mapped[float] = mapped_column(sa.Float)
    enabled_sharpe: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    disabled_sharpe: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    enabled_total_costs: Mapped[float] = mapped_column(sa.Float)
    disabled_total_costs: Mapped[float] = mapped_column(sa.Float)
    compute_cost_delta: Mapped[float] = mapped_column(sa.Float)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class ComponentRegistry(Base):
    """Current aggregate state per (component, version) -- recomputed
    from AblationTrial rows after every batch, not hand-maintained. Same
    mutability exemption as Strategy.status/Job (current state, not a
    log). Table name matches the frontend's already-written contract
    (stateToVisual.ts's ComponentVerdict) and world/construction.py's
    temple manifest entry."""

    __tablename__ = "component_registry"
    __table_args__ = (sa.UniqueConstraint("component", "version"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(sa.String(64))
    version: Mapped[str] = mapped_column(sa.String(32))
    families_affected: Mapped[list[str]] = mapped_column(JSONB, default=list)
    n_experiments: Mapped[int] = mapped_column(sa.Integer, default=0)
    mean_oos_improvement: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    median_oos_improvement: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    worst_oos_improvement: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    best_oos_improvement: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    ci_low: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    ci_high: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    metric: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    mean_cost_delta: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    mean_compute_cost_delta: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    failure_rate: Mapped[float] = mapped_column(sa.Float, default=0.0)
    verdict: Mapped[str] = mapped_column(sa.String(16), default="UNPROVEN")
    disabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


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


class PaperOrder(Base):
    """Mutable current-state table -- a fill UPDATEs this row, it is not
    an event log (same exemption as Strategy.status/Job)."""

    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    client_order_id: Mapped[str] = mapped_column(sa.String(64), unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(sa.String(32))
    side: Mapped[str] = mapped_column(sa.String(4))
    qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))
    status: Mapped[str] = mapped_column(default="SUBMITTED")
    expected_price: Mapped[float] = mapped_column(sa.Numeric(20, 8, asdecimal=False))
    expected_qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False))
    filled_qty: Mapped[float] = mapped_column(sa.Numeric(28, 8, asdecimal=False), default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(
        sa.Numeric(20, 8, asdecimal=False), nullable=True
    )
    event_time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )
    filled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class PaperFinding(Base):
    """Append-only by convention (Law 6-adjacent, same treatment as
    research_violations and ablation_trials -- see migration 0012's own
    docstring)."""

    __tablename__ = "paper_findings"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    finding_type: Mapped[str] = mapped_column(sa.String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


class WorkerCadence(Base):
    """Scheduling state for worker.py's cadence-gated concerns -- mutable,
    like Strategy.status, not a history log."""

    __tablename__ = "worker_cadence"

    concern: Mapped[str] = mapped_column(primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_holdout_engine: AsyncEngine | None = None
_holdout_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy: DATABASE_URL is only required once a caller actually needs
    the database, not at import time (tests/laws/ config tests must run
    with no Postgres available).
    """
    global _engine
    if _engine is None:
        database_url = os.environ["DATABASE_URL"]
        _engine = create_async_engine(database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def get_holdout_engine() -> AsyncEngine:
    """Same lazy pattern as get_engine(), a genuinely separate engine bound
    to HOLDOUT_DATABASE_URL -- the restricted, non-superuser role migration
    0010 creates. prometheus.validation.holdout.access_holdout() is the
    only caller; nothing else in the codebase should ever need this."""
    global _holdout_engine
    if _holdout_engine is None:
        holdout_url = os.environ["HOLDOUT_DATABASE_URL"]
        _holdout_engine = create_async_engine(holdout_url, pool_pre_ping=True)
    return _holdout_engine


def get_holdout_session_factory() -> async_sessionmaker[AsyncSession]:
    global _holdout_session_factory
    if _holdout_session_factory is None:
        _holdout_session_factory = async_sessionmaker(
            get_holdout_engine(), expire_on_commit=False
        )
    return _holdout_session_factory


@asynccontextmanager
async def get_holdout_session() -> AsyncIterator[AsyncSession]:
    async with get_holdout_session_factory()() as session:
        yield session

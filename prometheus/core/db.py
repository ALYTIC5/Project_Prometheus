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
    family: Mapped[str] = mapped_column(sa.String(16))
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


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


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

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
from datetime import datetime
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
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now()
    )


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

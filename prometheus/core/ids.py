"""Deterministic, collision-safe ID generation.

Concurrency safety comes from a single atomic upsert-increment statement
against id_counters — no explicit row locking, no read-then-write race.
Two concurrent callers against the same scope always get two different
values because the increment happens inside one atomic statement that
Postgres serializes per-row.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{4}-\d{6}$")
STRATEGY_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")
_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

_UPSERT_COUNTER = text(
    """
    INSERT INTO id_counters (scope, next_value)
    VALUES (:scope, 1)
    ON CONFLICT (scope) DO UPDATE SET next_value = id_counters.next_value + 1
    RETURNING next_value
    """
)


class IdSequenceExhausted(Exception):
    pass


async def next_experiment_id(session: AsyncSession, year: int | None = None) -> str:
    resolved_year = year if year is not None else datetime.now(UTC).year
    scope = f"experiment:{resolved_year}"
    result = await session.execute(_UPSERT_COUNTER, {"scope": scope})
    n = result.scalar_one()
    if n > 999_999:
        raise IdSequenceExhausted(f"experiment id sequence exhausted for {resolved_year}")
    exp_id = f"EXP-{resolved_year}-{n:06d}"
    await session.commit()
    return exp_id


async def next_strategy_id(session: AsyncSession, family: str) -> str:
    family = family.upper()
    if not _FAMILY_RE.match(family):
        raise ValueError(f"invalid strategy family: {family!r}")
    scope = f"strategy:{family}"
    result = await session.execute(_UPSERT_COUNTER, {"scope": scope})
    n = result.scalar_one()
    if n > 999:
        raise IdSequenceExhausted(f"strategy id sequence exhausted for family {family}")
    strategy_id = f"{family}-{n:03d}"
    await session.commit()
    return strategy_id

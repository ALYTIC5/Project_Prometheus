"""Deterministic, collision-safe ID generation.

Concurrency safety comes from a single atomic upsert-increment statement
against id_counters — no explicit row locking, no read-then-write race.
Two concurrent callers against the same scope always get two different
values because the increment happens inside one atomic statement that
Postgres serializes per-row.

These functions own their transaction and take no `session` argument.
Taking a caller's session and committing it inside here would flush and
persist whatever else the caller had pending — and since experiments,
results and decisions are append-only (Law 6 forbids UPDATE and DELETE),
prematurely-committed partial state could never be corrected, only
superseded. `engine.begin()` gives the counter increment its own short
transaction: committed on clean exit, rolled back on exception, and
touching nothing the caller owns. The atomicity property is unchanged;
only the ownership of the transaction is.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import text

from prometheus.core.db import get_engine

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


async def next_experiment_id(year: int | None = None) -> str:
    resolved_year = year if year is not None else datetime.now(UTC).year
    scope = f"experiment:{resolved_year}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    # Checked after the transaction closes, so an exhausting call still
    # commits its increment cleanly rather than rolling it back.
    if n > 999_999:
        raise IdSequenceExhausted(f"experiment id sequence exhausted for {resolved_year}")
    return f"EXP-{resolved_year}-{n:06d}"


async def next_strategy_id(family: str) -> str:
    family = family.upper()
    if not _FAMILY_RE.match(family):
        raise ValueError(f"invalid strategy family: {family!r}")
    scope = f"strategy:{family}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    if n > 999:
        raise IdSequenceExhausted(f"strategy id sequence exhausted for family {family}")
    return f"{family}-{n:03d}"

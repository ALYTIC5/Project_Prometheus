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
from datetime import UTC, date, datetime

from sqlalchemy import text

from prometheus.core.db import get_engine

EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{4}-\d{6}$")
STRATEGY_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}-\d{6}$")
JOB_ID_RE = re.compile(r"^JOB-\d{8}-\d{6}$")
PAPER_ORDER_ID_RE = re.compile(r"^PAPER-\d{8}-\d{6}$")
# Widened from [A-Z0-9]{1,9} (no underscore, 10 chars max) after a real
# bug: strategy.spec.FAMILY_VOL_BREAKOUT = "VOL_BREAKOUT" (12 chars, has
# an underscore) has never been a valid next_strategy_id() input since it
# was added -- ValueError: invalid strategy family: 'VOL_BREAKOUT',
# caught by CI's real-Postgres db-tests job, not locally (no local
# Postgres in this environment). Allows underscores and up to 20 chars,
# double the longest real FAMILIES entry today, not an unlimited pattern.
_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")

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
    """Widened from a 3-digit (999 total, ever) to a 6-digit (999,999
    total, ever) suffix -- same headroom next_job_id()/next_experiment_id()/
    next_paper_order_id() already use -- after a real production
    exhaustion: this counter is cumulative per family for the family's
    entire lifetime (not scoped per-day like next_job_id()), and the
    deterministic grid alone produces close to 1000 MOMENTUM strategies in
    one pass. It hit the old 999 cap on its very first run, and every
    later grid re-run, evolution mutation, and LLM hypothesis for that
    family failed at id generation -- before ever reaching a backtest --
    for every cycle since. 999/family/ever was never real headroom for a
    system meant to keep mutating and re-gridding indefinitely (PROMPT 7),
    the same lesson next_job_id()'s own docstring already recorded once
    for a different scope."""
    family = family.upper()
    if not _FAMILY_RE.match(family):
        raise ValueError(f"invalid strategy family: {family!r}")
    scope = f"strategy:{family}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    print(f"TEMP_DEBUG_CAP_CHECK n={n} cap=999999 family={family}")
    if n > 999_999:
        raise IdSequenceExhausted(f"strategy id sequence exhausted for family {family}")
    return f"{family}-{n:06d}"


async def next_job_id(day: date | None = None) -> str:
    """JOB-YYYYMMDD-NNNNNN, per docs/WORLD_MAPPING.md's reservation of the
    jobs table. Scoped per-day rather than per-year like experiments: a
    scheduled worker draining the queue every 30 minutes (PROMPTS.md
    PROMPT 7) can plausibly emit thousands of jobs a day.

    Widened from a 3-digit (999/day) to a 6-digit (999,999/day) suffix --
    same headroom next_experiment_id() already uses per year -- after a
    real production exhaustion: experiments.queue.enqueue() used to call
    this unconditionally before checking whether the job already existed
    (fixed separately), so a worker re-enqueuing an already-existing grid
    every 30-minute cycle burned a slot on every no-op re-enqueue and
    exhausted 999/day within hours. That bug is fixed at the call site,
    but 999/day was never real headroom for a growing universe in the
    first place -- this raises the actual ceiling too, not just patches
    the one caller that was hitting it fastest.
    """
    resolved_day = day if day is not None else datetime.now(UTC).date()
    scope = f"job:{resolved_day:%Y%m%d}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    if n > 999_999:
        raise IdSequenceExhausted(f"job id sequence exhausted for {resolved_day:%Y%m%d}")
    return f"JOB-{resolved_day:%Y%m%d}-{n:06d}"


async def next_paper_order_id(day: date | None = None) -> str:
    """PAPER-YYYYMMDD-NNNNNN, same per-day scoping and 6-digit headroom
    as next_job_id() -- a live champion polling every 15 minutes can
    plausibly submit or re-check many orders a day."""
    resolved_day = day if day is not None else datetime.now(UTC).date()
    scope = f"paper_order:{resolved_day:%Y%m%d}"
    async with get_engine().begin() as conn:
        result = await conn.execute(_UPSERT_COUNTER, {"scope": scope})
        n: int = result.scalar_one()
    if n > 999_999:
        raise IdSequenceExhausted(f"paper order id sequence exhausted for {resolved_day:%Y%m%d}")
    return f"PAPER-{resolved_day:%Y%m%d}-{n:06d}"

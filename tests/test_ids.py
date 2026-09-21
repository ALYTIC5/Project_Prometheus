"""core.ids.next_strategy_id() against real Postgres -- the id_counters
upsert-increment and the exhaustion boundary can't be verified without a
real sequence.

Marked `db` and skipped locally without TEST_DATABASE_URL, same convention
as test_population.py/test_queue_semantics.py. Every test uses its own
never-reused family (a fresh uuid4 suffix each time) so seeding
id_counters near a boundary can never collide with a real family's
durably-accumulating counter, or with another test run against the same
database.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from prometheus.core.ids import IdSequenceExhausted, next_strategy_id

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0011 applied)",
    ),
]


def _fresh_family() -> str:
    return f"ZTESTCAP{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


async def test_next_strategy_id_uses_six_digit_suffix(engine: AsyncEngine) -> None:
    family = _fresh_family()
    assert await next_strategy_id(family) == f"{family}-000001"


async def test_next_strategy_id_survives_the_old_three_digit_cap(engine: AsyncEngine) -> None:
    """Real production bug: the old cap (n > 999) permanently exhausted a
    family's id space after exactly one deterministic grid pass --
    MOMENTUM hit 999 strategies on its very first run and could never
    grid, mutate, or accept an LLM hypothesis for that family again.
    Seeds the counter to 999 directly and proves the 1000th id is now
    issued cleanly instead of raising IdSequenceExhausted."""
    family = _fresh_family()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO id_counters (scope, next_value) VALUES (:scope, 999)"),
            {"scope": f"strategy:{family}"},
        )
    assert await next_strategy_id(family) == f"{family}-001000"


async def test_next_strategy_id_exhausts_only_past_999_999(engine: AsyncEngine) -> None:
    family = _fresh_family()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO id_counters (scope, next_value) VALUES (:scope, 999999)"),
            {"scope": f"strategy:{family}"},
        )
    with pytest.raises(IdSequenceExhausted, match="strategy id sequence exhausted"):
        await next_strategy_id(family)


async def test_next_strategy_id_accepts_rotation_family_names() -> None:
    # SECTOR_MOMENTUM_ROTATION is 24 chars -- exceeds the old 20-char cap.
    strategy_id = await next_strategy_id("SECTOR_MOMENTUM_ROTATION")
    assert strategy_id.startswith("SECTOR_MOMENTUM_ROTATION-")

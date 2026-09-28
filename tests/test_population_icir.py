"""ICIR is the parent-selection fitness: the most consistent strategies are
bred first, the composite score only breaks ties and ranks families that
have no ICIR."""
from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.population import select_for_cross_breeding

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
    ),
]


async def _scored(session: AsyncSession, *, fast: int, score: float, icir: float | None) -> str:
    spec = {
        "family": "MOMENTUM", "symbol": f"P{uuid.uuid4().hex[:8]}/USDT", "timeframe": "1d",
        "fast_window": fast, "slow_window": fast * 5, "expected_horizon": 5,
    }
    strategy_id = f"P{uuid.uuid4().hex[:12]}"
    experiment_id = f"E{uuid.uuid4().hex[:12]}"
    config_hash = uuid.uuid4().hex
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:i, 'MOMENTUM', CAST(:s AS jsonb), 'PROMISING')"
        ),
        {"i": strategy_id, "s": json.dumps(spec)},
    )
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}'::jsonb, :i, :h)"
        ),
        {"e": experiment_id, "i": strategy_id, "h": config_hash},
    )
    await session.execute(
        text(
            "INSERT INTO validation_results (experiment_id, strategy_fingerprint, verdict, score, "
            "reason_codes, metrics) VALUES (:e, :h, 'PROMISING', :score, '[]'::jsonb, "
            "CAST(:m AS jsonb))"
        ),
        {"e": experiment_id, "h": config_hash, "score": score, "m": json.dumps({"icir": icir})},
    )
    return strategy_id


async def test_crossover_parents_are_the_most_consistent(db_session: AsyncSession) -> None:
    # Highest score but erratic, vs. two lower-scoring consistent ones.
    await _scored(db_session, fast=3, score=1e9, icir=1e6)
    steady = await _scored(db_session, fast=4, score=1.0, icir=1e12)
    steadier = await _scored(db_session, fast=6, score=0.5, icir=1e13)

    pair = await select_for_cross_breeding(db_session, family="MOMENTUM")
    assert pair is not None
    assert [c.strategy_id for c in pair] == [steadier, steady]
    assert pair[0].icir == 1e13

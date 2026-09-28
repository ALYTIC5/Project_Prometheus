"""Test helper: record a one-shot vault verdict for a spec, as
validation/holdout_test.run_holdout_test would after a real test."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_holdout_verdict(
    session: AsyncSession, config_hash: str, *, strategy_id: str = "test", passed: bool = True
) -> None:
    await session.execute(
        text(
            "INSERT INTO evaluator.holdout_verdicts (config_hash, strategy_id, n_observations, "
            "p_value, excess_return_pct, passed) VALUES (:h, :s, 180, :p, 5.0, :passed) "
            "ON CONFLICT (config_hash) DO NOTHING"
        ),
        {"h": config_hash, "s": strategy_id, "p": 0.001 if passed else 0.4, "passed": passed},
    )

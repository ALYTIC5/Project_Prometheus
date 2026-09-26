"""prometheus/validation/canaries.py -- a permanent, blind null suite.

The one-off null suite (tests/test_null_strategies.py) proves the engine
was honest once. Canaries keep proving it: about 5% of every regenerated
baseline grid gets a near-duplicate spec -- same family and symbol, one
parameter moved one step -- whose signal is replaced by a known-null one
when the evaluator runs it (backtest/null_signals.py). To every research
component a canary is an ordinary grid spec; which specs are canaries lives
only in evaluator.canary_registry, which the research role cannot read.

A canary promoted past PROMISING is a CANARY_BREACH (validation/status.py).

Selection is deterministic in (CANARY_SALT, spec) -- the same grid yields
the same canaries every cycle, so they are re-validated like every other
grid spec -- and unpredictable without the salt, which only the evaluator
process holds.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.null_signals import NULL_KINDS
from prometheus.core.seeds import derive_seed
from prometheus.strategy.spec import StrategySpec

# The self-improvement prompt's own target ("roughly 5% of all jobs").
CANARY_PERCENT = 5


@dataclass(frozen=True)
class Canary:
    spec: StrategySpec
    kind: str
    source_config_hash: str


def _jittered(spec: StrategySpec, seed: int) -> list[StrategySpec]:
    """Valid near-duplicates of `spec`: each parameter moved one step
    (+/-1 for integers, +/-5% for floats), in a seed-dependent order."""
    dumped = spec.model_dump()
    fields = sorted(spec.parameters)
    rotation = seed % len(fields) if fields else 0
    candidates: list[StrategySpec] = []
    for field in fields[rotation:] + fields[:rotation]:
        value = dumped[field]
        steps = (value + 1, value - 1) if isinstance(value, int) else (value * 1.05, value * 0.95)
        for new_value in steps:
            try:
                candidates.append(spec.with_updates(**{field: new_value}))
            except ValueError:
                continue
    return candidates


def canary_specs(grid: list[StrategySpec], salt: str) -> list[Canary]:
    grid_hashes = {spec.config_hash() for spec in grid}
    taken: set[str] = set()
    canaries: list[Canary] = []
    for spec in grid:
        source_hash = spec.config_hash()
        seed = derive_seed("canary", salt, source_hash)
        if seed % 100 >= CANARY_PERCENT:
            continue
        for candidate in _jittered(spec, seed):
            candidate_hash = candidate.config_hash()
            if candidate_hash in grid_hashes or candidate_hash in taken:
                continue
            taken.add(candidate_hash)
            canaries.append(
                Canary(
                    spec=candidate,
                    kind=NULL_KINDS[seed % len(NULL_KINDS)],
                    source_config_hash=source_hash,
                )
            )
            break
    return canaries


def canary_salt() -> str:
    return os.environ["CANARY_SALT"]


def with_canaries(grid: list[StrategySpec]) -> tuple[list[StrategySpec], list[Canary]]:
    canaries = canary_specs(grid, canary_salt())
    return grid + [c.spec for c in canaries], canaries


_REGISTER = text(
    """
    INSERT INTO evaluator.canary_registry (config_hash, kind, source_config_hash)
    VALUES (:config_hash, :kind, :source_config_hash)
    ON CONFLICT (config_hash) DO NOTHING
    """
)
_SELECT_KINDS = text(
    "SELECT config_hash, kind FROM evaluator.canary_registry WHERE config_hash IN :hashes"
).bindparams(bindparam("hashes", expanding=True))
_RECORD_STRATEGY = text(
    """
    INSERT INTO evaluator.canary_strategies (strategy_id, config_hash)
    VALUES (:strategy_id, :config_hash)
    ON CONFLICT (strategy_id) DO NOTHING
    """
)


async def register_canaries(session: AsyncSession, canaries: list[Canary]) -> None:
    for canary in canaries:
        await session.execute(
            _REGISTER,
            {
                "config_hash": canary.spec.config_hash(),
                "kind": canary.kind,
                "source_config_hash": canary.source_config_hash,
            },
        )


async def canary_kinds(session: AsyncSession, config_hashes: list[str]) -> dict[str, str]:
    if not config_hashes:
        return {}
    rows = (await session.execute(_SELECT_KINDS, {"hashes": config_hashes})).all()
    return {row.config_hash: row.kind for row in rows}


async def record_canary_strategy(
    session: AsyncSession, strategy_id: str, config_hash: str
) -> None:
    await session.execute(
        _RECORD_STRATEGY, {"strategy_id": strategy_id, "config_hash": config_hash}
    )


def null_seed(config_hash: str) -> int:
    return derive_seed("canary-null", config_hash)

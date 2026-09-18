"""Strategies API endpoint. Real rows from the `strategies` table, enriched
with the real validation and lineage data Prompt 5/7 already produce but
this route never surfaced -- the dashboard was showing "--" for OOS Sharpe/
PBO/DSR/generation/parent even though every one of those has a real answer
in Postgres today. Two real joins, not new schema:

1. Validation: `validation_results.strategy_fingerprint` is
   `StrategySpec.config_hash()`, not `strategies.id` -- the same
   strategies -> latest experiment -> that experiment's config_hash ->
   latest validation_results-for-that-fingerprint path
   `research/population.py`'s `_LATEST_FINGERPRINT_CTE` already
   established (duplicated here, not imported, since that symbol is
   module-private to population.py and this is the same well-understood
   pattern, not a new one).
2. Lineage: `StrategySpec.parent_id` (set by research/mutations.py) is the
   PARENT spec's own config_hash, not a strategies.id -- resolved in
   Python via `_resolve_lineage` below, matched against every other
   strategy's own recomputed hash, not a DB column (none exists, and
   config_hash() is a pure function of the spec, so recomputing it here is
   the honest source of truth, not a second copy of it).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Row

from prometheus.core.db import get_session_factory
from prometheus.strategy.spec import StrategySpec

router = APIRouter(prefix="/strategies", tags=["strategies"])

_SELECT_ALL = text(
    "SELECT id, family, spec, status, created_at FROM strategies ORDER BY created_at DESC LIMIT 500"
)
_SELECT_ONE = text("SELECT id, family, spec, status, created_at FROM strategies WHERE id = :id")

# Same join path as research/population.py's _LATEST_FINGERPRINT_CTE --
# see that module's own comment for why this is the real join (fingerprint,
# not strategies.id) and not a shortcut.
_SELECT_LATEST_VALIDATION = text(
    """
    WITH latest_experiment AS (
        SELECT DISTINCT ON (strategy_id) strategy_id, config_hash
          FROM experiments
         WHERE strategy_id IS NOT NULL
         ORDER BY strategy_id, created_at DESC
    )
    SELECT le.strategy_id, vr.verdict, vr.score, vr.pbo, vr.deflated_sharpe,
           vr.reason_codes, vr.metrics
      FROM latest_experiment le
      JOIN LATERAL (
          SELECT verdict, score, pbo, deflated_sharpe, reason_codes, metrics
            FROM validation_results
           WHERE strategy_fingerprint = le.config_hash
           ORDER BY created_at DESC LIMIT 1
      ) vr ON true
    """
)


def _resolve_lineage(specs_by_id: dict[str, StrategySpec]) -> dict[str, tuple[str | None, int]]:
    """For every strategy id, resolves (parent_strategy_id, generation)
    from its own spec.parent_id (the PARENT spec's config_hash --
    research/mutations.py's own convention) by matching it against every
    OTHER strategy's recomputed config_hash. generation counts hops back
    to a root: 0 for no parent, or for a parent hash that matches nothing
    in today's strategies (e.g. the parent was later deleted, or predates
    this feature) -- an honest "can't trace further," not an error, since
    a real spec can legitimately reference a parent no longer in the table.
    """
    hash_to_id = {spec.config_hash(): sid for sid, spec in specs_by_id.items()}
    resolved: dict[str, tuple[str | None, int]] = {}

    def resolve(sid: str, path: frozenset[str]) -> tuple[str | None, int]:
        if sid in resolved:
            return resolved[sid]
        parent_hash = specs_by_id[sid].parent_id
        parent_sid = hash_to_id.get(parent_hash) if parent_hash else None
        if parent_sid is None or parent_sid in path:
            # No parent, unknown parent, or a cycle (defensive -- a spec's
            # hash covers its own parent_id field, so a real cycle would
            # require two specs each claiming the other as parent, which
            # config_hash()'s own determinism makes impossible in practice).
            outcome = (parent_sid if parent_sid not in path else None, 0)
        else:
            _, parent_generation = resolve(parent_sid, path | {sid})
            outcome = (parent_sid, parent_generation + 1)
        resolved[sid] = outcome
        return outcome

    for sid in specs_by_id:
        resolve(sid, frozenset())
    return resolved


async def _enrich(rows: Sequence[Row[Any]], session: Any) -> list[dict[str, Any]]:
    specs_by_id = {r.id: StrategySpec.model_validate(r.spec) for r in rows}
    lineage = _resolve_lineage(specs_by_id)

    validation_rows = (await session.execute(_SELECT_LATEST_VALIDATION)).fetchall()
    validation_by_strategy_id = {v.strategy_id: v for v in validation_rows}

    enriched: list[dict[str, Any]] = []
    for row in rows:
        validation = validation_by_strategy_id.get(row.id)
        parent_id, generation = lineage.get(row.id, (None, 0))
        metrics = validation.metrics if validation is not None else {}
        enriched.append(
            {
                "id": row.id,
                "family": row.family,
                "spec": row.spec,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "verdict": validation.verdict if validation is not None else None,
                "score": validation.score if validation is not None else None,
                "pbo": validation.pbo if validation is not None else None,
                "deflated_sharpe": validation.deflated_sharpe if validation is not None else None,
                "excess_return": metrics.get("excess_return"),
                "excess_sharpe": metrics.get("excess_sharpe"),
                "reason_codes": validation.reason_codes if validation is not None else [],
                "generation": generation,
                "parent": parent_id,
            }
        )
    return enriched


@router.get("/")
async def list_strategies() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await session.execute(_SELECT_ALL)
        rows = result.fetchall()
        enriched = await _enrich(rows, session)
    return {"strategies": enriched, "total": len(enriched)}


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        row = (await session.execute(_SELECT_ONE, {"id": strategy_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
        enriched = await _enrich([row], session)
    return enriched[0]

"""Experiments API endpoint -- an experiment plus its real results/decisions
rows, joined by experiment_id (there is no FK-based ORM relationship here,
matching this file's plain-text-SQL style rather than the ORM style
core/config.py uses for PolicyVersion).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/experiments", tags=["experiments"])

_SELECT_ALL = text(
    """
    SELECT e.id, e.status, e.payload, e.hypothesis, e.parent_experiment_id, e.created_at,
           latest_decision.decision,
           latest_result.payload AS result_payload
      FROM experiments e
      LEFT JOIN LATERAL (
          SELECT decision FROM decisions
           WHERE experiment_id = e.id
           ORDER BY created_at DESC, id DESC
           LIMIT 1
      ) latest_decision ON true
      LEFT JOIN LATERAL (
          SELECT payload FROM results
           WHERE experiment_id = e.id
           ORDER BY created_at DESC, id DESC
           LIMIT 1
      ) latest_result ON true
     ORDER BY e.created_at DESC LIMIT 200
    """
)
# One point per spec (config_hash): its latest result, across every symbol
# and universe -- the Oracle scatter's data. /experiments/ is the latest 200
# EXPERIMENTS, which after the 2026-09-24 retry churn were ~98% result-less
# insufficient-data rejects, so the chart only ever showed whichever one or
# two symbols ran last and read as "every benchmark is identical".
_SELECT_SCATTER = text(
    """
    SELECT DISTINCT ON (e.config_hash)
           e.id, e.config_hash, st.family,
           st.spec->>'symbol' AS symbol, st.spec->'universe' AS universe,
           r.payload AS result_payload, r.created_at,
           latest_decision.decision
      FROM results r
      JOIN experiments e ON e.id = r.experiment_id
      JOIN strategies st ON st.id = e.strategy_id
      LEFT JOIN LATERAL (
          SELECT decision FROM decisions
           WHERE experiment_id = e.id
           ORDER BY created_at DESC, id DESC
           LIMIT 1
      ) latest_decision ON true
     ORDER BY e.config_hash, r.created_at DESC, r.id DESC
    """
)
_SELECT_ONE = text(
    "SELECT id, status, payload, hypothesis, parent_experiment_id, created_at "
    "FROM experiments WHERE id = :id"
)
_SELECT_RESULTS = text(
    "SELECT payload, created_at FROM results WHERE experiment_id = :id ORDER BY created_at DESC"
)
_SELECT_DECISIONS = text(
    "SELECT decision, created_at FROM decisions WHERE experiment_id = :id ORDER BY created_at DESC"
)


@router.get("/")
async def list_experiments() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await session.execute(_SELECT_ALL)
        rows = [
            {
                "id": r.id,
                "status": r.status,
                "payload": r.payload,
                "hypothesis": r.hypothesis,
                "parent_experiment_id": r.parent_experiment_id,
                "created_at": r.created_at.isoformat(),
                # The latest decision only -- Law 6 means an experiment can
                # carry more than one (a correction supersedes rather than
                # replaces), same "latest wins" rule as
                # experiments.lineage's latest_result fragment.
                "decision": r.decision,
                # None for the insufficient_data path (runner.py's except
                # branch writes a Decision but no Result row) -- an honest
                # gap, not a zero.
                "total_return_pct": (r.result_payload or {}).get("total_return_pct"),
                "benchmark_return_pct": (r.result_payload or {}).get("benchmark_return_pct"),
            }
            for r in result
        ]
    return {"experiments": rows, "total": len(rows)}


@router.get("/scatter")
async def experiments_scatter() -> dict[str, Any]:
    """Declared before /{experiment_id} so "scatter" isn't parsed as an id."""
    async with get_session_factory()() as session:
        rows = (await session.execute(_SELECT_SCATTER)).all()
    points = []
    for r in rows:
        payload = r.result_payload or {}
        if payload.get("total_return_pct") is None or payload.get("benchmark_return_pct") is None:
            continue
        points.append(
            {
                "id": r.id,
                "config_hash": r.config_hash,
                "family": r.family,
                "symbol": r.symbol,
                "universe": r.universe,
                "total_return_pct": payload["total_return_pct"],
                "benchmark_return_pct": payload["benchmark_return_pct"],
                # Results written before 2026-09-24 carry no benchmark
                # provenance (universe/window) -- flagged, not hidden.
                "benchmark_universe": payload.get("benchmark_universe"),
                "benchmark_window": payload.get("benchmark_window"),
                "decision": (r.decision or {}).get("decision"),
                "created_at": r.created_at.isoformat(),
            }
        )
    return {"points": points, "total": len(points)}


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        exp = (await session.execute(_SELECT_ONE, {"id": experiment_id})).first()
        if exp is None:
            raise HTTPException(status_code=404, detail=f"Unknown experiment: {experiment_id}")
        results = [
            {"payload": r.payload, "created_at": r.created_at.isoformat()}
            for r in await session.execute(_SELECT_RESULTS, {"id": experiment_id})
        ]
        decisions = [
            {"decision": d.decision, "created_at": d.created_at.isoformat()}
            for d in await session.execute(_SELECT_DECISIONS, {"id": experiment_id})
        ]
    return {
        "id": exp.id,
        "status": exp.status,
        "payload": exp.payload,
        "hypothesis": exp.hypothesis,
        "parent_experiment_id": exp.parent_experiment_id,
        "created_at": exp.created_at.isoformat(),
        "results": results,
        "decisions": decisions,
    }

"""Correlation-cluster visibility -- the "100 strategies" prompt's own
explicit ask: "Surface clusters on the dashboard so redundancy is
visible." Reads the latest validation_results row per strategy
fingerprint (same latest-per-fingerprint convention research/population.py's
own _LATEST_FINGERPRINT_CTE uses), grouped by the cluster_key
experiments/runner.py's clustering step writes into metrics->'cluster'.
Read-only, informational -- does not affect elect_champions() (see
docs/DEFERRED.md's own entry for why that gating change is separate,
more carefully reviewed follow-up work).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/clusters", tags=["clusters"])

# strategies has no config_hash column of its own (it's derived from
# spec JSONB, not stored) -- join through experiments, which does carry
# config_hash as a real column, same path population.py's own
# _LATEST_FINGERPRINT_CTE uses in the other direction (strategy_id ->
# config_hash instead of config_hash -> strategy_id here).
_SELECT_LATEST_CLUSTERED = text(
    """
    WITH latest_per_fingerprint AS (
        SELECT DISTINCT ON (strategy_fingerprint)
               strategy_fingerprint, metrics, score, verdict
          FROM validation_results
         WHERE metrics -> 'cluster' IS NOT NULL
         ORDER BY strategy_fingerprint, created_at DESC
    ),
    fingerprint_to_strategy AS (
        SELECT DISTINCT ON (config_hash) config_hash, strategy_id
          FROM experiments
         WHERE strategy_id IS NOT NULL
         ORDER BY config_hash, created_at DESC
    )
    SELECT lpf.strategy_fingerprint, lpf.metrics, lpf.score, lpf.verdict,
           fts.strategy_id, s.family
      FROM latest_per_fingerprint lpf
      LEFT JOIN fingerprint_to_strategy fts ON fts.config_hash = lpf.strategy_fingerprint
      LEFT JOIN strategies s ON s.id = fts.strategy_id
    """
)


@router.get("/")
async def list_clusters() -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = (await session.execute(_SELECT_LATEST_CLUSTERED)).fetchall()

    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster = row.metrics.get("cluster")
        if not cluster:
            continue
        key = cluster["cluster_key"]
        entry = clusters.setdefault(
            key,
            {
                "cluster_key": key,
                "mean_pairwise_correlation": cluster["mean_pairwise_correlation"],
                "members": [],
            },
        )
        entry["members"].append(
            {
                "strategy_id": row.strategy_id,
                "family": row.family,
                "config_hash": row.strategy_fingerprint,
                "is_representative": cluster["is_representative"],
                "score": row.score,
                "verdict": row.verdict,
            }
        )

    # Only real clusters (>1 member) are "redundancy" worth surfacing --
    # a cluster of one is just an ordinary, uncorrelated strategy and
    # would clutter this view with every strategy in the corpus.
    real_clusters = [c for c in clusters.values() if len(c["members"]) > 1]
    real_clusters.sort(key=lambda c: len(c["members"]), reverse=True)
    return {"clusters": real_clusters, "total": len(real_clusters)}

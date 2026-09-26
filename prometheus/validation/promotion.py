"""prometheus/validation/promotion.py -- verdict -> status mapping and
champion election. Both are judging decisions, so they live with the
evaluator (Law 9), not in research/population.py where they started.

The mapping is not a second state machine: validation.decision.Verdict
already is the lifecycle. CHAMPION is deliberately not what PROMOTE
writes -- a champion is the single best-scoring VALIDATED strategy per
family, elected here.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.validation.status import set_status

_VERDICT_TO_STATUS: dict[str, str] = {
    "PROMOTE": "VALIDATED",
    "PROMISING": "PROMISING",
    "CONTINUE_RESEARCH": "EXPERIMENTAL",
    "REGIME_SPECIALIST": "REGIME_SPECIALIST",
    "DORMANT": "DORMANT",
    "QUARANTINE": "QUARANTINED",
    "REJECT": "REJECTED",
    "RETIRE": "RETIRED",
}


def verdict_to_status(verdict: str) -> str:
    """Raises on an unknown verdict rather than silently defaulting."""
    try:
        return _VERDICT_TO_STATUS[verdict]
    except KeyError:
        raise ValueError(f"no status mapping for verdict {verdict!r}") from None


# validation_results.strategy_fingerprint is StrategySpec.config_hash(), not
# strategies.id: join strategy -> latest experiment -> its config_hash ->
# latest validation score. Scoped to VALIDATED only (the one status this
# query selects on); an unscoped walk over every strategy ever created took
# hours on 2026-09-25.
_SELECT_BEST_VALIDATED_PER_FAMILY = text(
    """
    WITH latest_experiment AS (
        SELECT DISTINCT ON (e.strategy_id) e.strategy_id, e.config_hash
          FROM experiments e
         WHERE e.strategy_id IN (SELECT id FROM strategies WHERE status = 'VALIDATED')
         ORDER BY e.strategy_id, e.created_at DESC
    ),
    latest_score AS (
        SELECT le.strategy_id, vr.score
          FROM latest_experiment le
          JOIN LATERAL (
              SELECT score FROM validation_results
               WHERE strategy_fingerprint = le.config_hash
               ORDER BY created_at DESC LIMIT 1
          ) vr ON true
    )
    SELECT DISTINCT ON (s.family) s.id
      FROM strategies s
      LEFT JOIN latest_score ls ON ls.strategy_id = s.id
     WHERE s.status = 'VALIDATED'
     ORDER BY s.family, ls.score DESC NULLS LAST
    """
)
_SELECT_STALE_CHAMPIONS = text(
    "SELECT id FROM strategies WHERE status = 'CHAMPION' AND id != ALL(:keep_ids)"
)


async def elect_champions(session: AsyncSession) -> list[str]:
    """One CHAMPION per family: its best-scoring VALIDATED strategy. A
    family with no VALIDATED strategy has no champion. A champion that is
    no longer its family's best goes back to VALIDATED (losing the title is
    not failing validation). Every write goes through set_status, so a
    canary or a promotion halt can never produce a champion. Returns the
    ids actually crowned."""
    best_ids = [
        row.id for row in (await session.execute(_SELECT_BEST_VALIDATED_PER_FAMILY)).fetchall()
    ]
    stale = (await session.execute(_SELECT_STALE_CHAMPIONS, {"keep_ids": best_ids})).scalars()
    for strategy_id in list(stale):
        await set_status(session, strategy_id, "VALIDATED", reason="no longer best in family")
    crowned: list[str] = []
    for strategy_id in best_ids:
        if await set_status(session, strategy_id, "CHAMPION", reason="best VALIDATED in family"):
            crowned.append(strategy_id)
    return crowned

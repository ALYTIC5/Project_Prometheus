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

from prometheus.validation.status import promotions_halted, reinstate_champion, set_status

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
# latest validation score. Scoped to VALIDATED/CHAMPION (the statuses this
# query selects on); an unscoped walk over every strategy ever created took
# hours on 2026-09-25. The sitting CHAMPION is a candidate too -- leaving it
# out demoted every champion on every run, and during a promotion halt
# (which refuses the re-crowning) emptied paper trading (2026-09-26..28).
_SELECT_BEST_PER_FAMILY = text(
    """
    WITH latest_experiment AS (
        SELECT DISTINCT ON (e.strategy_id) e.strategy_id, e.config_hash
          FROM experiments e
         WHERE e.strategy_id IN (
             SELECT id FROM strategies WHERE status IN ('VALIDATED', 'CHAMPION')
         )
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
    SELECT DISTINCT ON (s.family) s.id, s.status
      FROM strategies s
      LEFT JOIN latest_score ls ON ls.strategy_id = s.id
     WHERE s.status IN ('VALIDATED', 'CHAMPION')
     ORDER BY s.family, ls.score DESC NULLS LAST, (s.status = 'CHAMPION') DESC
    """
)
_SELECT_CHAMPIONS = text("SELECT id FROM strategies WHERE status = 'CHAMPION'")
_SELECT_STALE_CHAMPIONS = text(
    "SELECT id FROM strategies WHERE status = 'CHAMPION' AND id != ALL(:keep_ids)"
)


async def elect_champions(session: AsyncSession) -> list[str]:
    """One CHAMPION per family: its best-scoring VALIDATED or CHAMPION
    strategy (a tie keeps the sitting champion). A champion that is no
    longer its family's best goes back to VALIDATED (losing the title is not
    failing validation).

    While promotions are halted the champion set is frozen: no demotions and
    no crownings, so paper trading keeps running on the champions it had
    (user decision 2026-09-28). Returns the champion ids after the call."""
    if await promotions_halted(session):
        return list((await session.execute(_SELECT_CHAMPIONS)).scalars())
    best = (await session.execute(_SELECT_BEST_PER_FAMILY)).fetchall()
    best_ids = [row.id for row in best]
    stale = (await session.execute(_SELECT_STALE_CHAMPIONS, {"keep_ids": best_ids})).scalars()
    for strategy_id in list(stale):
        await set_status(session, strategy_id, "VALIDATED", reason="no longer best in family")
    for row in best:
        if row.status != "CHAMPION":
            await set_status(session, row.id, "CHAMPION", reason="best VALIDATED in family")
    return list((await session.execute(_SELECT_CHAMPIONS)).scalars())


# Per family, the most recently paper-traded strategy that is VALIDATED now
# -- i.e. the champion the halt churn demoted -- in families with no
# champion. Paper trading only ever trades CHAMPIONs, so a paper order proves
# the strategy held the title.
_SELECT_CHAMPIONS_TO_RESTORE = text(
    """
    SELECT DISTINCT ON (s.family) s.id
      FROM strategies s
      JOIN paper_orders o ON o.strategy_id = s.id
     WHERE s.status = 'VALIDATED'
       AND NOT EXISTS (
             SELECT 1 FROM strategies c WHERE c.status = 'CHAMPION' AND c.family = s.family
           )
     ORDER BY s.family, o.event_time DESC
    """
)


async def restore_champions_demoted_by_halt(session: AsyncSession) -> list[str]:
    """One-time repair (user decision 2026-09-28): give each family back the
    champion the pre-fix election churn took away during the promotion
    halt. Goes through reinstate_champion, which still refuses a canary."""
    restored: list[str] = []
    for strategy_id in list((await session.execute(_SELECT_CHAMPIONS_TO_RESTORE)).scalars()):
        if await reinstate_champion(
            session, strategy_id, reason="restored after halt-time election churn"
        ):
            restored.append(strategy_id)
    return restored

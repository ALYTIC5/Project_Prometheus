"""prometheus/validation/status.py -- the single writer of strategies.status.

Every status change goes through set_status, so two guarantees hold in one
place:

1. A canary (a known-null strategy injected blind, see validation/
   canaries.py) can never be promoted past PROMISING. An attempt is a
   CANARY_BREACH: the promotion is refused, the breach and a promotion halt
   are appended to the evaluator schema, a RESEARCH_VIOLATION is recorded,
   and it is logged at ERROR. A breach proves the pipeline can manufacture
   a false discovery, so nothing may be promoted until a human clears it.
2. While a halt is in force, no strategy is promoted past PROMISING.
   Demotions and rejections always go through -- a halt stops new claims
   of success, never the removal of old ones.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.violations import ResearchViolation, record_violations

logger = logging.getLogger(__name__)

PROMOTED_STATUSES = frozenset({"VALIDATED", "CHAMPION", "REGIME_SPECIALIST"})

# Only the order above PROMISING matters: moving INTO a promoted status from
# a lower rank is a promotion; CHAMPION -> VALIDATED is a demotion.
_RANK = {"CHAMPION": 3, "VALIDATED": 2, "REGIME_SPECIALIST": 2}

_UPDATE_STATUS = text("UPDATE strategies SET status = :status WHERE id = :id")
_SELECT_STATUS = text("SELECT status FROM strategies WHERE id = :id")
_SELECT_CANARY = text(
    "SELECT config_hash FROM evaluator.canary_strategies WHERE strategy_id = :id"
)
_SELECT_LATEST_HALT_EVENT = text(
    "SELECT event FROM evaluator.promotion_halts ORDER BY id DESC LIMIT 1"
)
_INSERT_BREACH = text(
    """
    INSERT INTO evaluator.canary_breaches
        (strategy_id, config_hash, attempted_status, reason)
    VALUES (:strategy_id, :config_hash, :attempted_status, :reason)
    """
)
_INSERT_HALT_EVENT = text(
    "INSERT INTO evaluator.promotion_halts (event, reason) VALUES (:event, :reason)"
)


async def promotions_halted(session: AsyncSession) -> bool:
    latest = (await session.execute(_SELECT_LATEST_HALT_EVENT)).scalar_one_or_none()
    return latest == "HALT"


async def clear_promotion_halt(session: AsyncSession, *, reason: str) -> None:
    """Human action only: after a breach has been investigated. Appends a
    CLEAR event; the HALT that preceded it stays in the log."""
    await session.execute(_INSERT_HALT_EVENT, {"event": "CLEAR", "reason": reason})


async def set_status(
    session: AsyncSession, strategy_id: str, new_status: str, *, reason: str
) -> bool:
    """Writes new_status unless it is a promotion that must be refused.
    Returns whether the status was written. Does not commit."""
    if await _is_promotion(session, strategy_id, new_status):
        canary_hash = (
            await session.execute(_SELECT_CANARY, {"id": strategy_id})
        ).scalar_one_or_none()
        if canary_hash is not None:
            await _record_breach(session, strategy_id, canary_hash, new_status, reason)
            return False
        if await promotions_halted(session):
            logger.warning(
                "promotion of %s to %s refused: promotions are halted (%s)",
                strategy_id, new_status, reason,
            )
            return False
    await session.execute(_UPDATE_STATUS, {"status": new_status, "id": strategy_id})
    return True


async def _is_promotion(session: AsyncSession, strategy_id: str, new_status: str) -> bool:
    if new_status not in PROMOTED_STATUSES:
        return False
    current = (await session.execute(_SELECT_STATUS, {"id": strategy_id})).scalar_one_or_none()
    return _RANK[new_status] > _RANK.get(current or "", 0)


async def _record_breach(
    session: AsyncSession, strategy_id: str, config_hash: str, attempted: str, reason: str
) -> None:
    await session.execute(
        _INSERT_BREACH,
        {
            "strategy_id": strategy_id,
            "config_hash": config_hash,
            "attempted_status": attempted,
            "reason": reason,
        },
    )
    await session.execute(
        _INSERT_HALT_EVENT,
        {"event": "HALT", "reason": f"CANARY_BREACH: {strategy_id} -> {attempted}"},
    )
    await record_violations(
        session,
        ResearchViolation.CANARY_BREACH,
        [{"strategy_id": strategy_id, "attempted_status": attempted, "reason": reason}],
    )
    logger.error(
        "CANARY_BREACH: canary %s was about to be promoted to %s (%s). "
        "Promotions halted until a human clears it.",
        strategy_id, attempted, reason,
    )

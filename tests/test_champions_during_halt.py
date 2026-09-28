"""Champion election keeps sitting champions, freezes during a promotion
halt, and the one-time restore gives back titles the halt-time churn took
(user decision 2026-09-28)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.validation.promotion import elect_champions, restore_champions_demoted_by_halt
from prometheus.validation.status import clear_promotion_halt, promotions_halted
from prometheus.worker import _CHAMPION_RESTORE_MARKER
from tests.holdout_helpers import record_holdout_verdict

pytestmark = pytest.mark.db


def test_restore_marker_fits_worker_cadence_column() -> None:
    assert len(_CHAMPION_RESTORE_MARKER) <= 16


def _family() -> str:
    return f"TF{uuid.uuid4().hex[:8]}"


async def _strategy(session: AsyncSession, family: str, status: str, score: float) -> str:
    strategy_id = f"T{uuid.uuid4().hex[:12]}"
    config_hash = uuid.uuid4().hex
    experiment_id = f"E{uuid.uuid4().hex[:12]}"
    await session.execute(
        text("INSERT INTO strategies (id, family, spec, status) VALUES (:i, :f, '{}', :s)"),
        {"i": strategy_id, "f": family, "s": status},
    )
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}', :i, :h)"
        ),
        {"e": experiment_id, "i": strategy_id, "h": config_hash},
    )
    await session.execute(
        text(
            "INSERT INTO validation_results (experiment_id, strategy_fingerprint, verdict, score) "
            "VALUES (:e, :h, 'PROMOTE', :sc)"
        ),
        {"e": experiment_id, "h": config_hash, "sc": score},
    )
    # Every strategy here is past its one vault test: CHAMPION requires it
    # (Law 3, 2026-09-28); these tests are about election, not the vault.
    await record_holdout_verdict(session, config_hash, strategy_id=strategy_id)
    return strategy_id


async def _status(session: AsyncSession, strategy_id: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT status FROM strategies WHERE id = :i"), {"i": strategy_id}
            )
        ).scalar_one()
    )


async def _halt(session: AsyncSession) -> None:
    await session.execute(
        text("INSERT INTO evaluator.promotion_halts (event, reason) VALUES ('HALT', 'test')")
    )


async def _paper_order(session: AsyncSession, strategy_id: str, when: datetime) -> None:
    await session.execute(
        text(
            "INSERT INTO paper_orders (id, strategy_id, client_order_id, symbol, side, qty, "
            "expected_price, expected_qty, event_time) "
            "VALUES (:id, :s, :c, 'BTC/USDT', 'BUY', 1, 1, 1, :t)"
        ),
        {"id": uuid.uuid4().hex[:20], "s": strategy_id, "c": uuid.uuid4().hex, "t": when},
    )


async def test_sitting_champion_that_is_still_best_is_not_demoted(
    db_session: AsyncSession,
) -> None:
    family = _family()
    champion = await _strategy(db_session, family, "CHAMPION", 0.9)
    runner_up = await _strategy(db_session, family, "VALIDATED", 0.5)

    await elect_champions(db_session)

    assert await _status(db_session, champion) == "CHAMPION"
    assert await _status(db_session, runner_up) == "VALIDATED"


async def test_better_validated_strategy_takes_the_title(db_session: AsyncSession) -> None:
    family = _family()
    champion = await _strategy(db_session, family, "CHAMPION", 0.4)
    challenger = await _strategy(db_session, family, "VALIDATED", 0.8)

    await elect_champions(db_session)

    assert await _status(db_session, champion) == "VALIDATED"
    assert await _status(db_session, challenger) == "CHAMPION"


async def test_halt_freezes_the_champion_set(db_session: AsyncSession) -> None:
    family = _family()
    champion = await _strategy(db_session, family, "CHAMPION", 0.4)
    challenger = await _strategy(db_session, family, "VALIDATED", 0.8)
    await _halt(db_session)

    champions = await elect_champions(db_session)

    assert champion in champions
    assert await _status(db_session, champion) == "CHAMPION"
    assert await _status(db_session, challenger) == "VALIDATED"
    await clear_promotion_halt(db_session, reason="test")


async def test_restore_gives_each_family_back_its_most_recent_paper_traded_champion(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    demoted_family, crowned_family = _family(), _family()
    older = await _strategy(db_session, demoted_family, "VALIDATED", 0.9)
    recent = await _strategy(db_session, demoted_family, "VALIDATED", 0.1)
    await _paper_order(db_session, older, now - timedelta(days=5))
    await _paper_order(db_session, recent, now - timedelta(days=2))
    sitting = await _strategy(db_session, crowned_family, "CHAMPION", 0.5)
    other = await _strategy(db_session, crowned_family, "VALIDATED", 0.9)
    await _paper_order(db_session, other, now)
    await _halt(db_session)

    restored = await restore_champions_demoted_by_halt(db_session)

    assert recent in restored and older not in restored and other not in restored
    assert await _status(db_session, recent) == "CHAMPION"
    assert await _status(db_session, sitting) == "CHAMPION"
    assert await _status(db_session, other) == "VALIDATED"
    assert await promotions_halted(db_session)  # the restore does not clear the halt
    await clear_promotion_halt(db_session, reason="test")


async def test_restore_never_crowns_a_canary(db_session: AsyncSession) -> None:
    family = _family()
    canary = await _strategy(db_session, family, "VALIDATED", 0.9)
    await _paper_order(db_session, canary, datetime.now(UTC))
    await db_session.execute(
        text(
            "INSERT INTO evaluator.canary_strategies (strategy_id, config_hash) VALUES (:i, :h)"
        ),
        {"i": canary, "h": uuid.uuid4().hex},
    )

    restored = await restore_champions_demoted_by_halt(db_session)

    assert canary not in restored
    assert await _status(db_session, canary) == "VALIDATED"
    breach = (
        await db_session.execute(
            text("SELECT count(*) FROM evaluator.canary_breaches WHERE strategy_id = :i"),
            {"i": canary},
        )
    ).scalar_one()
    assert breach == 1
    await clear_promotion_halt(db_session, reason="test")


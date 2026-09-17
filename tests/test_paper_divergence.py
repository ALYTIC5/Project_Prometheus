import pytest
from sqlalchemy import text

from prometheus.paper.divergence import check_divergence

pytestmark = [pytest.mark.db]


async def _seed_strategy(db_session, strategy_id: str) -> None:
    await db_session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, 'MOMENTUM', '{}', 'CHAMPION')"
        ),
        {"id": strategy_id},
    )
    await db_session.commit()


async def test_check_divergence_fires_on_material_slippage(db_session):
    await _seed_strategy(db_session, "MOMENTUM-020")
    # A consistent, large adverse price_delta_pct on every buy fill --
    # clearly material against the cost model's assumed ~0.05% baseline
    # (config/costs.yaml's slippage_bps=5.0 -> 0.05%), not noise around it.
    deltas = [
        {"price_delta_pct": 5.0, "qty_delta_pct": 0.0, "latency_seconds": 1.0, "side": "buy"}
    ] * 10

    fired = await check_divergence(
        db_session, strategy_id="MOMENTUM-020", reconciliation_deltas=deltas
    )
    assert fired is True

    status = (
        await db_session.execute(
            text("SELECT status FROM strategies WHERE id = 'MOMENTUM-020'")
        )
    ).scalar_one()
    assert status == "QUARANTINED"

    findings = (
        await db_session.execute(
            text("SELECT finding_type FROM paper_findings WHERE strategy_id = 'MOMENTUM-020'")
        )
    ).fetchall()
    assert any(row.finding_type == "PAPER_DIVERGENCE" for row in findings)

    proposals = (
        await db_session.execute(
            text(
                "SELECT status FROM experiments WHERE strategy_id = 'MOMENTUM-020' "
                "AND status = 'proposed'"
            )
        )
    ).fetchall()
    assert len(proposals) == 1


async def test_check_divergence_does_not_fire_on_small_noise(db_session):
    await _seed_strategy(db_session, "MOMENTUM-021")
    # Noise centered on the cost model's assumed ~0.05% baseline (not on
    # zero) -- mean is exactly 0.05, matching config/costs.yaml's
    # slippage_bps=5.0 -> 0.05%, so this must NOT fire against the new
    # cost-model-relative baseline even though it clearly would have
    # against the old zero-based one.
    price_deltas = [0.06, 0.04, 0.055, 0.045, 0.06, 0.04, 0.05, 0.05, 0.06, 0.04]
    deltas = [
        {"price_delta_pct": d, "qty_delta_pct": 0.0, "latency_seconds": 1.0, "side": "buy"}
        for d in price_deltas
    ]

    fired = await check_divergence(
        db_session, strategy_id="MOMENTUM-021", reconciliation_deltas=deltas
    )
    assert fired is False

    status = (
        await db_session.execute(
            text("SELECT status FROM strategies WHERE id = 'MOMENTUM-021'")
        )
    ).scalar_one()
    assert status == "CHAMPION"

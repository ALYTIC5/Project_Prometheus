"""Exercises reconcile_order (expected-vs-actual deltas for one FILLED
paper order), compute_paper_equity_curve (a REAL mark-to-market curve
built from actual fills -- cash plus position value, the same accounting
shape backtest.engine._run_accounting uses for simulated fills, now built
from real ones), and check_worse_than_holding (Law 8's paper-trading
equivalent: the real curve vs a EUR 1000 buy-and-hold of the same symbol
over the same window).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from prometheus.data.models import OhlcvBar as OhlcvBarModel
from prometheus.paper.reconciliation import (
    check_worse_than_holding,
    compute_paper_equity_curve,
    reconcile_order,
)

pytestmark = [pytest.mark.db]


async def _seed_strategy(session, strategy_id: str, family: str = "MOMENTUM") -> None:
    """paper_orders.strategy_id is a NOT NULL FK to strategies.id
    (alembic/versions/0012_paper_trading.py) -- a paper_orders INSERT
    without a pre-existing strategies row raises IntegrityError against a
    real Postgres (the same bug Task 6 found and fixed in
    test_paper_execution.py)."""
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, :family, '{}', 'CHAMPION')"
        ),
        {"id": strategy_id, "family": family},
    )
    await session.commit()


async def test_reconcile_order_computes_price_and_qty_deltas(db_session):
    await _seed_strategy(db_session, "MOMENTUM-010")
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, filled_qty, avg_fill_price,
                event_time, submitted_at, filled_at
            ) VALUES (
                'PAPER-TEST-1', 'MOMENTUM-010', 'coid-1', 'BTC/USDT', 'buy', 0.01,
                'FILLED', 50000.0, 0.01, 0.01, 50100.0,
                now() - interval '1 hour', now() - interval '1 hour', now()
            )
            """
        )
    )
    await db_session.commit()

    result = await reconcile_order(db_session, order_id="PAPER-TEST-1")
    assert result is not None
    assert result["price_delta_pct"] == pytest.approx((50100.0 - 50000.0) / 50000.0 * 100, rel=1e-6)
    assert result["qty_delta_pct"] == pytest.approx(0.0, abs=1e-9)
    assert result["latency_seconds"] > 0


async def test_reconcile_order_returns_none_when_not_filled(db_session):
    await _seed_strategy(db_session, "MOMENTUM-011")
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, event_time
            ) VALUES (
                'PAPER-TEST-2', 'MOMENTUM-011', 'coid-2', 'BTC/USDT', 'buy', 0.01,
                'SUBMITTED', 50000.0, 0.01, now()
            )
            """
        )
    )
    await db_session.commit()
    assert await reconcile_order(db_session, order_id="PAPER-TEST-2") is None


async def test_check_worse_than_holding_fires_on_losing_curve(db_session):
    await _seed_strategy(db_session, "MOMENTUM-012")

    # Seed real ohlcv_bars directly (rather than skipif-gating on
    # production data being present) -- 9 daily bars for BTC/USDT with a
    # mildly rising close, so compute_benchmark_curve has a real,
    # deterministic, non-empty curve to compare against.
    for i in range(1, 10):
        event_time = datetime(2026, 1, i, tzinfo=UTC)
        close = 50000.0 + i * 100.0
        db_session.add(
            OhlcvBarModel(
                symbol="BTC/USDT",
                timeframe="1d",
                event_time=event_time,
                available_at=event_time,
                source="test-fixture",
                revision=1,
                open=close,
                high=close * 1.001,
                low=close * 0.999,
                close=close,
                volume=1000.0,
            )
        )
    await db_session.commit()

    # A strictly losing paper equity curve against a flat/rising
    # benchmark should fire the finding.
    losing_curve = [
        (datetime(2026, 1, i, tzinfo=UTC).date(), 1000.0 - i * 10) for i in range(1, 10)
    ]
    fired = await check_worse_than_holding(
        db_session,
        strategy_id="MOMENTUM-012",
        symbol="BTC/USDT",
        paper_equity_curve=losing_curve,
        as_of_cutoff=datetime(2026, 1, 9, tzinfo=UTC),
    )
    assert fired is True

    findings = (
        await db_session.execute(
            text("SELECT finding_type FROM paper_findings WHERE strategy_id = 'MOMENTUM-012'")
        )
    ).fetchall()
    assert any(row.finding_type == "PAPER_WORSE_THAN_HOLDING" for row in findings)


async def test_compute_paper_equity_curve_from_real_fills(db_session):
    await _seed_strategy(db_session, "MOMENTUM-013")
    # Buy 0.01 BTC at 50000, then sell 0.005 at 51000 -- cash and
    # position both move, and the curve must reflect BOTH fills, not
    # just the size of the last one.
    await db_session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, symbol, side, qty, status,
                expected_price, expected_qty, filled_qty, avg_fill_price,
                event_time, submitted_at, filled_at
            ) VALUES
            ('PAPER-TEST-3A', 'MOMENTUM-013', 'coid-3a', 'BTC/USDT', 'buy', 0.01, 'FILLED',
             50000.0, 0.01, 0.01, 50000.0,
             now() - interval '2 hours', now() - interval '2 hours', now() - interval '2 hours'),
            ('PAPER-TEST-3B', 'MOMENTUM-013', 'coid-3b', 'BTC/USDT', 'sell', 0.005, 'FILLED',
             51000.0, 0.005, 0.005, 51000.0,
             now() - interval '1 hour', now() - interval '1 hour', now() - interval '1 hour')
            """
        )
    )
    await db_session.commit()

    curve = await compute_paper_equity_curve(
        db_session, strategy_id="MOMENTUM-013", current_price=52000.0
    )
    assert len(curve) == 3  # one point per fill, plus the final mark-to-market point

    # After fill 1 (buy 0.01 @ 50000): cash = 1000 - 500 = 500, position = 0.01
    # equity = 500 + 0.01 * 50000 = 1000
    assert curve[0][1] == pytest.approx(1000.0, abs=1e-6)

    # After fill 2 (sell 0.005 @ 51000): cash = 500 + 255 = 755, position = 0.005
    # equity = 755 + 0.005 * 51000 = 1010
    assert curve[1][1] == pytest.approx(1010.0, abs=1e-6)

    # Final point marked at current_price=52000, not the last fill's price:
    # equity = 755 + 0.005 * 52000 = 1015
    assert curve[2][1] == pytest.approx(1015.0, abs=1e-6)


async def test_compute_paper_equity_curve_empty_with_no_fills(db_session):
    curve = await compute_paper_equity_curve(
        db_session, strategy_id="MOMENTUM-NONEXISTENT", current_price=100.0
    )
    assert curve == []

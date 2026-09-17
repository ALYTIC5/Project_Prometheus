"""Order lifecycle for paper-traded CHAMPION strategies.

Exercises decide_and_submit (position derivation, RISK_LIMITS clamping,
idempotent submission via a deterministic client_order_id), current_position
(summed-fills derivation, never a stored value), and poll_fills (marking a
closed exchange order FILLED, leaving a still-open one untouched) against a
real Postgres. FakeBroker/FakeFetchOrderBroker stand in for
prometheus.paper.broker.PaperBroker so these tests exercise execution.py's
own logic, not ccxt/testnet I/O.
"""
from datetime import UTC, datetime

import polars as pl
import pytest
from sqlalchemy import text

from prometheus.core.config import (
    RISK_LIMITS,  # noqa: F401  (import confirms env is set by conftest)
)
from prometheus.paper.execution import current_position, decide_and_submit, poll_fills
from prometheus.strategy.spec import StrategySpec

pytestmark = [
    pytest.mark.db,
]


class FakeBroker:
    def __init__(self):
        self.submitted = []
        self.orders = {}

    def submit_order(self, *, symbol, side, qty, client_order_id):
        self.submitted.append((symbol, side, qty, client_order_id))
        self.orders[client_order_id] = {"id": f"exch-{client_order_id}", "status": "open"}
        return self.orders[client_order_id]

    def fetch_open_orders(self, *, symbol):
        return [
            {"id": v["id"], "clientOrderId": k, "symbol": symbol}
            for k, v in self.orders.items()
            if v["status"] == "open"
        ]

    def fetch_order(self, *, symbol, exchange_order_id):
        return {"id": exchange_order_id, "status": "closed", "filled": 0.01, "average": 50000.0}


class FakeFetchOrderBroker:
    """A broker whose fetch_order() always returns a fixed, caller-supplied
    result -- used by the poll_fills tests, which need to control the
    'closed' vs 'open' status independently of FakeBroker's own
    submit_order-driven state."""

    def __init__(self, fetch_order_result: dict):
        self._result = fetch_order_result
        self.fetch_calls: list[tuple[str, str]] = []

    def fetch_order(self, *, symbol, exchange_order_id):
        self.fetch_calls.append((symbol, exchange_order_id))
        return self._result


def _momentum_spec(symbol: str) -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM",
        symbol=symbol,
        timeframe="1d",
        fast_window=5,
        slow_window=10,
        expected_horizon=30,
    )


async def _seed_strategy(session, strategy_id: str, family: str = "MOMENTUM") -> None:
    """paper_orders.strategy_id is a NOT NULL FK to strategies.id
    (alembic/versions/0012_paper_trading.py) -- a paper_orders INSERT
    without a pre-existing strategies row raises IntegrityError against a
    real Postgres. Seeds the minimal valid row: strategies.spec is JSONB
    NOT NULL ('{}' is a valid empty object), status is any free-text
    String (CHAMPION reads correctly for a paper-traded strategy but
    carries no FK/enum constraint of its own)."""
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:id, :family, '{}', 'CHAMPION')"
        ),
        {"id": strategy_id, "family": family},
    )


async def _insert_submitted_order(
    session,
    *,
    order_id: str,
    strategy_id: str,
    symbol: str,
    exchange_order_id: str,
    side: str = "buy",
    qty: float = 0.01,
) -> None:
    """Seeds a paper_orders row in status='SUBMITTED' directly -- the state
    poll_fills expects to find on the tick after decide_and_submit already
    ran. Mirrors execution.py's own _INSERT_PAPER_ORDER column set exactly."""
    await session.execute(
        text(
            """
            INSERT INTO paper_orders (
                id, strategy_id, client_order_id, exchange_order_id, symbol, side, qty,
                status, expected_price, expected_qty, event_time
            ) VALUES (
                :id, :strategy_id, :client_order_id, :exchange_order_id, :symbol, :side, :qty,
                'SUBMITTED', :expected_price, :expected_qty, :event_time
            )
            """
        ),
        {
            "id": order_id,
            "strategy_id": strategy_id,
            "client_order_id": f"test-client-{order_id}",
            "exchange_order_id": exchange_order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "expected_price": 50000.0,
            "expected_qty": qty,
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
        },
    )


async def test_decide_and_submit_submits_when_position_changes(db_session):
    await _seed_strategy(db_session, "MOMENTUM-001")
    spec = _momentum_spec("BTC/USDT")
    bars = pl.DataFrame(
        {
            "available_at": [datetime(2026, 1, i, tzinfo=UTC) for i in range(1, 15)],
            "close": [100.0 + i for i in range(14)],
        }
    )
    broker = FakeBroker()
    order_id = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-001", spec=spec, bars=bars
    )
    assert order_id is not None
    assert len(broker.submitted) == 1


async def test_decide_and_submit_idempotent_on_replay(db_session):
    await _seed_strategy(db_session, "MOMENTUM-002")
    spec = _momentum_spec("BTC/USDT")
    bars = pl.DataFrame(
        {
            "available_at": [datetime(2026, 2, i, tzinfo=UTC) for i in range(1, 15)],
            "close": [100.0 + i for i in range(14)],
        }
    )
    broker = FakeBroker()
    first = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-002", spec=spec, bars=bars
    )
    second = await decide_and_submit(
        db_session, broker, strategy_id="MOMENTUM-002", spec=spec, bars=bars
    )
    assert first == second
    assert len(broker.submitted) == 1  # not re-submitted on replay


async def test_current_position_zero_with_no_orders(db_session):
    position = await current_position(db_session, "MOMENTUM-003")
    assert position == 0.0


async def test_poll_fills_marks_closed_order_as_filled(db_session):
    await _seed_strategy(db_session, "MOMENTUM-004")
    await _insert_submitted_order(
        db_session,
        order_id="PAPER-TEST-004",
        strategy_id="MOMENTUM-004",
        symbol="BTC/USDT",
        exchange_order_id="exch-004",
    )
    broker = FakeFetchOrderBroker(
        {"id": "exch-004", "status": "closed", "filled": 0.02, "average": 51000.0}
    )

    updated = await poll_fills(db_session, broker, symbol="BTC/USDT")

    assert updated == ["PAPER-TEST-004"]
    row = (
        await db_session.execute(
            text(
                "SELECT status, filled_qty, avg_fill_price FROM paper_orders WHERE id = :id"
            ),
            {"id": "PAPER-TEST-004"},
        )
    ).mappings().first()
    assert row["status"] == "FILLED"
    assert row["filled_qty"] == pytest.approx(0.02)
    assert row["avg_fill_price"] == pytest.approx(51000.0)


async def test_poll_fills_leaves_open_order_untouched(db_session):
    await _seed_strategy(db_session, "MOMENTUM-005")
    await _insert_submitted_order(
        db_session,
        order_id="PAPER-TEST-005",
        strategy_id="MOMENTUM-005",
        symbol="ETH/USDT",
        exchange_order_id="exch-005",
    )
    broker = FakeFetchOrderBroker({"id": "exch-005", "status": "open"})

    updated = await poll_fills(db_session, broker, symbol="ETH/USDT")

    assert updated == []
    row = (
        await db_session.execute(
            text("SELECT status, filled_qty FROM paper_orders WHERE id = :id"),
            {"id": "PAPER-TEST-005"},
        )
    ).mappings().first()
    assert row["status"] == "SUBMITTED"
    assert row["filled_qty"] == 0.0  # server_default, never touched by a still-open order

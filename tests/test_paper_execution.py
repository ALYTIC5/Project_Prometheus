"""Order lifecycle for paper-traded CHAMPION strategies.

Exercises decide_and_submit (position derivation, RISK_LIMITS clamping,
idempotent submission via a deterministic client_order_id) and
current_position (summed-fills derivation, never a stored value) against
a real Postgres. FakeBroker stands in for prometheus.paper.broker.PaperBroker
so these tests exercise execution.py's own logic, not ccxt/testnet I/O.
"""
from datetime import UTC, datetime

import polars as pl
import pytest

from prometheus.core.config import (
    RISK_LIMITS,  # noqa: F401  (import confirms env is set by conftest)
)
from prometheus.paper.execution import current_position, decide_and_submit
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


def _momentum_spec(symbol: str) -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM",
        symbol=symbol,
        timeframe="1d",
        fast_window=5,
        slow_window=10,
        expected_horizon=30,
    )


async def test_decide_and_submit_submits_when_position_changes(db_session):
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

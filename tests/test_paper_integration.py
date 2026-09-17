# tests/test_paper_integration.py
import os

import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not (os.environ.get("PAPER_API_KEY") and os.environ.get("PAPER_API_SECRET")),
        reason="requires real PAPER_API_KEY/PAPER_API_SECRET testnet credentials",
    ),
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0012 applied)",
    ),
]


async def test_broker_connects_to_real_testnet():
    from prometheus.paper.broker import PaperBroker

    broker = PaperBroker()
    # A real, harmless read-only call against the real testnet --
    # confirms credentials and connectivity without submitting an order.
    open_orders = broker.fetch_open_orders(symbol="BTC/USDT")
    assert isinstance(open_orders, list)

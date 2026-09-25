"""paper/sim_broker.py -- the internal simulated paper broker (Law 5: no
network, no venue). Pure, no DB."""
from __future__ import annotations

import pytest

from prometheus.backtest.costs import load_cost_config
from prometheus.paper.divergence import _is_material
from prometheus.paper.sim_broker import SimBroker


def test_buy_fills_at_reference_plus_slippage_sell_at_minus() -> None:
    slip = load_cost_config()[0].slippage_bps / 10_000.0
    broker = SimBroker()
    assert broker.fill_price("buy", 100.0) == pytest.approx(100.0 * (1 + slip))
    assert broker.fill_price("sell", 100.0) == pytest.approx(100.0 * (1 - slip))


def test_order_id_round_trips_its_fill_statelessly() -> None:
    broker = SimBroker()
    submitted = broker.submit_order(
        symbol="NEAR/USDT", side="buy", qty=12.5, client_order_id="c1", reference_price=2.0
    )
    fetched = SimBroker().fetch_order(symbol="NEAR/USDT", exchange_order_id=submitted["id"])
    assert fetched["status"] == "closed"
    assert fetched["filled"] == 12.5
    assert fetched["average"] == pytest.approx(broker.fill_price("buy", 2.0))
    assert len(submitted["id"]) <= 64  # paper_orders.exchange_order_id width


def test_fills_at_exactly_modelled_slippage_are_not_material_divergence() -> None:
    """A sim fill always slips by exactly slippage_bps -- zero variance,
    mean equal to the baseline up to float representation. Must never
    read as divergence (that would quarantine every champion)."""
    broker = SimBroker()
    slip_pct = load_cost_config()[0].slippage_bps / 100.0
    deltas = [
        (broker.fill_price("buy", p) - p) / p * 100 for p in (1.7, 2.3, 84411.53, 0.00031)
    ]
    assert not _is_material(deltas, assumed_baseline_pct=slip_pct)


def test_rejects_a_non_simulated_order_id() -> None:
    with pytest.raises(ValueError):
        SimBroker().fetch_order(symbol="X", exchange_order_id="123456")

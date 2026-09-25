"""Internal simulated paper broker -- Law 5 by construction: no network, no
venue, no credentials. Used when Binance testnet credentials
(PAPER_API_KEY/PAPER_API_SECRET) are not configured (2026-09-25, user
direction: "have your own internal paper trading systems").

Fill model: a market order fills in full at the decision bar's close (the
price execution.decide_and_submit already records as expected_price),
moved against the trader by config/costs.yaml's slippage_bps. The taker
fee is charged separately in reconciliation.compute_paper_equity_curve,
exactly as a real exchange reports price and fee separately -- and
divergence.check_divergence's baseline is slippage alone, so folding the
fee into the fill price would read as a permanent, zero-variance
"divergence" and quarantine every champion. Same close-to-close convention
and same cost model as the backtest engine. So paper trading here is an
honest FORWARD test of each champion on data it has never seen, not a
test of real exchange execution: backtest-vs-paper divergence will read
~zero by construction, and that is
stated rather than hidden (see docs/DECISIONS.md).

Stateless across worker runs (the worker is a cron job that exits): the
simulated exchange order id encodes its own fill -- "SIM:<side>:<price>:
<qty>" -- so fetch_order in a later run needs no stored broker state.
"""
from __future__ import annotations

from typing import Any

from prometheus.backtest.costs import load_cost_config

_PREFIX = "SIM"


class SimBroker:
    """Same method surface as paper.broker.PaperBroker (duck-typed by
    paper/execution.py and worker._run_paper)."""

    def __init__(self) -> None:
        config, _ = load_cost_config()
        self._adverse_fraction = config.slippage_bps / 10_000.0

    def fill_price(self, side: str, reference_price: float) -> float:
        sign = 1.0 if side == "buy" else -1.0
        return reference_price * (1.0 + sign * self._adverse_fraction)

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        reference_price: float,
    ) -> dict[str, Any]:
        price = self.fill_price(side, reference_price)
        order_id = f"{_PREFIX}:{side}:{price:.8f}:{qty:.8f}"
        return {"id": order_id, "clientOrderId": client_order_id, "status": "closed"}

    def fetch_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        prefix, side, price, qty = exchange_order_id.split(":")
        if prefix != _PREFIX:
            raise ValueError(f"not a simulated order id: {exchange_order_id!r}")
        return {
            "id": exchange_order_id,
            "side": side,
            "status": "closed",
            "filled": float(qty),
            "average": float(price),
        }

    def fetch_open_orders(self, *, symbol: str) -> list[dict[str, Any]]:
        return []  # every simulated market order fills immediately

    def cancel_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        return self.fetch_order(symbol=symbol, exchange_order_id=exchange_order_id)

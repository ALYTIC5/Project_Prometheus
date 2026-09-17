"""Order lifecycle for paper-traded CHAMPION strategies. Position is
DERIVED by summing filled paper_orders, never stored separately -- one
source of truth, no dual-write drift between an orders table and a
positions table.

The trading decision always uses signal_for() on 1d bars, identical to
the backtest -- this module never recomputes a signal on a shorter bar
(see docs/superpowers/specs/2026-09-17-paper-trading-design.md's cadence
discussion). What runs on every 15-minute worker tick is poll_fills, not
a new trading decision.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.engine import STARTING_CAPITAL, signal_for
from prometheus.core.config import RISK_LIMITS
from prometheus.core.ids import next_paper_order_id
from prometheus.strategy.spec import StrategySpec

_SELECT_FILLED_QTY = text(
    """
    SELECT COALESCE(SUM(
        CASE WHEN side = 'buy' THEN filled_qty ELSE -filled_qty END
    ), 0) AS net_qty
    FROM paper_orders
    WHERE strategy_id = :strategy_id AND status = 'FILLED'
    """
)

_SELECT_EXISTING_BY_CLIENT_ORDER_ID = text(
    "SELECT id FROM paper_orders WHERE client_order_id = :client_order_id"
)

_INSERT_PAPER_ORDER = text(
    """
    INSERT INTO paper_orders (
        id, strategy_id, client_order_id, exchange_order_id, symbol, side, qty,
        status, expected_price, expected_qty, event_time
    ) VALUES (
        :id, :strategy_id, :client_order_id, :exchange_order_id, :symbol, :side, :qty,
        'SUBMITTED', :expected_price, :expected_qty, :event_time
    )
    """
)

_SELECT_OPEN_ORDERS = text(
    """
    SELECT id, exchange_order_id, symbol FROM paper_orders
    WHERE status = 'SUBMITTED' AND symbol = :symbol
    """
)

_UPDATE_FILL = text(
    """
    UPDATE paper_orders
       SET status = 'FILLED', filled_qty = :filled_qty, avg_fill_price = :avg_fill_price,
           filled_at = now()
     WHERE id = :id
    """
)


async def current_position(session: AsyncSession, strategy_id: str) -> float:
    """Net base-asset quantity held, derived from every FILLED order's
    signed quantity -- never a separately stored, driftable value."""
    result = await session.execute(_SELECT_FILLED_QTY, {"strategy_id": strategy_id})
    return float(result.scalar_one())


def _client_order_id(strategy_id: str, event_time: datetime, side: str) -> str:
    """Deterministic -- a tick replayed after a crash (same strategy,
    same decision bar, same side) produces the identical id, making
    re-submission a safe no-op via the SELECT-before-INSERT check in
    decide_and_submit, the same idempotency shape queue.enqueue() uses
    for jobs."""
    raw = f"{strategy_id}|{event_time.isoformat()}|{side}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _clamp_target_qty(target_qty: float, price: float) -> float:
    """Law 4: order sizing never exceeds RISK_LIMITS, applied against
    this strategy's own €1000 paper capital (STARTING_CAPITAL), not the
    whole paper-trading book. MAX_LEVERAGE would only matter for a
    margined position, which nothing here ever opens (spot only) --
    included anyway so a future margin feature can't silently bypass it."""
    max_notional = STARTING_CAPITAL * min(
        RISK_LIMITS.MAX_POSITION_PCT / 100.0, RISK_LIMITS.MAX_GROSS_EXPOSURE_PCT / 100.0
    ) * RISK_LIMITS.MAX_LEVERAGE
    max_qty = max_notional / price
    return max(min(target_qty, max_qty), -max_qty)


async def decide_and_submit(
    session: AsyncSession,
    broker: Any,
    *,
    strategy_id: str,
    spec: StrategySpec,
    bars: pl.DataFrame,
) -> str | None:
    """Computes the champion's target position from the exact same
    signal_for() the backtest uses, diffs it against the currently held
    quantity, and submits the delta as a market order sized off €1000
    notional and clamped by RISK_LIMITS. Returns None if no change is
    needed (target already matches current position) or if this exact
    decision (strategy_id, event_time, side) was already submitted --
    the caller should call this every tick; it is a safe no-op when
    there is nothing new to do.
    """
    signaled = signal_for(bars, spec)
    last_row = signaled.tail(1).to_dicts()[0]
    target_fraction = last_row["position"]
    price = bars.tail(1)["close"][0]
    event_time = bars.tail(1)["available_at"][0]

    target_qty = _clamp_target_qty((target_fraction * STARTING_CAPITAL) / price, price)
    held_qty = await current_position(session, strategy_id)
    delta = target_qty - held_qty
    if abs(delta) < 1e-8:
        return None

    side = "buy" if delta > 0 else "sell"
    client_order_id = _client_order_id(strategy_id, event_time, side)

    existing = await session.execute(
        _SELECT_EXISTING_BY_CLIENT_ORDER_ID, {"client_order_id": client_order_id}
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is not None:
        return str(existing_id)

    result = broker.submit_order(
        symbol=spec.symbol, side=side, qty=abs(delta), client_order_id=client_order_id
    )
    order_id = await next_paper_order_id()
    await session.execute(
        _INSERT_PAPER_ORDER,
        {
            "id": order_id,
            "strategy_id": strategy_id,
            "client_order_id": client_order_id,
            "exchange_order_id": result.get("id"),
            "symbol": spec.symbol,
            "side": side,
            "qty": abs(delta),
            "expected_price": price,
            "expected_qty": abs(delta),
            "event_time": event_time,
        },
    )
    await session.commit()
    return order_id


async def poll_fills(session: AsyncSession, broker: Any, *, symbol: str) -> list[str]:
    """Called every 15-minute tick regardless of whether a new bar
    closed -- checks every still-SUBMITTED order for this symbol against
    the exchange and records fills. Returns the ids of orders updated
    this call."""
    open_rows = (await session.execute(_SELECT_OPEN_ORDERS, {"symbol": symbol})).fetchall()
    updated: list[str] = []
    for row in open_rows:
        fetched = broker.fetch_order(symbol=symbol, exchange_order_id=row.exchange_order_id)
        if fetched.get("status") != "closed":
            continue
        await session.execute(
            _UPDATE_FILL,
            {
                "id": row.id,
                "filled_qty": fetched.get("filled", 0.0),
                "avg_fill_price": fetched.get("average"),
            },
        )
        updated.append(row.id)
    if updated:
        await session.commit()
    return updated

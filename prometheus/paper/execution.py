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
import json
from datetime import UTC, datetime
from typing import Any

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import load_cost_config
from prometheus.backtest.engine import STARTING_CAPITAL, signal_for
from prometheus.core.config import RISK_LIMITS
from prometheus.core.ids import next_paper_order_id
from prometheus.paper.reconciliation import compute_paper_equity_curve
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
    whole paper-trading book.

    I4 (final-review fix wave): MAX_LEVERAGE is one more independent cap
    inside the min(...), not a multiplying factor on top of the other
    two -- .env.example documents it as "max gross exposure divided by
    equity, as a multiplier (1 = unlevered)", i.e. a ceiling, and
    multiplying by it can only ever relax MAX_POSITION_PCT/
    MAX_GROSS_EXPOSURE_PCT, which is backwards for a risk limit (with the
    test sentinels 11/22/3, the old formula's effective cap was 33%
    despite MAX_POSITION_PCT=11). MAX_LEVERAGE would only matter for a
    margined position, which nothing here ever opens (spot only) --
    included anyway so a future margin feature can't silently bypass it."""
    max_notional = STARTING_CAPITAL * min(
        RISK_LIMITS.MAX_POSITION_PCT / 100.0,
        RISK_LIMITS.MAX_GROSS_EXPOSURE_PCT / 100.0,
        RISK_LIMITS.MAX_LEVERAGE,
    )
    max_qty = max_notional / price
    return max(min(target_qty, max_qty), -max_qty)


_SELECT_FILLS_BEFORE = text(
    """
    SELECT side, filled_qty, avg_fill_price FROM paper_orders
     WHERE strategy_id = :strategy_id AND status = 'FILLED'
       AND avg_fill_price IS NOT NULL AND filled_qty IS NOT NULL
       AND filled_at < :before
     ORDER BY filled_at
    """
)
_SELECT_MARK_BEFORE = text(
    """
    SELECT close FROM paper_marks
     WHERE symbol = :symbol AND bar_available_at < :before
     ORDER BY bar_available_at DESC LIMIT 1
    """
)
_SELECT_FINDING_SINCE = text(
    """
    SELECT 1 FROM paper_findings
     WHERE strategy_id = :strategy_id AND finding_type = :finding_type AND detected_at >= :since
     LIMIT 1
    """
)
_INSERT_FINDING = text(
    """
    INSERT INTO paper_findings (strategy_id, finding_type, detail)
    VALUES (:strategy_id, :finding_type, CAST(:detail AS jsonb))
    """
)


async def _start_of_day_equity(
    session: AsyncSession, *, strategy_id: str, symbol: str, day_start: datetime
) -> float:
    """Equity at the start of the UTC day: every fill before it replayed
    (same cash/fee accounting as reconciliation.compute_paper_equity_curve),
    the position valued at the last mark before it."""
    fee_fraction = load_cost_config()[0].taker_fee_bps / 10_000.0
    cash, qty, last_fill_price = STARTING_CAPITAL, 0.0, None
    for row in (
        await session.execute(
            _SELECT_FILLS_BEFORE, {"strategy_id": strategy_id, "before": day_start}
        )
    ).fetchall():
        signed = float(row.filled_qty) if row.side == "buy" else -float(row.filled_qty)
        price = float(row.avg_fill_price)
        cash -= signed * price + abs(signed) * price * fee_fraction
        qty += signed
        last_fill_price = price
    if qty == 0:
        return cash
    mark = (
        await session.execute(_SELECT_MARK_BEFORE, {"symbol": symbol, "before": day_start})
    ).scalar_one_or_none()
    price = float(mark) if mark is not None else float(last_fill_price or 0.0)
    return cash + qty * price


def breached_limit(
    *, equity: float, peak: float, start_of_day: float
) -> tuple[str, dict[str, float]] | None:
    """Law 4's loss limits against this strategy's own paper account.
    Drawdown first: it is the harder stop."""
    drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
    if drawdown_pct >= RISK_LIMITS.MAX_DRAWDOWN_PCT:
        return "RISK_MAX_DRAWDOWN", {
            "drawdown_pct": drawdown_pct, "limit_pct": RISK_LIMITS.MAX_DRAWDOWN_PCT,
            "equity": equity, "peak": peak,
        }
    daily_loss_pct = (start_of_day - equity) / start_of_day * 100 if start_of_day > 0 else 0.0
    if daily_loss_pct >= RISK_LIMITS.MAX_DAILY_LOSS_PCT:
        return "RISK_DAILY_LOSS", {
            "daily_loss_pct": daily_loss_pct, "limit_pct": RISK_LIMITS.MAX_DAILY_LOSS_PCT,
            "equity": equity, "start_of_day": start_of_day,
        }
    return None


async def check_risk_limits(
    session: AsyncSession, *, strategy_id: str, symbol: str, price: float, now: datetime
) -> str | None:
    """Returns the breached limit's finding type (and records it, once per
    strategy per UTC day), or None. A drawdown breach persists once the
    strategy is flat -- flat equity cannot climb back to its peak -- so it
    halts that strategy's paper trading until a human intervenes; a daily
    loss clears the next UTC day."""
    curve = await compute_paper_equity_curve(session, strategy_id=strategy_id, current_price=price)
    equity = curve[-1][1] if curve else STARTING_CAPITAL
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    start_of_day = await _start_of_day_equity(
        session, strategy_id=strategy_id, symbol=symbol, day_start=day_start
    )
    peak = max([STARTING_CAPITAL, start_of_day, equity, *(point for _, point in curve)])
    breach = breached_limit(equity=equity, peak=peak, start_of_day=start_of_day)
    if breach is None:
        return None
    finding_type, detail = breach
    already = (
        await session.execute(
            _SELECT_FINDING_SINCE,
            {"strategy_id": strategy_id, "finding_type": finding_type, "since": day_start},
        )
    ).first()
    if already is None:
        await session.execute(
            _INSERT_FINDING,
            {"strategy_id": strategy_id, "finding_type": finding_type,
             "detail": json.dumps(detail)},
        )
    return finding_type


async def decide_and_submit(
    session: AsyncSession,
    broker: Any,
    *,
    strategy_id: str,
    spec: StrategySpec,
    bars: pl.DataFrame,
    force_flat: bool = False,
    now: datetime | None = None,
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
    # I5 (final-review fix wave): Law 4 / .env.example's own documented
    # contract -- "true = no new positions, regardless of every limit
    # above" -- was previously enforced nowhere. Checked first, before
    # computing a signal or touching the broker at all: a no-op, exactly
    # like "no change needed".
    if RISK_LIMITS.KILL_SWITCH:
        return None

    price = bars.tail(1)["close"][0]
    event_time = bars.tail(1)["available_at"][0]
    if force_flat:
        # No longer eligible (demoted): close out, never open.
        target_fraction = 0.0
    else:
        signaled = signal_for(bars, spec)
        target_fraction = signaled.tail(1).to_dicts()[0]["position"]
        breached = await check_risk_limits(
            session, strategy_id=strategy_id, symbol=spec.symbol, price=float(price),
            now=now or datetime.now(UTC),
        )
        if breached is not None:
            target_fraction = 0.0

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
        symbol=spec.symbol,
        side=side,
        qty=abs(delta),
        client_order_id=client_order_id,
        reference_price=price,
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
        filled_qty = fetched.get("filled")
        avg_fill_price = fetched.get("average")
        if filled_qty is None or avg_fill_price is None:
            # I1 (final-review fix wave): the exchange reported the order
            # "closed" but didn't (yet) give us fill data -- .get(...)
            # with no default so a present-but-null value is caught the
            # same as a missing key. Leave the row SUBMITTED so next
            # tick's poll_fills retries, instead of writing None/0.0 into
            # a NOT NULL column that reconcile_order/
            # compute_paper_equity_curve would later choke on every tick.
            continue
        await session.execute(
            _UPDATE_FILL,
            {
                "id": row.id,
                "filled_qty": filled_qty,
                "avg_fill_price": avg_fill_price,
            },
        )
        updated.append(row.id)
    if updated:
        await session.commit()
    return updated

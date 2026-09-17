"""Compares every FILLED paper order against what was expected at
submission time, and compares realized paper equity against a €1000
buy-and-hold over the same window (Law 8) -- the same
backtest.benchmark.compute_benchmark_curve every other Law-8 comparison
in this codebase uses, not a second benchmark computation.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.benchmark import compute_benchmark_curve
from prometheus.backtest.engine import STARTING_CAPITAL
from prometheus.core.db import PaperFinding
from prometheus.data.loaders import load_point_in_time

_SELECT_ORDER = text(
    """
    SELECT expected_price, expected_qty, filled_qty, avg_fill_price,
           submitted_at, filled_at, status
      FROM paper_orders WHERE id = :order_id
    """
)

_SELECT_FILLED_ORDERS_CHRONO = text(
    """
    SELECT side, filled_qty, avg_fill_price, filled_at
      FROM paper_orders
     WHERE strategy_id = :strategy_id AND status = 'FILLED'
     ORDER BY filled_at
    """
)


async def reconcile_order(session: AsyncSession, *, order_id: str) -> dict[str, float] | None:
    """None if the order hasn't reached FILLED yet -- there is nothing
    to reconcile against a still-open order."""
    row = (await session.execute(_SELECT_ORDER, {"order_id": order_id})).first()
    if row is None or row.status != "FILLED":
        return None

    price_delta_pct = (float(row.avg_fill_price) - float(row.expected_price)) / float(
        row.expected_price
    ) * 100
    qty_delta_pct = (float(row.filled_qty) - float(row.expected_qty)) / float(row.expected_qty) * 100
    latency_seconds = (row.filled_at - row.submitted_at).total_seconds()

    return {
        "price_delta_pct": price_delta_pct,
        "qty_delta_pct": qty_delta_pct,
        "latency_seconds": latency_seconds,
    }


async def compute_paper_equity_curve(
    session: AsyncSession, *, strategy_id: str, current_price: float
) -> list[tuple[date, float]]:
    """A REAL mark-to-market equity curve built from actual fills --
    cash (STARTING_CAPITAL, debited by every buy's notional and credited
    by every sell's) plus the current position's value, same accounting
    shape backtest.engine._run_accounting produces from simulated
    positions, now built from real filled orders. This is deliberately
    NOT "the notional of each individual trade" -- a list of per-trade
    notionals is not an equity curve and cannot be meaningfully compared
    against compute_benchmark_curve's final portfolio value.

    One point per fill event (marked at that fill's own price), plus a
    final point marked at `current_price` (the latest close) -- an open
    position's value moves with the market between fills, not just at
    the moment of the last trade."""
    rows = (
        await session.execute(_SELECT_FILLED_ORDERS_CHRONO, {"strategy_id": strategy_id})
    ).fetchall()
    if not rows:
        return []

    cash = STARTING_CAPITAL
    position_qty = 0.0
    curve: list[tuple[date, float]] = []
    for row in rows:
        signed_qty = float(row.filled_qty) if row.side == "buy" else -float(row.filled_qty)
        cash -= signed_qty * float(row.avg_fill_price)
        position_qty += signed_qty
        curve.append((row.filled_at.date(), cash + position_qty * float(row.avg_fill_price)))

    curve.append((rows[-1].filled_at.date(), cash + position_qty * current_price))
    return curve


async def check_worse_than_holding(
    session: AsyncSession,
    *,
    strategy_id: str,
    symbol: str,
    paper_equity_curve: list[tuple[date, float]],
    as_of_cutoff: datetime,
) -> bool:
    """Compares the champion's realized paper equity (compute_paper_equity_curve's
    output) against a €1000 buy-and-hold of its own symbol over the
    identical window (Law 8). Writes and prominently surfaces
    PAPER_WORSE_THAN_HOLDING -- checked FIRST, same ordering
    validation/decision.py already establishes for the backtest-time
    equivalent of this same check."""
    if not paper_equity_curve:
        return False

    window_start = datetime.combine(paper_equity_curve[0][0], time.min, tzinfo=UTC)
    pit, _data_version_hash = await load_point_in_time(
        session, [symbol], "1d", window_start, as_of_cutoff
    )
    benchmark = compute_benchmark_curve(pit, [symbol], as_of_cutoff)
    if not benchmark.equity_curve:
        return False

    paper_final = paper_equity_curve[-1][1]
    benchmark_final = benchmark.final_value
    if paper_final >= benchmark_final:
        return False

    session.add(
        PaperFinding(
            strategy_id=strategy_id,
            finding_type="PAPER_WORSE_THAN_HOLDING",
            detail={
                "paper_final_value": paper_final,
                "benchmark_final_value": benchmark_final,
                "as_of_cutoff": as_of_cutoff.isoformat(),
            },
        )
    )
    await session.commit()
    return True

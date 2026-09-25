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
from prometheus.backtest.costs import apply_cost, load_cost_config
from prometheus.backtest.engine import STARTING_CAPITAL
from prometheus.core.db import PaperFinding
from prometheus.data.loaders import load_point_in_time

_SELECT_ORDER = text(
    """
    SELECT expected_price, expected_qty, filled_qty, avg_fill_price,
           submitted_at, filled_at, status, side
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


async def reconcile_order(session: AsyncSession, *, order_id: str) -> dict[str, float | str] | None:
    """None if the order hasn't reached FILLED yet -- there is nothing
    to reconcile against a still-open order.

    Also returns None (I1, final-review fix wave) if a FILLED row somehow
    carries a NULL avg_fill_price/filled_qty -- execution.py's poll_fills
    now refuses to mark an order FILLED without both values, but this is
    a second, independent guard: since worker.py re-reconciles a
    strategy's FULL fill history every tick, one bad historical row
    raising TypeError here would otherwise break every future tick for
    that champion forever."""
    row = (await session.execute(_SELECT_ORDER, {"order_id": order_id})).first()
    if row is None or row.status != "FILLED":
        return None
    if row.avg_fill_price is None or row.filled_qty is None:
        return None

    price_delta_pct = (float(row.avg_fill_price) - float(row.expected_price)) / float(
        row.expected_price
    ) * 100
    qty_delta_pct = (
        (float(row.filled_qty) - float(row.expected_qty)) / float(row.expected_qty) * 100
    )
    latency_seconds = (row.filled_at - row.submitted_at).total_seconds()

    return {
        "price_delta_pct": price_delta_pct,
        "qty_delta_pct": qty_delta_pct,
        "latency_seconds": latency_seconds,
        # C1 (final-review fix wave): divergence.py needs the order's side
        # to normalize price_delta_pct into "adverse slippage" (paying
        # more than expected on a buy vs. receiving less than expected on
        # a sell are both bad, but have opposite signs here) -- fetched
        # from this same row, no second query.
        "side": row.side,
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
    the moment of the last trade.

    Skips (I1, final-review fix wave) any row with a NULL avg_fill_price
    or filled_qty rather than raising -- execution.py's poll_fills now
    refuses to write a FILLED row without both, but this is a second,
    independent guard against one bad historical row taking down this
    strategy's equity curve, and therefore every future tick's
    PAPER_WORSE_THAN_HOLDING check, forever."""
    rows = (
        await session.execute(_SELECT_FILLED_ORDERS_CHRONO, {"strategy_id": strategy_id})
    ).fetchall()
    if not rows:
        return []

    # Law 8: the same cost model as the backtest and its benchmark. The
    # fill price already carries slippage; the taker fee is charged here on
    # each fill's notional (previously zero -- docs/DEFERRED.md I6).
    cost_config, _ = load_cost_config()
    fee_fraction = cost_config.taker_fee_bps / 10_000.0
    cash = STARTING_CAPITAL
    position_qty = 0.0
    curve: list[tuple[date, float]] = []
    last_valid_row = None
    for row in rows:
        if row.avg_fill_price is None or row.filled_qty is None:
            continue
        signed_qty = float(row.filled_qty) if row.side == "buy" else -float(row.filled_qty)
        cash -= signed_qty * float(row.avg_fill_price)
        cash -= abs(signed_qty) * float(row.avg_fill_price) * fee_fraction
        position_qty += signed_qty
        curve.append((row.filled_at.date(), cash + position_qty * float(row.avg_fill_price)))
        last_valid_row = row

    if last_valid_row is None:
        return []

    curve.append((last_valid_row.filled_at.date(), cash + position_qty * current_price))
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
    benchmark = compute_benchmark_curve(
        pit, [symbol], window_start=window_start, window_end=as_of_cutoff, cost_model=apply_cost
    )
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

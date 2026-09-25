"""Paper trading API endpoint -- surfaces the Harbour (PROMPT 8) for the
dashboard: which strategies currently hold CHAMPION status, each one's
real mark-to-market equity curve (built from actual fills, not
simulated), its recent orders, and any real divergence/worse-than-
holding findings. Previously invisible outside a direct DB query --
paper trading has genuinely never had a dashboard view.

Deliberately shows the champion's own equity curve only, not a live-
recomputed benchmark overlay: `backtest.benchmark.compute_benchmark_curve`
needs a full point-in-time load (the same cost worker.py's own paper
concern already pays every 15 minutes), and recomputing that on every
dashboard poll for however many champions exist would be a real,
avoidable cost this project's hosting-budget discipline exists to catch.
The global benchmark chart gets away with a cheap read because
`benchmark_equity` is periodically computed and stored, not live-fetched
per request -- a per-champion equivalent is the natural follow-up once
there's a real champion to store one for. There is not yet: as of this
route's first ship, zero strategies have ever reached CHAMPION status
(every validated strategy so far is REJECTed) -- an honest empty state,
not a placeholder.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory
from prometheus.paper.reconciliation import compute_paper_equity_curve
from prometheus.strategy.rotation_spec import ROTATION_FAMILIES, RotationSpec
from prometheus.strategy.spec import StrategySpec

router = APIRouter(prefix="/paper", tags=["paper"])

_SELECT_CHAMPIONS = text("SELECT id, family, spec FROM strategies WHERE status = 'CHAMPION'")

# The worker's own latest mark first (migration 0022): ohlcv_bars stops at
# holdout_start, so marking there alone freezes every open position's value.
_SELECT_LATEST_CLOSE = text(
    """
    SELECT close FROM (
        (SELECT close, 1 AS pref, marked_at AS at FROM paper_marks
          WHERE symbol = :symbol ORDER BY marked_at DESC LIMIT 1)
        UNION ALL
        (SELECT close, 2 AS pref, event_time AS at FROM ohlcv_bars
          WHERE symbol = :symbol ORDER BY event_time DESC LIMIT 1)
    ) latest
    ORDER BY pref
    LIMIT 1
    """
)

_SELECT_RECENT_ORDERS = text(
    """
    SELECT id, symbol, side, qty, status, expected_price, avg_fill_price,
           filled_qty, submitted_at, filled_at
      FROM paper_orders
     WHERE strategy_id = :strategy_id
     ORDER BY submitted_at DESC
     LIMIT 20
    """
)

_SELECT_RECENT_FINDINGS = text(
    """
    SELECT id, finding_type, detail, detected_at
      FROM paper_findings
     WHERE strategy_id = :strategy_id
     ORDER BY detected_at DESC
     LIMIT 10
    """
)


@router.get("/")
async def get_paper_trading_status() -> dict[str, Any]:
    async with get_session_factory()() as session:
        champion_rows = (await session.execute(_SELECT_CHAMPIONS)).fetchall()

        champions: list[dict[str, Any]] = []
        for row in champion_rows:
            # C1 (final-review fix wave): a rotation strategy can hold
            # CHAMPION status (validate_rotation_specs calls
            # elect_champions like every other validation path), and its
            # stored spec is a RotationSpec dump -- no `symbol`, so
            # StrategySpec.model_validate() raises ValidationError on it
            # and this endpoint 500s for every champion, not just that
            # one. It has no single symbol to mark against either, so
            # `symbol` becomes its universe as a display string and
            # current_price stays 0.0: rotation strategies are not wired
            # into paper-trading execution yet (the design doc's own
            # "Explicitly out of scope for this pass: Live paper-trading
            # execution"), so it has no fills, hence an empty curve,
            # empty orders and empty findings -- an honest empty state,
            # exactly what this route's own docstring describes for a
            # champion with nothing traded yet.
            if row.family in ROTATION_FAMILIES:
                rotation_spec = RotationSpec.model_validate(row.spec)
                display_symbol = ", ".join(rotation_spec.universe)
                current_price = 0.0
            else:
                spec = StrategySpec.model_validate(row.spec)
                display_symbol = spec.symbol
                latest_close = (
                    await session.execute(_SELECT_LATEST_CLOSE, {"symbol": spec.symbol})
                ).scalar_one_or_none()
                current_price = float(latest_close) if latest_close is not None else 0.0

            equity_curve = await compute_paper_equity_curve(
                session, strategy_id=row.id, current_price=current_price
            )

            orders = (
                await session.execute(_SELECT_RECENT_ORDERS, {"strategy_id": row.id})
            ).fetchall()
            findings = (
                await session.execute(_SELECT_RECENT_FINDINGS, {"strategy_id": row.id})
            ).fetchall()

            champions.append(
                {
                    "strategy_id": row.id,
                    "family": row.family,
                    "symbol": display_symbol,
                    "equity_curve": [
                        {"date": d.isoformat(), "equity": equity} for d, equity in equity_curve
                    ],
                    "recent_orders": [
                        {
                            "id": o.id,
                            "symbol": o.symbol,
                            "side": o.side,
                            "qty": float(o.qty),
                            "status": o.status,
                            "expected_price": float(o.expected_price),
                            "avg_fill_price": float(o.avg_fill_price)
                            if o.avg_fill_price is not None
                            else None,
                            "filled_qty": float(o.filled_qty),
                            "submitted_at": o.submitted_at.isoformat(),
                            "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                        }
                        for o in orders
                    ],
                    "recent_findings": [
                        {
                            "id": f.id,
                            "finding_type": f.finding_type,
                            "detail": f.detail,
                            "detected_at": f.detected_at.isoformat(),
                        }
                        for f in findings
                    ],
                }
            )

    return {"champions": champions, "total": len(champions)}

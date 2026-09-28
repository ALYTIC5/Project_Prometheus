"""Law 4 loss limits in paper trading (2026-09-28): MAX_DRAWDOWN_PCT and
MAX_DAILY_LOSS_PCT (test sentinels 15 / 4, tests/conftest.py) force a
strategy flat and are recorded once per day; a demoted strategy's open
position is flattened, never re-opened."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.paper.execution import breached_limit, check_risk_limits, decide_and_submit
from prometheus.strategy.spec import StrategySpec


def test_drawdown_is_checked_before_daily_loss() -> None:
    assert breached_limit(equity=840.0, peak=1000.0, start_of_day=850.0)[0] == "RISK_MAX_DRAWDOWN"
    breach = breached_limit(equity=955.0, peak=1000.0, start_of_day=1000.0)
    assert breach is not None and breach[0] == "RISK_DAILY_LOSS"
    assert breached_limit(equity=970.0, peak=1000.0, start_of_day=990.0) is None


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)
_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
_YESTERDAY = _NOW - timedelta(days=1)


async def _holding(session: AsyncSession, *, qty: float, price: float) -> tuple[str, str]:
    """A strategy that bought `qty` at `price` yesterday, marked at that
    price yesterday."""
    strategy_id = f"R{uuid.uuid4().hex[:12]}"
    symbol = f"R{uuid.uuid4().hex[:6]}/USDT"
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:i, 'MOMENTUM', '{}', 'PROMISING')"
        ),
        {"i": strategy_id},
    )
    await session.execute(
        text(
            "INSERT INTO paper_orders (id, strategy_id, client_order_id, symbol, side, qty, "
            "status, expected_price, expected_qty, filled_qty, avg_fill_price, event_time, "
            "submitted_at, filled_at) VALUES (:id, :s, :c, :sym, 'buy', :q, 'FILLED', :p, :q, "
            ":q, :p, :t, :t, :t)"
        ),
        {"id": f"PO-{uuid.uuid4().hex[:10]}", "s": strategy_id, "c": uuid.uuid4().hex,
         "sym": symbol, "q": qty, "p": price, "t": _YESTERDAY},
    )
    await session.execute(
        text("INSERT INTO paper_marks (symbol, close, bar_available_at) VALUES (:s, :c, :t)"),
        {"s": symbol, "c": price, "t": _YESTERDAY},
    )
    return strategy_id, symbol


async def _findings(session: AsyncSession, strategy_id: str) -> list[str]:
    rows = await session.execute(
        text("SELECT finding_type FROM paper_findings WHERE strategy_id = :s"), {"s": strategy_id}
    )
    return [r.finding_type for r in rows]


@_needs_db
@pytest.mark.db
async def test_a_daily_loss_breach_is_recorded_once_per_day(db_session: AsyncSession) -> None:
    # 1.1 units @ 100 = 11% of the EUR 1000 account (MAX_POSITION_PCT);
    # a fall to 60 loses 44 = 4.4% of the account today (> 4%).
    strategy_id, symbol = await _holding(db_session, qty=1.1, price=100.0)
    assert await check_risk_limits(
        db_session, strategy_id=strategy_id, symbol=symbol, price=99.0, now=_NOW
    ) is None
    for _ in range(2):
        assert await check_risk_limits(
            db_session, strategy_id=strategy_id, symbol=symbol, price=60.0, now=_NOW
        ) == "RISK_DAILY_LOSS"
    assert await _findings(db_session, strategy_id) == ["RISK_DAILY_LOSS"]
    # A new UTC day starts from the equity at the last mark (the worker marks
    # every tick): no breach without new losses.
    await db_session.execute(
        text("INSERT INTO paper_marks (symbol, close, bar_available_at) VALUES (:s, 60, :t)"),
        {"s": symbol, "t": _NOW},
    )
    assert await check_risk_limits(
        db_session, strategy_id=strategy_id, symbol=symbol, price=60.0,
        now=_NOW + timedelta(days=1),
    ) is None


class _RecordingBroker:
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []

    def submit_order(self, **kwargs: Any) -> dict[str, Any]:
        self.orders.append(kwargs)
        return {"id": f"X{len(self.orders)}"}


def _bars(symbol: str, close: float) -> pl.DataFrame:
    return pl.DataFrame(
        {"symbol": [symbol], "timeframe": ["1d"], "available_at": [_NOW], "open": [close],
         "high": [close], "low": [close], "close": [close], "volume": [1.0]}
    )


@_needs_db
@pytest.mark.db
async def test_force_flat_closes_the_position_and_never_opens_one(
    db_session: AsyncSession,
) -> None:
    strategy_id, symbol = await _holding(db_session, qty=1.1, price=100.0)
    spec = StrategySpec(
        family="MOMENTUM", symbol=symbol, timeframe="1d", fast_window=2, slow_window=3,
        expected_horizon=1,
    )
    broker = _RecordingBroker()
    await decide_and_submit(
        db_session, broker, strategy_id=strategy_id, spec=spec, bars=_bars(symbol, 100.0),
        force_flat=True, now=_NOW,
    )
    assert [(o["side"], round(o["qty"], 8)) for o in broker.orders] == [("sell", 1.1)]

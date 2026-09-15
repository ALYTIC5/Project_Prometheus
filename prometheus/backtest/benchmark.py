"""Law 8: the €1,000 buy-and-hold benchmark. One entry at the start of the
window, held flat, the SAME cost model (`backtest.costs.apply_cost`) any
strategy backtest uses -- Law 8's explicit requirement that the benchmark
never gets an unfair cost advantage.
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import apply_cost
from prometheus.data.schema import PointInTimeFrame

STARTING_CAPITAL = 1000.0

_UPSERT_BENCHMARK_EQUITY = text(
    """
    INSERT INTO benchmark_equity (date, equity)
    VALUES (:date, :equity)
    ON CONFLICT (date) DO UPDATE SET equity = EXCLUDED.equity
    """
)


def compute_benchmark_curve(
    pit: PointInTimeFrame, symbol: str, as_of_cutoff: datetime
) -> list[tuple[date, float]]:
    bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == symbol).sort("available_at")
    if bars.height == 0:
        return []
    equity_after_entry_cost = STARTING_CAPITAL - apply_cost(STARTING_CAPITAL)
    entry_price = bars["close"][0]
    return [
        (row["available_at"].date(), equity_after_entry_cost * (row["close"] / entry_price))
        for row in bars.iter_rows(named=True)
    ]


async def record_benchmark_curve(session: AsyncSession, curve: list[tuple[date, float]]) -> None:
    """Upsert, not append-only: benchmark_equity is a recomputed curve, not
    an event log (see core/db.py's BenchmarkEquity docstring) -- rerunning
    against the same window legitimately replaces a date's value rather
    than accumulating duplicate rows for it."""
    for day, equity in curve:
        await session.execute(_UPSERT_BENCHMARK_EQUITY, {"date": day, "equity": equity})

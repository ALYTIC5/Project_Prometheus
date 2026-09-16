"""Law 8: the €1,000 buy-and-hold benchmark. One entry at the start of the
window per symbol, held flat, the SAME cost model any strategy backtest
uses -- Law 8's explicit requirement that the benchmark never gets an
unfair cost advantage.

No Sharpe here, deliberately -- backtest/engine.py's own docstring already
establishes "no Sharpe/PBO/DSR anywhere, that's cpz-quant's job" as this
codebase's precedent (CLAUDE.md forbids hand-rolling it), and computing
one just for the benchmark would contradict that and need re-deriving once
cpz-quant lands in Prompt 5. max_drawdown_pct IS included -- it's
arithmetic (the same peak-to-trough walk run_backtest already does), not
a statistical estimator, so there's nothing to defer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.data.schema import PointInTimeFrame

STARTING_CAPITAL = 1000.0

_UPSERT_BENCHMARK_EQUITY = text(
    """
    INSERT INTO benchmark_equity (date, equity)
    VALUES (:date, :equity)
    ON CONFLICT (date) DO UPDATE SET equity = EXCLUDED.equity
    """
)


@dataclass(frozen=True)
class BenchmarkResult:
    equity_curve: list[tuple[date, float]]
    max_drawdown_pct: float
    final_value: float


def compute_benchmark_curve(
    pit: PointInTimeFrame,
    symbols: list[str],
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
) -> BenchmarkResult:
    """Law 8's own words: "equal-weight for multi-asset, 100% for single-
    asset" -- one formula, not two code paths. STARTING_CAPITAL splits
    equally across `symbols` (len==1 collapses to exactly today's single-
    asset behavior), `cost_model` charged once per symbol at entry, each
    symbol's contribution combined by an outer join on available_at with
    forward-fill -- handles symbols with different calendars or history
    lengths honestly rather than assuming they all share identical
    timestamps (true of this project's crypto universe today, not a safe
    assumption to bake into the math).
    """
    if not symbols:
        raise ValueError("compute_benchmark_curve requires at least one symbol")

    per_symbol_share = STARTING_CAPITAL / len(symbols)
    equity_after_entry_cost = per_symbol_share - cost_model(per_symbol_share)

    contributions: list[pl.DataFrame] = []
    for symbol in symbols:
        bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == symbol).sort("available_at")
        if bars.height == 0:
            continue
        entry_price = bars["close"][0]
        contributions.append(
            bars.select(
                "available_at",
                (equity_after_entry_cost * pl.col("close") / entry_price).alias(symbol),
            )
        )

    if not contributions:
        return BenchmarkResult(equity_curve=[], max_drawdown_pct=0.0, final_value=STARTING_CAPITAL)

    combined = contributions[0]
    for other in contributions[1:]:
        combined = combined.join(other, on="available_at", how="full", coalesce=True)
    combined = combined.sort("available_at")

    value_columns = [c for c in combined.columns if c != "available_at"]
    combined = combined.with_columns(
        [pl.col(c).forward_fill().fill_null(equity_after_entry_cost) for c in value_columns]
    ).with_columns(pl.sum_horizontal(value_columns).alias("equity"))

    curve = [(row["available_at"].date(), row["equity"]) for row in combined.iter_rows(named=True)]

    peak = curve[0][1]
    max_drawdown = 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    return BenchmarkResult(
        equity_curve=curve,
        max_drawdown_pct=max_drawdown * 100,
        final_value=curve[-1][1],
    )


async def record_benchmark_curve(session: AsyncSession, curve: list[tuple[date, float]]) -> None:
    """Upsert, not append-only: benchmark_equity is a recomputed curve, not
    an event log (see core/db.py's BenchmarkEquity docstring) -- rerunning
    against the same window legitimately replaces a date's value rather
    than accumulating duplicate rows for it."""
    for day, equity in curve:
        await session.execute(_UPSERT_BENCHMARK_EQUITY, {"date": day, "equity": equity})

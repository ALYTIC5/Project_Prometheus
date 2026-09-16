"""Law 8: the €1,000 buy-and-hold benchmark. One entry at the start of the
window per symbol, held flat, the SAME cost model any strategy backtest
uses -- Law 8's explicit requirement that the benchmark never gets an
unfair cost advantage.

max_drawdown_pct is arithmetic (the same peak-to-trough walk run_backtest
already does), not a statistical estimator, so it was never deferred.

VsBenchmark: excess_return, periods_underperforming_pct,
max_relative_drawdown are plain arithmetic over the two equity curves.
excess_sharpe (PROMPT 5) uses cpz-quant's compute_risk_analytics --
CLAUDE.md forbids hand-rolling Sharpe, and now that cpz-quant is actually
installed there is no reason left to defer it (docs/DEFERRED.md's old
entry for this is resolved). It is Optional: compute_risk_analytics
returns None below 30 aligned observations, and an honestly-absent excess
Sharpe on a short window beats a fabricated one. information_ratio/
tracking_error are STILL deliberately not included -- computing them
correctly needs the strategy curve (keyed per-bar, any timeframe) and the
benchmark curve (keyed per-date, coarser) aligned onto a shared period
grid, and cpz-quant doesn't do that alignment for us either; still
deferred to a dedicated pass rather than rushed (see docs/DEFERRED.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import polars as pl
from cpz_quant.certification.analytics import compute_risk_analytics
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


@dataclass(frozen=True)
class VsBenchmark:
    excess_return: float
    periods_underperforming_pct: float
    max_relative_drawdown: float
    # None below cpz-quant's own 30-observation floor -- honestly absent,
    # not a fabricated 0.0, on a strategy that hasn't run long enough yet.
    excess_sharpe: float | None


def compute_vs_benchmark(
    strategy_curve: tuple[tuple[str, float], ...],
    strategy_max_drawdown_pct: float,
    benchmark: BenchmarkResult,
) -> VsBenchmark:
    """Law 8's own comparison, as a structured object every BacktestResult
    carries (see engine.py's run_backtest) rather than something runner.py
    recomputes ad hoc. Aligned at DATE granularity -- the benchmark
    curve's own resolution -- so a strategy on a sub-daily timeframe has
    its last-observation-per-date compared against the benchmark's one
    point per date. Coarser than per-bar, but honest about what it's
    comparing rather than silently misaligned.
    """
    strategy_return_pct = (
        (strategy_curve[-1][1] - STARTING_CAPITAL) / STARTING_CAPITAL * 100
        if strategy_curve
        else 0.0
    )
    benchmark_return_pct = (benchmark.final_value - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    excess_return = strategy_return_pct - benchmark_return_pct

    strategy_by_date: dict[date, float] = {}
    for iso_ts, equity in strategy_curve:
        strategy_by_date[datetime.fromisoformat(iso_ts).date()] = equity
    benchmark_by_date = dict(benchmark.equity_curve)

    shared_dates = sorted(set(strategy_by_date) & set(benchmark_by_date))
    underperforming = 0
    compared = 0
    for i in range(1, len(shared_dates)):
        prev_date, curr_date = shared_dates[i - 1], shared_dates[i]
        prev_s, curr_s = strategy_by_date[prev_date], strategy_by_date[curr_date]
        prev_b, curr_b = benchmark_by_date[prev_date], benchmark_by_date[curr_date]
        if not prev_s or not prev_b:
            continue
        s_ret = (curr_s - prev_s) / prev_s
        b_ret = (curr_b - prev_b) / prev_b
        compared += 1
        if s_ret < b_ret:
            underperforming += 1
    periods_underperforming_pct = (underperforming / compared * 100) if compared else 0.0

    strategy_series = [strategy_by_date[d] for d in shared_dates]
    benchmark_series = [benchmark_by_date[d] for d in shared_dates]
    strategy_analytics = compute_risk_analytics(strategy_series)
    benchmark_analytics = compute_risk_analytics(benchmark_series)
    excess_sharpe = (
        strategy_analytics.sharpe - benchmark_analytics.sharpe
        if strategy_analytics
        and benchmark_analytics
        and strategy_analytics.sharpe is not None
        and benchmark_analytics.sharpe is not None
        else None
    )

    return VsBenchmark(
        excess_return=excess_return,
        periods_underperforming_pct=periods_underperforming_pct,
        max_relative_drawdown=strategy_max_drawdown_pct - benchmark.max_drawdown_pct,
        excess_sharpe=excess_sharpe,
    )


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

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

from prometheus.backtest.costs import CostModel
from prometheus.data.schema import PointInTimeFrame

STARTING_CAPITAL = 1000.0

_UPSERT_BENCHMARK_EQUITY = text(
    """
    INSERT INTO benchmark_equity (universe_key, date, equity)
    VALUES (:universe_key, :date, :equity)
    ON CONFLICT (universe_key, date) DO UPDATE SET equity = EXCLUDED.equity
    """
)


class BenchmarkMismatch(Exception):
    """Law 8: a benchmark whose universe or window differs from its
    strategy's. Deliberately NOT a ValueError -- runner.run_one treats
    ValueError from a backtest as insufficient data; this is a bug, never
    a data shortfall."""


def universe_key(symbols: list[str] | tuple[str, ...]) -> str:
    """Stable identity of a benchmark universe -- sorted, comma-joined --
    so benchmark_equity keeps one curve per universe instead of every
    spec overwriting the same date-keyed global row (docs/DEFERRED.md
    I5)."""
    return ",".join(sorted(symbols))


@dataclass(frozen=True)
class BenchmarkResult:
    equity_curve: list[tuple[date, float]]
    max_drawdown_pct: float
    final_value: float
    # Law 8 provenance, carried so a mismatch is checkable after the fact
    # (validation's BENCHMARK_MISMATCH gate, the law test) rather than
    # only by reading the call site.
    universe: tuple[str, ...] = ()
    window_start: date | None = None
    window_end: date | None = None


def assert_benchmark_matches(
    benchmark: BenchmarkResult,
    strategy_universe: tuple[str, ...],
    strategy_curve: tuple[tuple[str, float], ...],
) -> None:
    """Hard Law 8 check: same universe, same first and last date as the
    strategy's own realised equity curve. Raises BenchmarkMismatch --
    never silently compares against the wrong thing."""
    if tuple(sorted(benchmark.universe)) != tuple(sorted(strategy_universe)):
        raise BenchmarkMismatch(
            f"benchmark universe {benchmark.universe} != strategy universe {strategy_universe}"
        )
    if not strategy_curve or not benchmark.equity_curve:
        return
    strategy_start = datetime.fromisoformat(strategy_curve[0][0]).date()
    strategy_end = datetime.fromisoformat(strategy_curve[-1][0]).date()
    if (benchmark.window_start, benchmark.window_end) != (strategy_start, strategy_end):
        raise BenchmarkMismatch(
            f"benchmark window {benchmark.window_start}..{benchmark.window_end} != "
            f"strategy window {strategy_start}..{strategy_end}"
        )


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
    *,
    window_start: datetime | None,
    window_end: datetime,
    cost_model: CostModel,
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

    Every argument that defines WHAT is being compared is required, with
    no default (2026-09-24, Law 8): `symbols` is the strategy's own
    universe, `window_start`/`window_end` its own realised window (None
    start = explicitly "from the first available bar"), `cost_model` the
    same cost model the strategy used. The entry happens on the first bar
    at or after window_start -- i.e. the strategy's first tradable bar
    after its warm-up, not bar 1 of the loaded history, so a 200-day SMA
    isn't charged 200 days of buy-and-hold it could never have held.
    """
    if not symbols:
        raise ValueError("compute_benchmark_curve requires at least one symbol")

    per_symbol_share = STARTING_CAPITAL / len(symbols)
    equity_after_entry_cost = per_symbol_share - cost_model(per_symbol_share)

    contributions: list[pl.DataFrame] = []
    for symbol in symbols:
        bars = pit.as_of(window_end).filter(pl.col("symbol") == symbol).sort("available_at")
        if window_start is not None:
            bars = bars.filter(pl.col("available_at") >= window_start)
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
        return BenchmarkResult(
            equity_curve=[],
            max_drawdown_pct=0.0,
            final_value=STARTING_CAPITAL,
            universe=tuple(symbols),
        )

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
        universe=tuple(symbols),
        window_start=curve[0][0],
        window_end=curve[-1][0],
    )


async def record_benchmark_curve(session: AsyncSession, benchmark: BenchmarkResult) -> None:
    """Upsert, not append-only: benchmark_equity is a recomputed curve, not
    an event log (see core/db.py's BenchmarkEquity docstring) -- rerunning
    against the same window legitimately replaces a date's value rather
    than accumulating duplicate rows for it. Keyed per universe (migration
    0018): previously keyed on date alone, so every spec's curve
    overwrote every other universe's for the same date."""
    key = universe_key(benchmark.universe)
    for day, equity in benchmark.equity_curve:
        await session.execute(
            _UPSERT_BENCHMARK_EQUITY, {"universe_key": key, "date": day, "equity": equity}
        )

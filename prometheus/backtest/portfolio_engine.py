"""Portfolio-level backtest engine for RotationSpec -- cross-sectional
rotation strategies that hold a weighted basket of a UNIVERSE rather
than a single symbol's position. Returns the same BacktestResult shape
run_backtest() does (backtest/engine.py) so every downstream consumer
(PBO, Deflated Sharpe, clustering, dashboard) needs zero changes.

Net vs gross accounting is tracked as two fully parallel dollar-ledgers
(cash + per-symbol legs), not "gross = net + total_costs" -- costs
compound with future returns, so adding the raw cost total back onto the
net curve would understate gross return on any window with more than one
rebalance. This mirrors backtest/engine.py's _run_accounting, which
also keeps a genuinely separate gross_equity accumulator rather than a
post-hoc adjustment.

See docs/superpowers/specs/2026-09-21-cross-sectional-rotation-design.md.
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl

from prometheus.backtest.benchmark import (
    BenchmarkResult,
    compute_benchmark_curve,
    compute_vs_benchmark,
)
from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, BacktestResult
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import ROTATION_FAMILY_EQUAL_WEIGHT, RotationSpec

Membership = dict[str, tuple[date, date | None]]


def weights_for_equal_weight(eligible_symbols: list[str]) -> dict[str, float]:
    """#59's own definition: 1/N across whatever is eligible right now,
    always. Empty input -> empty weights (100% cash), not a
    ZeroDivisionError."""
    if not eligible_symbols:
        return {}
    share = 1.0 / len(eligible_symbols)
    return {symbol: share for symbol in eligible_symbols}


def _eligible_symbols(universe: tuple[str, ...], membership: Membership, as_of: date) -> list[str]:
    """Law 2: reconstruct membership as of `as_of`, not today's listing.
    A symbol absent from `membership` entirely is never eligible."""
    eligible: list[str] = []
    for symbol in universe:
        window = membership.get(symbol)
        if window is None:
            continue
        listed_at, delisted_at = window
        if listed_at <= as_of and (delisted_at is None or as_of < delisted_at):
            eligible.append(symbol)
    return eligible


def _weights_for(
    spec: RotationSpec,
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of_idx: int,
) -> dict[str, float]:
    """Single dispatch point every family's weight function is called
    through, keyed on spec.family. Tasks 4-6 add branches here for the
    remaining five ROTATION_FAMILIES; each of those weight functions
    takes (eligible_symbols, price_history_by_symbol, lookback_days,
    top_n) -- `bars_by_symbol`/`as_of_idx` are threaded through now so
    this task doesn't need to change signature later."""
    if spec.family == ROTATION_FAMILY_EQUAL_WEIGHT:
        return weights_for_equal_weight(eligible)
    raise ValueError(f"no weight function wired for family {spec.family!r}")  # Tasks 4-6 extend this


def _rebalance_indices(num_dates: int, first_idx: int, rebalance_frequency_days: int) -> set[int]:
    """Indices into the sorted, deduplicated union-of-dates list where a
    rebalance happens: `first_idx` (the first date with enough warm-up
    history), then every `rebalance_frequency_days` trading days after
    it. If `first_idx >= num_dates` (not enough history anywhere in this
    window) this is correctly empty -- the portfolio simply never
    invests rather than forcing a rebalance on the last bar regardless
    of whether the warm-up requirement was actually met."""
    return set(range(first_idx, num_dates, rebalance_frequency_days))


def _drift(
    dollar_alloc: dict[str, float],
    close_by_symbol_date: dict[str, dict[date, float]],
    prev_date: date,
    curr_date: date,
) -> None:
    """Each held symbol's dollar allocation drifts with its own daily
    return between rebalances -- no daily rebalancing drag. Mutates
    `dollar_alloc` in place. A symbol missing a close on either date
    (no price data) is left un-drifted rather than raising -- it simply
    holds its last known dollar value, the same way cash would."""
    for symbol in list(dollar_alloc):
        prev_close = close_by_symbol_date.get(symbol, {}).get(prev_date)
        curr_close = close_by_symbol_date.get(symbol, {}).get(curr_date)
        if prev_close and curr_close:
            dollar_alloc[symbol] *= curr_close / prev_close


def run_portfolio_backtest(
    pit: PointInTimeFrame,
    spec: RotationSpec,
    membership: Membership,
    as_of_cutoff: datetime,
    *,
    cost_model: CostModel = apply_cost,
    benchmark_result: BenchmarkResult | None = None,
) -> BacktestResult:
    frame = pit.as_of(as_of_cutoff).filter(pl.col("symbol").is_in(list(spec.universe)))
    all_dates: list[date] = sorted({row["available_at"].date() for row in frame.iter_rows(named=True)})
    if not all_dates:
        raise ValueError(f"no bars for universe {spec.universe} as of {as_of_cutoff}")

    bars_by_symbol: dict[str, pl.DataFrame] = {
        symbol: frame.filter(pl.col("symbol") == symbol).sort("available_at")
        for symbol in spec.universe
    }
    close_by_symbol_date: dict[str, dict[date, float]] = {
        symbol: {row["available_at"].date(): row["close"] for row in bars.iter_rows(named=True)}
        for symbol, bars in bars_by_symbol.items()
    }

    warmup = spec.lookback_days or 0
    first_idx = warmup
    rebalance_indices = _rebalance_indices(len(all_dates), first_idx, spec.rebalance_frequency_days)

    # Net (cost-bearing) ledger.
    cash = STARTING_CAPITAL
    dollar_alloc: dict[str, float] = {}
    # Gross (no-cost) ledger -- a fully parallel accumulator driven by the
    # SAME target-weight schedule, never charged a cost. Kept separate
    # (not "net + total_costs") because costs compound with subsequent
    # returns across multiple rebalances; only a true parallel path is
    # exact.
    gross_cash = STARTING_CAPITAL
    gross_dollar_alloc: dict[str, float] = {}

    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    turnover = 0.0
    total_costs = 0.0
    curve: list[tuple[str, float]] = []

    for idx, as_of in enumerate(all_dates):
        if idx >= first_idx:
            if idx > first_idx:
                prev_date = all_dates[idx - 1]
                _drift(dollar_alloc, close_by_symbol_date, prev_date, as_of)
                _drift(gross_dollar_alloc, close_by_symbol_date, prev_date, as_of)

            if idx in rebalance_indices:
                eligible = _eligible_symbols(spec.universe, membership, as_of)
                target_weights = _weights_for(spec, eligible, bars_by_symbol, idx)

                # Net: size against pre-trade equity, charge cost on the
                # notional actually traded, then realize the post-cost
                # equity into the new target weights.
                pre_trade_equity = cash + sum(dollar_alloc.values())
                intended_alloc = {s: w * pre_trade_equity for s, w in target_weights.items()}
                traded = sum(
                    abs(intended_alloc.get(s, 0.0) - dollar_alloc.get(s, 0.0))
                    for s in set(intended_alloc) | set(dollar_alloc)
                )
                cost = cost_model(traded) if traded else 0.0
                total_costs += cost
                if pre_trade_equity:
                    turnover += traded / pre_trade_equity
                post_cost_equity = pre_trade_equity - cost
                dollar_alloc = {s: w * post_cost_equity for s, w in target_weights.items()}
                cash = post_cost_equity - sum(dollar_alloc.values())

                # Gross: identical target schedule, no cost ever charged.
                gross_pre_trade_equity = gross_cash + sum(gross_dollar_alloc.values())
                gross_dollar_alloc = {
                    s: w * gross_pre_trade_equity for s, w in target_weights.items()
                }
                gross_cash = gross_pre_trade_equity - sum(gross_dollar_alloc.values())

        equity = cash + sum(dollar_alloc.values())
        gross_equity = gross_cash + sum(gross_dollar_alloc.values())
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        curve.append((datetime.combine(as_of, datetime.min.time()).isoformat(), equity))

    equity_curve: tuple[tuple[str, float], ...] = tuple(curve)
    total_return_pct = (equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    gross_return_pct = (gross_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    if benchmark_result is None:
        benchmark_result = compute_benchmark_curve(
            pit, list(spec.universe), as_of_cutoff, cost_model=cost_model
        )
    vs_benchmark = compute_vs_benchmark(equity_curve, max_drawdown * 100, benchmark_result)

    return BacktestResult(
        equity_curve=equity_curve,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown * 100,
        turnover=turnover,
        gross_return_pct=gross_return_pct,
        total_costs=total_costs,
        vs_benchmark=vs_benchmark,
    )

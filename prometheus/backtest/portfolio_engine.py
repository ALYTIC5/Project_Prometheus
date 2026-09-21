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
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

Membership = dict[str, tuple[date, date | None]]


def weights_for_equal_weight(eligible_symbols: list[str]) -> dict[str, float]:
    """#59's own definition: 1/N across whatever is eligible right now,
    always. Empty input -> empty weights (100% cash), not a
    ZeroDivisionError."""
    if not eligible_symbols:
        return {}
    share = 1.0 / len(eligible_symbols)
    return {symbol: share for symbol in eligible_symbols}


def trailing_return(bars: pl.DataFrame, as_of: date, lookback_days: int) -> float | None:
    """Close-to-close return from `lookback_days` bars before `as_of` to
    `as_of` itself, using only rows with available_at <= as_of (Law 1 --
    a ranking decision at `as_of` never reads a bar not yet available on
    that date). None when there aren't enough prior bars -- an
    honestly-excluded symbol for this ranking cycle, not a fabricated
    0.0 that would make it look like a flat, tied-for-worst performer."""
    rows = bars.filter(pl.col("available_at") <= datetime.combine(as_of, datetime.min.time()))
    if rows.height <= lookback_days:
        return None
    closes: list[float] = rows["close"].to_list()
    start_close = closes[-(lookback_days + 1)]
    end_close = closes[-1]
    if start_close == 0:
        return None
    return (end_close - start_close) / start_close


def weights_for_top_n_momentum(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    lookback_days: int,
    top_n: int,
    *,
    worst: bool = False,
) -> dict[str, float]:
    """Shared ranking primitive for #49 (best-N), #51 (best-3, top_n
    fixed by the caller's spec), and #52 (worst-N, worst=True) -- #52 is
    literally #49's own mechanism with the sort direction flipped, per
    the design doc's "inverse of #49" framing, not a separate algorithm.
    Symbols with no `trailing_return` (insufficient history) are excluded
    from ranking entirely. Fewer scored symbols than `top_n` -> every
    scored symbol is used, equal-weighted among just those. No scored
    symbols at all -> empty weights (100% cash), same convention as
    `weights_for_equal_weight`."""
    scored: list[tuple[str, float]] = []
    for symbol in eligible:
        ret = trailing_return(bars_by_symbol[symbol], as_of, lookback_days)
        if ret is not None:
            scored.append((symbol, ret))
    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[1], reverse=not worst)
    chosen = scored[: min(top_n, len(scored))]
    share = 1.0 / len(chosen)
    return {symbol: share for symbol, _ in chosen}


def weights_for_dual_momentum_gem(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Antonacci's own published GEM rule (#50): among the equity legs
    (every symbol in `eligible` except the final, defensive one -- this
    family's own universe convention, `universe = (equity_leg_1, ...,
    defensive_leg)`, stated in docs/strategies/dual_momentum_gem.md),
    hold the strongest equity leg only if ITS OWN trailing return is
    positive (absolute momentum); otherwise hold the defensive leg.
    Empty (100% cash) only when there isn't enough history to judge at
    all -- an honestly-skipped rebalance, not a fabricated decision.

    Callers relying on `eligible[-1]` being the defensive leg must first
    confirm the defensive symbol is actually present in `eligible` --
    `_weights_for`'s dispatch does this by checking `spec.universe[-1]`
    membership before calling this function, since `_eligible_symbols`
    preserves universe order but can drop the defensive leg entirely if
    it fails point-in-time membership on `as_of`, which would otherwise
    silently point `eligible[-1]` at the wrong (equity) symbol."""
    if len(eligible) < 2:
        return {}
    *equity_legs, defensive_leg = eligible
    equity_returns = [
        (symbol, trailing_return(bars_by_symbol[symbol], as_of, lookback_days))
        for symbol in equity_legs
    ]
    scored_equity_returns = [(s, r) for s, r in equity_returns if r is not None]
    defensive_return = trailing_return(bars_by_symbol[defensive_leg], as_of, lookback_days)
    if not scored_equity_returns or defensive_return is None:
        return {}
    best_symbol, best_return = max(scored_equity_returns, key=lambda pair: pair[1])
    if best_return > 0:
        return {best_symbol: 1.0}
    return {defensive_leg: 1.0}


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
    as_of: date,
) -> dict[str, float]:
    """Single dispatch point every family's weight function is called
    through, keyed on spec.family. Tasks 5-6 add branches here for the
    remaining two ROTATION_FAMILIES. `as_of` (not the loop's integer
    index) is threaded through so ranking families can compute
    `trailing_return` against real dates without reaching back into the
    caller's loop state."""
    if spec.family == ROTATION_FAMILY_EQUAL_WEIGHT:
        return weights_for_equal_weight(eligible)
    if spec.family in (ROTATION_FAMILY_SECTOR_MOMENTUM, ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3):
        lookback_days = spec.lookback_days
        top_n = spec.top_n
        if lookback_days is None or top_n is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days and top_n")
        return weights_for_top_n_momentum(eligible, bars_by_symbol, as_of, lookback_days, top_n)
    if spec.family == ROTATION_FAMILY_SECTOR_MEAN_REVERSION:
        lookback_days = spec.lookback_days
        top_n = spec.top_n
        if lookback_days is None or top_n is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days and top_n")
        return weights_for_top_n_momentum(
            eligible, bars_by_symbol, as_of, lookback_days, top_n, worst=True,
        )
    if spec.family == ROTATION_FAMILY_DUAL_MOMENTUM_GEM:
        lookback_days = spec.lookback_days
        if lookback_days is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days")
        # spec.universe[-1] is the defensive leg by this family's own
        # convention (docs/strategies/dual_momentum_gem.md). `eligible`
        # preserves universe order (see _eligible_symbols) but can drop
        # the defensive leg entirely if it fails point-in-time
        # membership -- checking its membership explicitly here, rather
        # than trusting `eligible[-1]`, is what keeps that guarantee
        # honest: once confirmed present, universe order forces it to
        # also be the last element of `eligible`, since nothing follows
        # it in `spec.universe`.
        if spec.universe[-1] not in eligible:
            return {}
        return weights_for_dual_momentum_gem(eligible, bars_by_symbol, as_of, lookback_days)
    raise ValueError(f"no weight function wired for family {spec.family!r}")  # Task 6 extends this


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
                target_weights = _weights_for(spec, eligible, bars_by_symbol, as_of)

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

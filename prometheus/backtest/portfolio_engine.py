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

from datetime import UTC, date, datetime

import polars as pl

import numpy as np

from prometheus.backtest.benchmark import (
    BenchmarkResult,
    compute_benchmark_curve,
    compute_vs_benchmark,
)
from prometheus.backtest.costs import CostModel, apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, BacktestResult
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM,
    ROTATION_FAMILY_DAA,
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_MIN_VARIANCE,
    ROTATION_FAMILY_PAA,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_RESIDUAL_MOMENTUM,
    ROTATION_FAMILY_RISK_PARITY,
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
    0.0 that would make it look like a flat, tied-for-worst performer.

    I2 (final-review fix wave): the cutoff is the END of `as_of`, not
    midnight. Production ETF bars carry `available_at = event_time +
    5 minutes` (data/ingest_etf.py's _INGESTION_LAG), so a midnight
    cutoff excluded the bar dated `as_of` from its OWN decision --
    every ranking family saw one fewer bar than `lookback_days`
    required and returned None for every symbol on the first
    rebalance. Still Law-1-safe: `all_dates` itself is derived from
    real `available_at` timestamps already filtered by
    `pit.as_of(as_of_cutoff)`, and this cutoff still admits no bar
    whose `available_at` falls on a date AFTER `as_of` -- only bars
    dated `as_of` itself, whatever time of day their availability
    lag lands on."""
    rows = bars.filter(
        pl.col("available_at") <= datetime.combine(as_of, datetime.max.time(), UTC)
    )
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


def weights_for_gtaa_sma(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Faber's own published GTAA rule (#53): each of `len(eligible)`
    assets independently gets a FIXED 1/N slice of capital if its own
    close is above its own trailing `lookback_days`-bar SMA, else that
    slice is simply absent (cash) -- never redistributed to the assets
    still in, unlike a ranking family's top-N reallocation. Each
    symbol's in/out decision reads only that symbol's own bars, so
    there is no cross-asset comparison. A symbol with fewer than
    `lookback_days` available bars is skipped (its slice sits in cash)
    -- an honestly-unjudged asset, not a fabricated in/out call. Empty
    `eligible` -> empty weights (100% cash), same convention as
    `weights_for_equal_weight`.

    The `available_at` cutoff is the END of `as_of`, for exactly the
    reason `trailing_return`'s own docstring gives (I2)."""
    if not eligible:
        return {}
    share = 1.0 / len(eligible)
    weights: dict[str, float] = {}
    for symbol in eligible:
        bars = bars_by_symbol[symbol]
        rows = bars.filter(
        pl.col("available_at") <= datetime.combine(as_of, datetime.max.time(), UTC)
    )
        if rows.height < lookback_days:
            continue
        closes: list[float] = rows["close"].to_list()
        sma = sum(closes[-lookback_days:]) / lookback_days
        if closes[-1] > sma:
            weights[symbol] = share
    return weights


def _closes_as_of(bars: pl.DataFrame, as_of: date) -> list[float]:
    """Every close with `available_at` on or before the END of `as_of`
    (I2's own cutoff convention) -- the shared building block every
    function below uses so the cutoff logic lives in exactly one place."""
    rows = bars.filter(
        pl.col("available_at") <= datetime.combine(as_of, datetime.max.time(), UTC)
    )
    return rows["close"].to_list()


def _momentum_13612w(bars: pl.DataFrame, as_of: date) -> float | None:
    """Keller & Keuning's own "13612W" momentum score (used by both DAA
    and, informally, its sibling constructions): a weighted average of
    1/3/6/12-month trailing returns (21/63/126/252 trading days), weights
    12/4/2/1 -- overweights the most recent month while still respecting
    the full year. None when there isn't a full 252-bar history to judge
    on, an honestly-excluded symbol for this cycle."""
    closes = _closes_as_of(bars, as_of)
    if len(closes) <= 252:
        return None
    end_close = closes[-1]

    def _ret(lookback: int) -> float | None:
        start_close = closes[-(lookback + 1)]
        if start_close == 0:
            return None
        return (end_close - start_close) / start_close

    r1, r3, r6, r12 = _ret(21), _ret(63), _ret(126), _ret(252)
    if r1 is None or r3 is None or r6 is None or r12 is None:
        return None
    return (12.0 * r1 + 4.0 * r3 + 2.0 * r6 + 1.0 * r12) / 19.0


def weights_for_daa(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    universe: tuple[str, ...],
    top_n: int,
) -> dict[str, float]:
    """Keller & Keuning's own Defensive Asset Allocation (#54, "Breadth
    Momentum and the Canary Universe: Defensive Asset Allocation",
    2016), a documented SIMPLIFICATION of the published construction:
    `universe` = (canary_1, canary_2, offensive_1, ..., offensive_N,
    defensive) -- a single defensive leg rather than the paper's own
    3-asset protective pool (this project's ingested universe has no
    ultra-short-duration Treasury ETF equivalent to the paper's own
    SHY choice). The mechanism itself is faithful: T of the 2 canary
    assets showing a negative 13612W score sends T/(scored canary count)
    of the portfolio to cash/defensive, and the remainder is split
    equally among the top `top_n` positive-momentum offensive assets.
    A canary asset with no scorable history is excluded from BOTH the
    numerator and denominator (an honest adjustment when the paper's own
    2-asset canary can't be fully judged), never silently treated as
    "good"."""
    canary_symbols = universe[:2]
    defensive_symbol = universe[-1]
    offensive_symbols = universe[2:-1]

    canary_scores = [
        score
        for symbol in canary_symbols
        if symbol in eligible
        for score in (_momentum_13612w(bars_by_symbol[symbol], as_of),)
        if score is not None
    ]
    if not canary_scores:
        return {}
    bad = sum(1 for score in canary_scores if score < 0)
    cash_fraction = bad / len(canary_scores)

    offensive_scored = [
        (symbol, score)
        for symbol in offensive_symbols
        if symbol in eligible
        for score in (_momentum_13612w(bars_by_symbol[symbol], as_of),)
        if score is not None and score > 0
    ]

    weights: dict[str, float] = {}
    invested_fraction = 1.0 - cash_fraction
    if offensive_scored and invested_fraction > 0:
        offensive_scored.sort(key=lambda pair: pair[1], reverse=True)
        chosen = offensive_scored[: min(top_n, len(offensive_scored))]
        share = invested_fraction / len(chosen)
        for symbol, _ in chosen:
            weights[symbol] = share
    else:
        cash_fraction = 1.0

    if cash_fraction > 0 and defensive_symbol in eligible:
        weights[defensive_symbol] = weights.get(defensive_symbol, 0.0) + cash_fraction
    return weights


def weights_for_paa(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    universe: tuple[str, ...],
    lookback_days: int,
    top_n: int,
    protection_factor: float,
) -> dict[str, float]:
    """Keller & Keuning's own Protective Asset Allocation (#55,
    "Protective Asset Allocation (PAA): A Simple Momentum-Based
    Alternative for Term Deposits", 2017): `universe` = (offensive_1,
    ..., offensive_N, defensive), same trailing-leg convention as
    DUAL_MOMENTUM_GEM. Each offensive asset's momentum score is its
    close's distance from its own `lookback_days`-bar SMA (the paper's
    own construction, same trend-vs-SMA test GTAA_SMA already uses, just
    continuous rather than binary). `n` of the N SCORABLE offensive
    assets with a positive score determines the bond fraction:
    `min(1, (N-n)*protection_factor/N)` -- the paper's own explicitly-
    varied "a" (protection_factor) parameter. The remaining equity
    fraction is split equally among the top `top_n` POSITIVE-score
    assets; if none score positive, the whole portfolio goes defensive
    (same honest fallback DAA above uses)."""
    offensive_symbols = universe[:-1]
    defensive_symbol = universe[-1]

    scored: list[tuple[str, float]] = []
    for symbol in offensive_symbols:
        if symbol not in eligible:
            continue
        closes = _closes_as_of(bars_by_symbol[symbol], as_of)
        if len(closes) < lookback_days:
            continue
        sma = sum(closes[-lookback_days:]) / lookback_days
        if sma == 0:
            continue
        scored.append((symbol, closes[-1] / sma - 1.0))

    if not scored:
        if defensive_symbol in eligible:
            return {defensive_symbol: 1.0}
        return {}

    n_scored = len(scored)
    n_positive = sum(1 for _, score in scored if score > 0)
    bond_fraction = min(1.0, (n_scored - n_positive) * protection_factor / n_scored)

    positive_scored = sorted(
        [(s, sc) for s, sc in scored if sc > 0], key=lambda pair: pair[1], reverse=True
    )
    weights: dict[str, float] = {}
    equity_fraction = 1.0 - bond_fraction
    if positive_scored and equity_fraction > 0:
        chosen = positive_scored[: min(top_n, len(positive_scored))]
        share = equity_fraction / len(chosen)
        for symbol, _ in chosen:
            weights[symbol] = share
    else:
        bond_fraction = 1.0

    if bond_fraction > 0 and defensive_symbol in eligible:
        weights[defensive_symbol] = weights.get(defensive_symbol, 0.0) + bond_fraction
    return weights


def weights_for_accelerating_dual_momentum(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date,
) -> dict[str, float]:
    """Ludlow & Hanly's own Accelerating Dual Momentum ("Using Combined
    Momentum Signals to Generate Better Risk Adjusted Returns", 2018):
    the same absolute/relative momentum switch DUAL_MOMENTUM_GEM uses
    (hold the strongest equity leg only if its own momentum is positive,
    else the defensive leg), but scored on the AVERAGE of 1/3/6-month
    trailing returns rather than a single 12-month return -- reacts
    faster to regime changes, the paper's own stated motivation.
    `eligible` = (equity_leg_1, ..., equity_leg_N, defensive_leg), same
    convention as DUAL_MOMENTUM_GEM; the dispatcher confirms the
    defensive leg's membership before calling this, exactly as it does
    for DUAL_MOMENTUM_GEM."""
    if len(eligible) < 2:
        return {}
    *equity_legs, defensive_leg = eligible

    def _score(symbol: str) -> float | None:
        closes = _closes_as_of(bars_by_symbol[symbol], as_of)
        if len(closes) <= 126:
            return None
        end_close = closes[-1]
        rets = []
        for lookback in (21, 63, 126):
            start_close = closes[-(lookback + 1)]
            if start_close == 0:
                return None
            rets.append((end_close - start_close) / start_close)
        return sum(rets) / len(rets)

    scored = [(s, sc) for s in equity_legs for sc in (_score(s),) if sc is not None]
    if not scored:
        return {}
    best_symbol, best_score = max(scored, key=lambda pair: pair[1])
    if best_score > 0:
        return {best_symbol: 1.0}
    return {defensive_leg: 1.0}


def weights_for_risk_parity(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Naive ("inverse volatility") risk parity (#57) -- weight
    inversely proportional to each asset's own rolling volatility
    (daily-return std over `lookback_days`), so no single volatile
    asset can dominate the portfolio's own risk contribution. A
    documented SIMPLIFICATION of full covariance-based risk parity (Qian
    2005, "Risk Parity Portfolios") -- the naive inverse-vol form is the
    standard practitioner shorthand for it and ignores cross-asset
    correlation entirely, unlike MINIMUM_VARIANCE below which does use
    the full covariance matrix. Symbols with fewer than
    `lookback_days`+1 closes, or zero volatility, are excluded."""
    inv_vols: dict[str, float] = {}
    for symbol in eligible:
        closes = _closes_as_of(bars_by_symbol[symbol], as_of)
        if len(closes) <= lookback_days:
            continue
        window = closes[-(lookback_days + 1):]
        returns = [
            (window[i] - window[i - 1]) / window[i - 1]
            for i in range(1, len(window))
            if window[i - 1] != 0
        ]
        if len(returns) < 2:
            continue
        vol = float(np.std(returns, ddof=1))
        if vol > 0:
            inv_vols[symbol] = 1.0 / vol
    total = sum(inv_vols.values())
    if not total:
        return {}
    return {symbol: value / total for symbol, value in inv_vols.items()}


def weights_for_min_variance(
    eligible: list[str], bars_by_symbol: dict[str, pl.DataFrame], as_of: date, lookback_days: int,
) -> dict[str, float]:
    """Minimum-variance portfolio (#58): the unconstrained analytic
    solution w = (Sigma^-1 1) / (1^T Sigma^-1 1) using the sample
    covariance matrix of daily returns over `lookback_days`, computed
    only over symbols with a FULLY ALIGNED return history (a genuine
    covariance needs matched dates across assets, unlike the other
    families here which score each symbol independently). A documented
    SIMPLIFICATION of the true long-only-constrained quadratic program
    (which has no closed form and would need an iterative solver, a new
    dependency this project's cost-discipline rule requires justifying):
    the unconstrained solution can assign negative weights, which are
    clipped to zero and the remainder renormalized -- a standard
    practitioner approximation to the constrained optimum, not the exact
    one. Falls back to `weights_for_risk_parity` (documented, not
    silent) whenever fewer than 2 symbols have aligned history or the
    covariance matrix is singular."""
    aligned: dict[str, list[float]] = {}
    common_dates: set[date] | None = None
    for symbol in eligible:
        bars = bars_by_symbol[symbol]
        rows = bars.filter(
            pl.col("available_at") <= datetime.combine(as_of, datetime.max.time(), UTC)
        )
        by_date = {row["available_at"].date(): row["close"] for row in rows.iter_rows(named=True)}
        if len(by_date) <= lookback_days:
            continue
        aligned[symbol] = list(by_date.values())
        dates = set(by_date.keys())
        common_dates = dates if common_dates is None else common_dates & dates

    usable = [s for s in aligned if len(aligned[s]) > lookback_days]
    if len(usable) < 2 or not common_dates or len(common_dates) <= lookback_days:
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)

    sorted_dates = sorted(common_dates)[-(lookback_days + 1):]
    return_matrix = []
    for symbol in usable:
        bars = bars_by_symbol[symbol]
        rows = bars.filter(
            pl.col("available_at") <= datetime.combine(as_of, datetime.max.time(), UTC)
        )
        by_date = {row["available_at"].date(): row["close"] for row in rows.iter_rows(named=True)}
        closes = [by_date[d] for d in sorted_dates]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        return_matrix.append(returns)

    lengths = {len(r) for r in return_matrix}
    if len(lengths) != 1 or lengths == {0}:
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)

    cov = np.cov(np.array(return_matrix))
    try:
        inv_cov = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)

    ones = np.ones(len(usable))
    raw_weights = inv_cov @ ones
    denom = ones @ raw_weights
    if denom == 0:
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)
    raw_weights = raw_weights / denom
    clipped = np.clip(raw_weights, 0.0, None)
    total = clipped.sum()
    if total <= 0:
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)
    return {symbol: float(w) / float(total) for symbol, w in zip(usable, clipped) if w > 0}


def weights_for_fifty_two_week_high(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    lookback_days: int,
    top_n: int,
) -> dict[str, float]:
    """George & Hwang's own "52-week high" momentum (#60, "The 52-Week
    High and Momentum Investing", *Journal of Finance*, 2004): rank
    assets by proximity to their own trailing `lookback_days`-bar high
    (close / rolling_high, closer to 1.0 = closer to the high), long the
    top `top_n`. A momentum signal via ANCHORING to a salient reference
    price rather than raw trailing return -- the paper's own stated
    distinct mechanism from ordinary momentum."""
    scored: list[tuple[str, float]] = []
    for symbol in eligible:
        closes = _closes_as_of(bars_by_symbol[symbol], as_of)
        if len(closes) <= lookback_days:
            continue
        window_high = max(closes[-lookback_days:])
        if window_high == 0:
            continue
        scored.append((symbol, closes[-1] / window_high))
    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[1], reverse=True)
    chosen = scored[: min(top_n, len(scored))]
    share = 1.0 / len(chosen)
    return {symbol: share for symbol, _ in chosen}


def weights_for_residual_momentum(
    eligible: list[str],
    bars_by_symbol: dict[str, pl.DataFrame],
    as_of: date,
    universe: tuple[str, ...],
    lookback_days: int,
    top_n: int,
) -> dict[str, float]:
    """Blitz, Huij & Martens' own Residual Momentum (#62, "Residual
    Momentum", *Journal of Empirical Finance*, 2011): rank assets by
    their CUMULATIVE RESIDUAL return over `lookback_days` -- the daily
    return left over after subtracting away each asset's own
    market-beta-scaled share of the benchmark's daily return -- rather
    than raw momentum, isolating the idiosyncratic component the paper's
    own finding says is the more persistent signal. `universe[0]` is the
    market-benchmark symbol (never itself held); the rest is the ranked
    pool. Beta is estimated via the same closed-form OLS slope
    (cov(asset, benchmark) / var(benchmark)) LINREG_SLOPE already uses,
    over the same `lookback_days` window."""
    if not universe or universe[0] not in eligible:
        return {}
    benchmark_symbol = universe[0]
    pool = [s for s in universe[1:] if s in eligible]

    bench_closes = _closes_as_of(bars_by_symbol[benchmark_symbol], as_of)
    if len(bench_closes) <= lookback_days:
        return {}
    bench_window = bench_closes[-(lookback_days + 1):]
    bench_returns = [
        (bench_window[i] - bench_window[i - 1]) / bench_window[i - 1]
        for i in range(1, len(bench_window))
        if bench_window[i - 1] != 0
    ]
    if len(bench_returns) < 2:
        return {}
    bench_mean = sum(bench_returns) / len(bench_returns)
    bench_var = sum((r - bench_mean) ** 2 for r in bench_returns)
    if bench_var == 0:
        return {}

    scored: list[tuple[str, float]] = []
    for symbol in pool:
        closes = _closes_as_of(bars_by_symbol[symbol], as_of)
        if len(closes) <= lookback_days:
            continue
        window = closes[-(lookback_days + 1):]
        asset_returns = [
            (window[i] - window[i - 1]) / window[i - 1]
            for i in range(1, len(window))
            if window[i - 1] != 0
        ]
        if len(asset_returns) != len(bench_returns):
            continue
        asset_mean = sum(asset_returns) / len(asset_returns)
        cov = sum(
            (a - asset_mean) * (b - bench_mean) for a, b in zip(asset_returns, bench_returns)
        )
        beta = cov / bench_var
        residual_returns = [a - beta * b for a, b in zip(asset_returns, bench_returns)]
        residual_cumulative = sum(residual_returns)
        scored.append((symbol, residual_cumulative))

    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[1], reverse=True)
    chosen = scored[: min(top_n, len(scored))]
    share = 1.0 / len(chosen)
    return {symbol: share for symbol, _ in chosen}


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
    through, keyed on spec.family. All 6 ROTATION_FAMILIES are wired
    here. `as_of` (not the loop's integer index) is threaded through so
    ranking families can compute `trailing_return` against real dates
    without reaching back into the caller's loop state."""
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
    if spec.family == ROTATION_FAMILY_GTAA_SMA:
        lookback_days = spec.lookback_days
        if lookback_days is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days")
        return weights_for_gtaa_sma(eligible, bars_by_symbol, as_of, lookback_days)
    if spec.family == ROTATION_FAMILY_DAA:
        top_n = spec.top_n
        if top_n is None:
            raise ValueError(f"family {spec.family!r} requires top_n")
        return weights_for_daa(eligible, bars_by_symbol, as_of, spec.universe, top_n)
    if spec.family == ROTATION_FAMILY_PAA:
        lookback_days = spec.lookback_days
        top_n = spec.top_n
        protection_factor = spec.protection_factor
        if lookback_days is None or top_n is None or protection_factor is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days, top_n, protection_factor")
        return weights_for_paa(
            eligible, bars_by_symbol, as_of, spec.universe, lookback_days, top_n, protection_factor
        )
    if spec.family == ROTATION_FAMILY_ACCELERATING_DUAL_MOMENTUM:
        # Same defensive-leg membership check DUAL_MOMENTUM_GEM's own
        # dispatch makes, for the same reason (see its comment above).
        if spec.universe[-1] not in eligible:
            return {}
        return weights_for_accelerating_dual_momentum(eligible, bars_by_symbol, as_of)
    if spec.family == ROTATION_FAMILY_RISK_PARITY:
        lookback_days = spec.lookback_days
        if lookback_days is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days")
        return weights_for_risk_parity(eligible, bars_by_symbol, as_of, lookback_days)
    if spec.family == ROTATION_FAMILY_MIN_VARIANCE:
        lookback_days = spec.lookback_days
        if lookback_days is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days")
        return weights_for_min_variance(eligible, bars_by_symbol, as_of, lookback_days)
    if spec.family == ROTATION_FAMILY_FIFTY_TWO_WEEK_HIGH:
        lookback_days = spec.lookback_days
        top_n = spec.top_n
        if lookback_days is None or top_n is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days and top_n")
        return weights_for_fifty_two_week_high(eligible, bars_by_symbol, as_of, lookback_days, top_n)
    if spec.family == ROTATION_FAMILY_RESIDUAL_MOMENTUM:
        lookback_days = spec.lookback_days
        top_n = spec.top_n
        if lookback_days is None or top_n is None:
            raise ValueError(f"family {spec.family!r} requires lookback_days and top_n")
        return weights_for_residual_momentum(
            eligible, bars_by_symbol, as_of, spec.universe, lookback_days, top_n
        )
    raise ValueError(f"no weight function wired for family {spec.family!r}")


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
) -> float:
    """Each held symbol's dollar allocation drifts with its own daily
    return between rebalances -- no daily rebalancing drag. Mutates
    `dollar_alloc` in place and returns the dollar value released back
    to cash.

    Promoted-minor #3 (final-review fix wave): a symbol with no bar on
    `curr_date` (a real data gap, not just a membership lapse) is
    REMOVED from the allocation and its last known value returned to
    the caller as cash, rather than left in place at a frozen,
    non-drifting value. A frozen leg is a silent fabrication: it
    reports a position whose value provably stopped tracking anything
    real, and it is most load-bearing in EQUAL_WEIGHT_BASELINE -- the
    spec's own designated baseline every other rotation family is
    measured against, so one frozen leg there distorts every family's
    comparison, not just its own. A symbol missing only the PREVIOUS
    date's close (the first bar after a gap) is held un-drifted for
    that single step -- there is no honest return to apply across a
    gap, and it is a real, present position again from here on."""
    released = 0.0
    for symbol in list(dollar_alloc):
        curr_close = close_by_symbol_date.get(symbol, {}).get(curr_date)
        if not curr_close:
            released += dollar_alloc.pop(symbol)
            continue
        prev_close = close_by_symbol_date.get(symbol, {}).get(prev_date)
        if prev_close:
            dollar_alloc[symbol] *= curr_close / prev_close
    return released


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

    warmup = spec.lookback_days or 0
    # I1 (final-review fix wave): the insufficient-history guard
    # run_backtest has always had (engine.py raises whenever
    # bars.height < _min_bars_for(spec)) and this engine did not. Without
    # it, a universe with fewer dates than `lookback_days` never reaches
    # its first rebalance and this function returns a fabricated flat
    # EUR1,000 curve -- which run_one then records as a genuine REJECT
    # decision in the APPEND-ONLY `decisions` table (Law 6: never
    # correctable). Raising ValueError instead is what
    # experiments.failure.classify_exception turns into
    # FailureMode.INSUFFICIENT_DATA, the honest classification.
    if len(all_dates) <= warmup:
        raise ValueError(
            f"not enough bars for universe {spec.universe} as of {as_of_cutoff}: "
            f"need > {warmup}, have {len(all_dates)}"
        )

    bars_by_symbol: dict[str, pl.DataFrame] = {
        symbol: frame.filter(pl.col("symbol") == symbol).sort("available_at")
        for symbol in spec.universe
    }
    close_by_symbol_date: dict[str, dict[date, float]] = {
        symbol: {row["available_at"].date(): row["close"] for row in bars.iter_rows(named=True)}
        for symbol, bars in bars_by_symbol.items()
    }

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
                cash += _drift(dollar_alloc, close_by_symbol_date, prev_date, as_of)
                gross_cash += _drift(
                    gross_dollar_alloc, close_by_symbol_date, prev_date, as_of
                )

            if idx in rebalance_indices:
                # Promoted-minor #3: membership eligibility (Law 2) is
                # necessary but not sufficient -- a symbol whose bar is
                # genuinely missing on this date has no price to size,
                # trade or mark a position against, so it is not
                # allocatable today no matter what its membership window
                # says. Excluding it here is what keeps its slice in cash
                # rather than handing it a weight that would immediately
                # become a frozen, non-drifting leg.
                eligible = [
                    symbol
                    for symbol in _eligible_symbols(spec.universe, membership, as_of)
                    if close_by_symbol_date.get(symbol, {}).get(as_of)
                ]
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

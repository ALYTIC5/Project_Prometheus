"""Sharpe/Sortino/Calmar/max-drawdown/tail-ratio via cpz-quant's
compute_risk_analytics (CLAUDE.md: do not hand-roll Sharpe). Turnover is a
pass-through of BacktestResult's own field, computed nowhere twice.
hit_rate is plain arithmetic over the equity curve.

information_coefficient / icir are NOT in cpz-quant -- IC is a property of
the raw SIGNAL (does the fast-minus-slow SMA spread predict the forward
return), which the certification layer never sees; it only sees an equity
curve. Computed with scipy.stats.spearmanr (a real library call, not a
hand-rolled rank correlation -- the same "use the real implementation"
rule CLAUDE.md applies to PBO/Sharpe). Per PROMPTS.md PROMPT 5: IC/ICIR
carry NO hardcoded pass/fail here -- decay.py is where a horizon claim
gets judged, this module only measures.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import polars as pl
from cpz_quant.certification.analytics import RiskAnalytics, compute_risk_analytics
from scipy.stats import spearmanr

from prometheus.backtest.engine import signal_for
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.splits import derive_folds


@dataclass(frozen=True)
class ValidationMetrics:
    # None below cpz-quant's own 30-observation floor -- honestly absent,
    # not fabricated, on a strategy that hasn't accumulated enough history.
    risk: RiskAnalytics | None
    turnover: float
    hit_rate: float | None
    information_coefficient: float | None
    icir: float | None


def hit_rate(equity_curve: tuple[tuple[str, float], ...]) -> float | None:
    """Fraction of bars where equity rose. None on fewer than 2 points --
    there is no bar-over-bar comparison to make yet."""
    if len(equity_curve) < 2:
        return None
    positive = 0
    total = 0
    prev = equity_curve[0][1]
    for _, equity in equity_curve[1:]:
        total += 1
        if equity > prev:
            positive += 1
        prev = equity
    return positive / total if total else None


def _with_ic_columns(signaled: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """Spread and forward return computed over the FULL series before any
    fold slicing -- shift(-horizon) must see genuine chronological
    neighbors. Slicing first (e.g. inside a per-fold loop) would let a
    combinatorial fold's non-contiguous test blocks pull a "forward"
    value from an unrelated block at the seam between them."""
    return signaled.with_columns(
        (pl.col("_fast") - pl.col("_slow")).alias("_spread"),
        (pl.col("close").shift(-horizon) / pl.col("close") - 1).alias("_forward_return"),
    )


def _correlation_with_pvalue(frame: pl.DataFrame) -> tuple[float, float] | None:
    frame = frame.drop_nulls(["_spread", "_forward_return"])
    if frame.height < 3:
        return None
    spread = frame["_spread"].to_numpy()
    forward_return = frame["_forward_return"].to_numpy()
    if spread.std() == 0 or forward_return.std() == 0:
        return None
    correlation, p_value = spearmanr(spread, forward_return)
    if correlation != correlation:  # NaN guard
        return None
    return float(correlation), float(p_value)


def _correlation(frame: pl.DataFrame) -> float | None:
    result = _correlation_with_pvalue(frame)
    return result[0] if result is not None else None


def information_coefficient(bars: pl.DataFrame, spec: StrategySpec, horizon: int) -> float | None:
    """Spearman rank correlation between the signal's raw strength (fast
    SMA minus slow SMA, known as of each bar's own close -- NOT the
    execution-shifted `position` column) and the forward return over
    `horizon` bars."""
    return _correlation(_with_ic_columns(signal_for(bars, spec), horizon))


def information_coefficient_with_pvalue(
    bars: pl.DataFrame, spec: StrategySpec, horizon: int
) -> tuple[float, float] | None:
    """Same as information_coefficient, plus scipy's own p-value for the
    correlation -- decay.py's "does it have power at the claimed horizon"
    needs a significance test, not just a nonzero sign, and scipy already
    computes one rather than this module hand-rolling a second one."""
    return _correlation_with_pvalue(_with_ic_columns(signal_for(bars, spec), horizon))


def information_coefficient_ratio(
    bars: pl.DataFrame, spec: StrategySpec, horizon: int
) -> float | None:
    """ICIR: mean(IC)/std(IC) across folds -- the textbook definition of
    "is the IC consistent, not just positive once". Reuses
    validation.splits.derive_folds rather than an ad hoc rolling window,
    so its fold boundaries are the same purge/embargo-respecting ones the
    rest of validation uses."""
    full = _with_ic_columns(signal_for(bars, spec), horizon)
    folds = derive_folds(bars.height, spec.expected_horizon)
    ics = [
        ic
        for fold in folds
        if (ic := _correlation(full[list(fold.test_idx)])) is not None
    ]
    if len(ics) < 2:
        return None
    mean_ic = statistics.mean(ics)
    stdev_ic = statistics.stdev(ics)
    return mean_ic / stdev_ic if stdev_ic > 0 else None


def compute_metrics(
    equity_curve: tuple[tuple[str, float], ...],
    turnover: float,
    bars: pl.DataFrame,
    spec: StrategySpec,
) -> ValidationMetrics:
    equity_values = [equity for _, equity in equity_curve]
    risk = compute_risk_analytics(equity_values) if len(equity_values) >= 2 else None
    return ValidationMetrics(
        risk=risk,
        turnover=turnover,
        hit_rate=hit_rate(equity_curve),
        information_coefficient=information_coefficient(bars, spec, spec.expected_horizon),
        icir=information_coefficient_ratio(bars, spec, spec.expected_horizon),
    )

"""Sharpe/Sortino/Calmar/max-drawdown/tail-ratio via cpz-quant's
compute_risk_analytics (CLAUDE.md: do not hand-roll Sharpe). Turnover is a
pass-through of BacktestResult's own field, computed nowhere twice.
hit_rate is plain arithmetic over the equity curve.

information_coefficient / icir are NOT in cpz-quant -- IC is a property of
the raw SIGNAL (does a family's own continuous `_signal_strength` column
predict the forward return), which the certification layer never sees; it
only sees an equity curve. Computed with scipy.stats.spearmanr (a real
library call, not a hand-rolled rank correlation -- the same "use the real
implementation" rule CLAUDE.md applies to PBO/Sharpe). Per PROMPTS.md
PROMPT 5: IC/ICIR carry NO hardcoded pass/fail here -- decay.py is where a
horizon claim gets judged, this module only measures.

Signal-strength contract (found 2026-09-24: `_with_ic_columns` hardcoded
`_fast`/`_slow`, which only 4 of 47 families' signal_for() output ever
carried -- every other family's validate_grid pass silently `continue`d
past a ColumnNotFoundError, dropping the whole row including risk/Sharpe/
hit_rate that had already computed cleanly). `strategy.spec.
EMITS_SIGNAL_STRENGTH` is the single declared source of truth for which
families' signal_for() output MUST carry a continuous `_signal_strength`
column: True means it must be there (a missing column is a real bug,
raised as SignalStrengthContractViolation, never silently guessed as
None); False is a deliberate, declared absence (event/regime-switch
families with no cited continuous form) -- IC/ICIR are honestly None for
those, same "absent beats fabricated" rule RotationSpec's own
information_coefficient=None already uses.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import polars as pl
from cpz_quant.certification.analytics import RiskAnalytics, compute_risk_analytics
from scipy.stats import spearmanr

from prometheus.backtest.engine import signal_for
from prometheus.strategy.spec import EMITS_SIGNAL_STRENGTH, StrategySpec
from prometheus.validation.splits import derive_folds


class SignalStrengthContractViolation(Exception):
    """A family declares EMITS_SIGNAL_STRENGTH[family] = True but its
    signal_for() output didn't carry `_signal_strength` -- a real coding
    bug in that family's signal generator, not a case to silently treat as
    "no continuous signal." Distinct from a declared False, which returns
    None cleanly and never raises this."""


@dataclass(frozen=True)
class ValidationMetrics:
    # None below cpz-quant's own 30-observation floor -- honestly absent,
    # not fabricated, on a strategy that hasn't accumulated enough history.
    risk: RiskAnalytics | None
    turnover: float
    hit_rate: float | None
    information_coefficient: float | None
    icir: float | None
    # {"information_coefficient": repr(exc)} etc -- which named metrics
    # actually failed to compute and why, never silently absorbed into a
    # bare None. Empty means every metric this spec's family declares it
    # should produce, produced. experiments/runner.py persists this
    # verbatim and validation/decision.py refuses PROMOTE while it's
    # non-empty -- incomplete evidence must never look like complete
    # evidence.
    metric_failures: dict[str, str] = field(default_factory=dict)


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


def signal_frame_or_none(bars: pl.DataFrame, spec: StrategySpec) -> pl.DataFrame | None:
    """The single gate every IC/ICIR entry point below goes through, and
    the one place signal_for() is actually called for validation purposes
    -- CALL THIS AT MOST ONCE PER SPEC. Found 2026-09-24, same day as the
    signal-strength fix that made this call reachable for 43 more
    families: compute_metrics's IC+ICIR and decay.py's 9 DECAY_HORIZONS
    (+1 claimed) each independently re-ran signal_for(bars, spec) from
    scratch -- ~12 redundant re-computations of the SAME per-family
    indicator (several of them O(n*window) pure-Python rolling_map calls:
    CCI/HULL_MA_TREND/AROON_CROSSOVER/LINREG_SLOPE) per validated spec,
    across every symbol/family in a batch. Harmless while only 4 families
    ever reached this code path; once the signal-strength fix let all 47
    through, this compounded enough to blow the research concern's
    execution budget in production (job_health showed 100% job failure /
    research stuck for hours after that same deploy) -- fixed by callers
    (compute_metrics, experiments/runner.py) computing this ONCE per spec
    and threading it through instead of recomputing per horizon.

    `EMITS_SIGNAL_STRENGTH[spec.family]` is the declared contract (spec.py
    is the source of truth, checked exhaustively by
    tests/test_validation_metrics.py against every registered family) --
    False returns None here, cleanly, same "absent beats fabricated"
    treatment RotationSpec's own information_coefficient=None already
    gets. True but signal_for() didn't actually emit `_signal_strength` is
    a real bug in that family's signal generator, not a reason to guess
    None -- raised loudly so it shows up in ValidationMetrics.
    metric_failures instead of silently vanishing the way the old
    hardcoded `_fast`/`_slow` lookup did for 43 of 47 families."""
    if not EMITS_SIGNAL_STRENGTH.get(spec.family, False):
        return None
    signaled = signal_for(bars, spec)
    if "_signal_strength" not in signaled.columns:
        raise SignalStrengthContractViolation(
            f"family {spec.family!r} declares EMITS_SIGNAL_STRENGTH=True but "
            "signal_for() did not emit a _signal_strength column"
        )
    return signaled


def _with_ic_columns(signaled: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """Forward return computed over the FULL series before any fold
    slicing -- shift(-horizon) must see genuine chronological neighbors.
    Slicing first (e.g. inside a per-fold loop) would let a combinatorial
    fold's non-contiguous test blocks pull a "forward" value from an
    unrelated block at the seam between them."""
    return signaled.with_columns(
        (pl.col("close").shift(-horizon) / pl.col("close") - 1).alias("_forward_return"),
    )


def _correlation_with_pvalue(frame: pl.DataFrame) -> tuple[float, float] | None:
    frame = frame.drop_nulls(["_signal_strength", "_forward_return"])
    if frame.height < 3:
        return None
    spread = frame["_signal_strength"].to_numpy()
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


def information_coefficient(
    bars: pl.DataFrame, spec: StrategySpec, horizon: int, *, signaled: pl.DataFrame | None = None
) -> float | None:
    """Spearman rank correlation between the family's own continuous
    `_signal_strength` (known as of each bar's own close -- NOT the
    execution-shifted `position` column) and the forward return over
    `horizon` bars. None when this family is declared to have no
    continuous signal (EMITS_SIGNAL_STRENGTH[spec.family] is False).

    Pass `signaled` (this spec's own signal_frame_or_none(bars, spec)
    result) when the caller already computed it -- e.g. compute_metrics
    computing both IC and ICIR from one signal_for() call instead of two.
    Omit it (the default) to compute fresh from bars/spec, unchanged
    behavior for every existing caller/test."""
    if signaled is None:
        signaled = signal_frame_or_none(bars, spec)
    if signaled is None:
        return None
    return _correlation(_with_ic_columns(signaled, horizon))


def information_coefficient_with_pvalue(
    bars: pl.DataFrame, spec: StrategySpec, horizon: int, *, signaled: pl.DataFrame | None = None
) -> tuple[float, float] | None:
    """Same as information_coefficient, plus scipy's own p-value for the
    correlation -- decay.py's "does it have power at the claimed horizon"
    needs a significance test, not just a nonzero sign, and scipy already
    computes one rather than this module hand-rolling a second one. Same
    optional pre-computed `signaled` as information_coefficient."""
    if signaled is None:
        signaled = signal_frame_or_none(bars, spec)
    if signaled is None:
        return None
    return _correlation_with_pvalue(_with_ic_columns(signaled, horizon))


def information_coefficient_ratio(
    bars: pl.DataFrame, spec: StrategySpec, horizon: int, *, signaled: pl.DataFrame | None = None
) -> float | None:
    """ICIR: mean(IC)/std(IC) across folds -- the textbook definition of
    "is the IC consistent, not just positive once". Reuses
    validation.splits.derive_folds rather than an ad hoc rolling window,
    so its fold boundaries are the same purge/embargo-respecting ones the
    rest of validation uses. Same optional pre-computed `signaled` as
    information_coefficient."""
    if signaled is None:
        signaled = signal_frame_or_none(bars, spec)
    if signaled is None:
        return None
    full = _with_ic_columns(signaled, horizon)
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


_UNCOMPUTED = object()  # sentinel: "caller didn't pass one, compute it yourself"


def compute_metrics(
    equity_curve: tuple[tuple[str, float], ...],
    turnover: float,
    bars: pl.DataFrame,
    spec: StrategySpec,
    *,
    signaled: pl.DataFrame | None = _UNCOMPUTED,  # type: ignore[assignment]
) -> ValidationMetrics:
    """Every metric computes independently -- one failing (a real bug in
    one family's signal_for(), a degenerate fold split, anything else)
    must never discard risk/turnover/hit_rate that already computed
    cleanly. Each failure is named in metric_failures instead of raising,
    so experiments/runner.py always has a row to persist and validation/
    decision.py can refuse to treat it as complete evidence.

    `signaled` lets a caller that has ALREADY called signal_frame_or_none
    for this spec (experiments/runner.py, to also share it with
    compute_decay) pass the result straight through instead of this
    function re-deriving it -- signal_for() is the expensive part (see
    signal_frame_or_none's own docstring on the 2026-09-24 redundant-
    recomputation incident), IC and ICIR both need it, and re-running it
    twice here was exactly that bug in miniature. Omit it (the default
    sentinel) to compute it once internally, unchanged behavior for every
    existing caller/test that only wants risk/turnover/hit_rate/IC/ICIR
    from raw bars."""
    equity_values = [equity for _, equity in equity_curve]
    risk = compute_risk_analytics(equity_values) if len(equity_values) >= 2 else None

    metric_failures: dict[str, str] = {}

    resolved_signaled: pl.DataFrame | None = None
    if signaled is not _UNCOMPUTED:
        resolved_signaled = signaled
    else:
        try:
            resolved_signaled = signal_frame_or_none(bars, spec)
        except Exception as exc:
            metric_failures["information_coefficient"] = repr(exc)
            metric_failures["icir"] = repr(exc)

    information_coefficient_value: float | None = None
    if "information_coefficient" not in metric_failures:
        try:
            information_coefficient_value = information_coefficient(
                bars, spec, spec.expected_horizon, signaled=resolved_signaled
            )
        except Exception as exc:
            metric_failures["information_coefficient"] = repr(exc)

    icir_value: float | None = None
    if "icir" not in metric_failures:
        try:
            icir_value = information_coefficient_ratio(
                bars, spec, spec.expected_horizon, signaled=resolved_signaled
            )
        except Exception as exc:
            metric_failures["icir"] = repr(exc)

    return ValidationMetrics(
        risk=risk,
        turnover=turnover,
        hit_rate=hit_rate(equity_curve),
        information_coefficient=information_coefficient_value,
        icir=icir_value,
        metric_failures=metric_failures,
    )

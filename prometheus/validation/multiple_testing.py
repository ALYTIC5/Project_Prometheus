"""Multiple-testing correction: the real, cumulative trial count, and the
Deflated/Probabilistic Sharpe Ratio.

Hand-rolled DSR/PSR, not cpz-quant, and this is a deliberate exception to
CLAUDE.md's "don't hand-roll Sharpe/PBO/DSR" -- read cpz-quant 1.1.0's
actual source before writing this file: despite its own module docstring
naming "Deflated Sharpe Ratio" as a certification feature,
`CertRigor.deflated_sharpe`/`probabilistic_sharpe`
(cpz_quant/certification/grade.py) are INPUT fields on a grading
dataclass that the proprietary `cpz-ai` SDK fills in -- this OSS package
never computes them. See docs/DEPENDENCIES.md's cpz-quant entry for the
full finding. What follows is Bailey & Lopez de Prado (2014), "The
Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting, and Non-Normality", Journal of Portfolio Management 40(5) --
a published closed form, the same "cited constant, not an invented
threshold" category the null suite's z=1.96 already establishes for this
codebase.

PROMPTS.md's own words: "Deflated Sharpe uses the ACTUAL cumulative
count. Evidence requirements tighten as count grows." -- trials_to_date()
is a live COUNT(*) over `results`, not a separate counter table that
could drift from what actually ran.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# To the precision the original paper uses.
_EULER_MASCHERONI = 0.5772156649


def _phi(x: float) -> float:
    """Standard normal CDF -- stdlib erf, no scipy needed for one
    well-known closed form."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Standard normal inverse CDF (probit) -- stdlib statistics.NormalDist,
    same precedent as the null suite's significance test."""
    return statistics.NormalDist().inv_cdf(p)


def _psr_denominator(skewness: float, kurtosis: float, sharpe_hat: float) -> float:
    """The PSR/MinTRL shared denominator -- Bailey & Lopez de Prado
    (2012/2014)'s adjustment for skew and (non-excess) kurtosis. Shared
    by probabilistic_sharpe_ratio and minimum_track_record_length so the
    same formula is never duplicated between the two companion
    statistics."""
    return 1.0 - skewness * sharpe_hat + ((kurtosis - 1.0) / 4.0) * sharpe_hat**2


def probabilistic_sharpe_ratio(
    sharpe_hat: float,
    benchmark_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
) -> float | None:
    """PSR(SR*): the probability the TRUE Sharpe exceeds benchmark_sharpe,
    given an observed Sharpe estimated over n_observations periods with
    the given skew/kurtosis (non-excess convention -- Gaussian kurtosis
    == 3.0; cpz-quant's RiskAnalytics.excess_kurtosis needs +3 before
    passing it here). None if n_observations < 2 (no variance to estimate
    from) or the denominator is non-positive (numerically degenerate, not
    a valid estimate to report -- happens for extreme skew/kurtosis
    combined with a large |sharpe_hat|)."""
    if n_observations < 2:
        return None
    denom = _psr_denominator(skewness, kurtosis, sharpe_hat)
    if denom <= 0:
        return None
    z = (sharpe_hat - benchmark_sharpe) * math.sqrt(n_observations - 1) / math.sqrt(denom)
    return _phi(z)


def minimum_track_record_length(
    *,
    sharpe_hat: float,
    benchmark_sharpe: float,
    skewness: float,
    kurtosis: float,
    confidence: float,
) -> int | None:
    """Bailey & Lopez de Prado's Minimum Track Record Length -- the
    number of independent observations needed before an observed Sharpe
    is distinguishable from benchmark_sharpe at the given confidence,
    given the same skew/kurtosis adjustment probabilistic_sharpe_ratio
    already applies (same paper, same _psr_denominator helper -- the
    natural companion statistic, not a new formula family). Used by
    paper/duration.py to answer PROMPTS.md's "observation period derived
    from horizon and independent trade count needed for significance"
    with a citable closed form instead of an invented number.

    None if the denominator is non-positive (same degenerate case
    probabilistic_sharpe_ratio guards against) or sharpe_hat equals
    benchmark_sharpe (no finite track record distinguishes an edge of
    exactly zero from the benchmark)."""
    denom = _psr_denominator(skewness, kurtosis, sharpe_hat)
    if denom <= 0:
        return None
    diff = sharpe_hat - benchmark_sharpe
    if diff == 0:
        return None
    z = _phi_inv(confidence)
    n_star = 1.0 + denom * (z**2) / (diff**2)
    return max(2, math.ceil(n_star))


def expected_max_sharpe(n_trials: int, sharpe_std_across_trials: float) -> float | None:
    """E[max SR_n] across n_trials independent trials under the null (all
    true Sharpes zero) -- the benchmark PSR is deflated against. None if
    n_trials < 2 (no meaningful "max of many" to expect) or the trial
    Sharpes have zero spread (nothing to select-bias against)."""
    if n_trials < 2 or sharpe_std_across_trials <= 0:
        return None
    return sharpe_std_across_trials * (
        (1 - _EULER_MASCHERONI) * _phi_inv(1 - 1.0 / n_trials)
        + _EULER_MASCHERONI * _phi_inv(1 - 1.0 / (n_trials * math.e))
    )


@dataclass(frozen=True)
class DeflatedSharpeResult:
    deflated_sharpe: float | None  # PSR evaluated at the expected-max-Sharpe benchmark
    expected_max_sharpe_null: float | None
    n_trials_for_deflation: int
    n_observations: int


def deflated_sharpe_ratio(
    *,
    trial_sharpes_for_variance: list[float],
    this_trial_sharpe: float,
    n_trials_for_deflation: int,
    n_observations: int,
    skewness: float,
    kurtosis: float,
) -> DeflatedSharpeResult:
    """Two different trial counts, deliberately decoupled:

    `trial_sharpes_for_variance` is the CONCURRENT grid batch's own
    per-spec Sharpes -- the only real cross-sectional Sharpe distribution
    available today to estimate "how much could luck alone produce"
    from (no historical Sharpe is stored for the corpus run before
    PROMPT 5, so there is nothing better to draw a variance estimate
    from yet).

    `n_trials_for_deflation` is the REAL cumulative count from
    trials_to_date() -- the selection-PRESSURE denominator PROMPTS.md
    calls for ("the ACTUAL cumulative count"), which only grows over
    time and is not bounded by any one grid's batch size.
    """
    std = (
        statistics.stdev(trial_sharpes_for_variance)
        if len(trial_sharpes_for_variance) >= 2
        else 0.0
    )
    sr_benchmark = expected_max_sharpe(n_trials_for_deflation, std)
    dsr = (
        None
        if sr_benchmark is None
        else probabilistic_sharpe_ratio(
            this_trial_sharpe, sr_benchmark, n_observations, skewness, kurtosis
        )
    )
    return DeflatedSharpeResult(
        deflated_sharpe=dsr,
        expected_max_sharpe_null=sr_benchmark,
        n_trials_for_deflation=n_trials_for_deflation,
        n_observations=n_observations,
    )


_SELECT_TRIALS_TO_DATE = text("SELECT COUNT(*) FROM results")


async def trials_to_date(session: AsyncSession) -> int:
    """The real, live experiment corpus size."""
    return int((await session.execute(_SELECT_TRIALS_TO_DATE)).scalar_one())

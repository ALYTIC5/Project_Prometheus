"""PROMOTE / PROMISING / CONTINUE_RESEARCH / REGIME_SPECIALIST / DORMANT /
QUARANTINE / REJECT / RETIRE.

WORSE_THAN_HOLDING is the FIRST check, before PBO/DSR -- PROMPTS.md's own
words. Everything after that point is only reached once a strategy has
already cleared Law 8's baseline bar; PBO/DSR then decide how MUCH to
trust the edge, not whether one exists at all.

reason_codes reuse experiments/failure.py's FailureMode vocabulary where
it already covers the case (WORSE_THAN_HOLDING, NO_TRADES), plus new
codes this module adds (OVERFITTING, DSR_NOT_POSITIVE, REGIME_INCONSISTENT)
-- all landing in the same flat decisions.reason_codes JSONB array the
existing jsonb_array_elements_text aggregation already counts, so nothing
downstream needs a second vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from prometheus.experiments.failure import FailureMode
from prometheus.validation.scoring import ScoreInputs, compute_score

# PBO's own cited overfit convention (Bailey, Borwein, Lopez de Prado &
# Zhu 2015), reused verbatim -- see scoring.py's module docstring.
_PBO_OVERFIT_CUTOFF = 0.5

# The natural midpoint of scoring.py's own scale (an unweighted mean of
# binary [0,1] evidence components) -- "a majority of the available
# evidence is positive," not a separately invented pass bar.
_PROMISING_SCORE_FLOOR = 50.0


class Verdict(str, Enum):
    PROMOTE = "PROMOTE"
    PROMISING = "PROMISING"
    CONTINUE_RESEARCH = "CONTINUE_RESEARCH"
    REGIME_SPECIALIST = "REGIME_SPECIALIST"
    DORMANT = "DORMANT"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"
    RETIRE = "RETIRE"


@dataclass(frozen=True)
class Evidence:
    score_inputs: ScoreInputs
    turnover: float
    consistent_across_regimes: bool | None
    # A prior verdict for this same strategy fingerprint, if one exists --
    # None for every strategy validated for the first time (true of all
    # of them until this module has run at least twice against the same
    # fingerprint). RETIRE is only reachable once something WAS promoted.
    previous_verdict: str | None = None
    # Names of any metric that failed to compute for this spec (see
    # validation/metrics.py's ValidationMetrics.metric_failures) --
    # non-empty means the evidence behind this decision is incomplete,
    # not just imperfect. Never invented as a reason to reject outright
    # (WORSE_THAN_HOLDING/REJECT/DORMANT/QUARANTINE/REGIME_SPECIALIST
    # don't depend on IC/ICIR being trustworthy in the "good news"
    # direction, so those verdicts stand on their own); only PROMOTE is
    # gated, below.
    metric_failures: tuple[str, ...] = ()
    # Law 8: True when the result's benchmark universe or window differs
    # from the strategy's own. Checked FIRST -- a comparison against the
    # wrong benchmark can't support any verdict, WORSE_THAN_HOLDING
    # included.
    benchmark_mismatch: bool = False


@dataclass(frozen=True)
class DecisionResult:
    verdict: Verdict
    score: float
    reason_codes: list[str]


def decide(evidence: Evidence) -> DecisionResult:
    score_result = compute_score(evidence.score_inputs)

    # 0. A mismatched benchmark means every comparison below is against
    #    the wrong thing -- held for research, never scored as a verdict.
    if evidence.benchmark_mismatch:
        return DecisionResult(
            Verdict.CONTINUE_RESEARCH, score_result.score, ["BENCHMARK_MISMATCH"]
        )

    # 1. WORSE_THAN_HOLDING first, before anything else.
    if score_result.worse_than_holding:
        if evidence.previous_verdict == Verdict.PROMOTE.value:
            return DecisionResult(
                Verdict.RETIRE, score_result.score, ["WORSE_THAN_HOLDING", "RETIRE_FROM_PROMOTE"]
            )
        return DecisionResult(
            Verdict.REJECT, score_result.score, [FailureMode.WORSE_THAN_HOLDING.value]
        )

    # 2. Nothing was actually tested -- dormant, not rejected.
    if evidence.turnover == 0.0:
        return DecisionResult(Verdict.DORMANT, score_result.score, [FailureMode.NO_TRADES.value])

    pbo = evidence.score_inputs.pbo
    dsr = evidence.score_inputs.deflated_sharpe

    # 3. Overfitting -- PBO's own cited convention.
    if pbo is not None and pbo > _PBO_OVERFIT_CUTOFF:
        return DecisionResult(Verdict.REJECT, score_result.score, ["OVERFITTING"])

    # 4. Beats the baseline and clears PBO, but only in a narrow regime.
    if evidence.consistent_across_regimes is False:
        return DecisionResult(
            Verdict.REGIME_SPECIALIST, score_result.score, ["REGIME_INCONSISTENT"]
        )

    # 5. Survives deflation and clears PBO -- the strongest evidence
    #    this pipeline can currently produce. Incomplete evidence must
    #    never look like complete evidence: a metric that failed to
    #    compute (not merely absent-by-design) holds this at
    #    CONTINUE_RESEARCH rather than reaching VALIDATED/CHAMPION-
    #    eligible status on a partial read.
    if dsr is not None and dsr > 0 and (pbo is None or pbo <= _PBO_OVERFIT_CUTOFF):
        if evidence.metric_failures:
            return DecisionResult(
                Verdict.CONTINUE_RESEARCH, score_result.score, ["INCOMPLETE_EVIDENCE"]
            )
        return DecisionResult(Verdict.PROMOTE, score_result.score, [])

    # 6. DSR computed but non-positive -- doesn't survive multiple-testing
    #    correction. Not necessarily overfit (PBO may be fine); held, not
    #    rejected, since more trials could still resolve it either way.
    if dsr is not None and dsr <= 0:
        return DecisionResult(Verdict.QUARANTINE, score_result.score, ["DSR_NOT_POSITIVE"])

    # 7. Beats the baseline, no PBO/DSR evidence yet (too few grid trials
    #    or too few observations for either) -- real positive signal, just
    #    not yet validated against multiple-testing/overfitting.
    if score_result.score >= _PROMISING_SCORE_FLOOR:
        return DecisionResult(Verdict.PROMISING, score_result.score, score_result.reason_codes)

    return DecisionResult(Verdict.CONTINUE_RESEARCH, score_result.score, score_result.reason_codes)

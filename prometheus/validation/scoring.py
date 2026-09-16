"""Composite score. `excess_return` and `excess_sharpe` are REQUIRED
inputs (no defaults) -- Law 8's "everything runs against Buy & Hold" only
holds as a structural guarantee if scoring cannot even be attempted
without both. Underperforming on both is a hard cap to the scale's own
floor (0), not a separately invented cap value -- PROMPTS.md: "hard score
cap preventing PROMOTE. This is Law 8."

Every component's zero-point is a cited external convention, not a number
this file invents:
- PBO: Bailey, Borwein, Lopez de Prado & Zhu (2015) -- "PBO above ~0.5
  means the optimization is more likely than not overfit" (also quoted in
  cpz_quant.certification.overfitting's own docstring).
- Deflated Sharpe: cpz-quant's OWN certification/grade.py gate,
  `evaluate_gates`'s "deflated_sharpe_positive" check, is exactly
  `dsr is not None and dsr > 0` -- reused here, not reinvented.
- excess_sharpe / decay: zero and "not significant at p<0.05" respectively
  are this project's own already-established zero-points (Law 8's "beat
  buy-and-hold" and decay.py's cited significance convention).

Weighting: an unweighted mean of whichever components are available. No
component is asserted more important than another -- that would be a
relative-importance number this project has no basis to invent, so the
least-arbitrary combination rule is used instead.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreInputs:
    excess_return: float
    excess_sharpe: float | None
    pbo: float | None
    deflated_sharpe: float | None
    has_power_at_claimed_horizon: bool | None


@dataclass(frozen=True)
class ScoreResult:
    score: float  # 0-100
    worse_than_holding: bool
    reason_codes: list[str]


def _pbo_component(pbo: float | None) -> float | None:
    # pbo=0 -> 1.0, pbo=0.5 -> 0.0 (the CSCV paper's own overfit cutoff),
    # clamped below zero rather than reporting a negative component.
    return None if pbo is None else max(0.0, 1.0 - 2.0 * pbo)


def _dsr_component(deflated_sharpe: float | None) -> float | None:
    return None if deflated_sharpe is None else (1.0 if deflated_sharpe > 0 else 0.0)


def _excess_sharpe_component(excess_sharpe: float | None) -> float | None:
    return None if excess_sharpe is None else (1.0 if excess_sharpe > 0 else 0.0)


def _decay_component(has_power: bool | None) -> float | None:
    return None if has_power is None else (1.0 if has_power else 0.0)


def compute_score(inputs: ScoreInputs) -> ScoreResult:
    worse_than_holding = inputs.excess_return <= 0 and (
        inputs.excess_sharpe is None or inputs.excess_sharpe <= 0
    )
    if worse_than_holding:
        return ScoreResult(score=0.0, worse_than_holding=True, reason_codes=["WORSE_THAN_HOLDING"])

    components = [
        _pbo_component(inputs.pbo),
        _dsr_component(inputs.deflated_sharpe),
        _excess_sharpe_component(inputs.excess_sharpe),
        _decay_component(inputs.has_power_at_claimed_horizon),
    ]
    available = [c for c in components if c is not None]
    reason_codes = []
    if len(available) < len(components):
        reason_codes.append("SCORE_PARTIAL_EVIDENCE")
    score = (sum(available) / len(available) * 100) if available else 0.0
    return ScoreResult(score=score, worse_than_holding=False, reason_codes=reason_codes)

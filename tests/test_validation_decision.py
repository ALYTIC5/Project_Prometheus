"""validation/scoring.py + validation/decision.py. Pure functions, no DB."""
from __future__ import annotations

from prometheus.validation.decision import Evidence, Verdict, decide
from prometheus.validation.scoring import ScoreInputs, compute_score


def _inputs(**overrides: object) -> ScoreInputs:
    defaults: dict[str, object] = dict(
        excess_return=5.0,
        excess_sharpe=0.5,
        pbo=0.1,
        deflated_sharpe=0.3,
        has_power_at_claimed_horizon=True,
    )
    defaults.update(overrides)
    return ScoreInputs(**defaults)  # type: ignore[arg-type]


def test_worse_than_holding_hard_caps_score_to_zero() -> None:
    result = compute_score(_inputs(excess_return=-1.0, excess_sharpe=-0.2))
    assert result.score == 0.0
    assert result.worse_than_holding is True
    assert "WORSE_THAN_HOLDING" in result.reason_codes


def test_positive_evidence_scores_above_zero() -> None:
    result = compute_score(_inputs())
    assert result.score > 0.0
    assert result.worse_than_holding is False


def test_missing_evidence_is_flagged_not_silently_averaged_as_zero() -> None:
    result = compute_score(_inputs(pbo=None, deflated_sharpe=None))
    assert "SCORE_PARTIAL_EVIDENCE" in result.reason_codes


# --- decision.decide ------------------------------------------------------


def _evidence(**overrides: object) -> Evidence:
    defaults: dict[str, object] = dict(
        score_inputs=_inputs(),
        turnover=1.0,
        consistent_across_regimes=True,
        previous_verdict=None,
    )
    defaults.update(overrides)
    return Evidence(**defaults)  # type: ignore[arg-type]


def test_worse_than_holding_checked_before_pbo() -> None:
    """PROMPTS.md's explicit ordering rule: WORSE_THAN_HOLDING is the
    FIRST check, before PBO/DSR -- even a strategy with a terrible PBO
    (which would independently justify REJECT/OVERFITTING) must be
    reported as WORSE_THAN_HOLDING when it's also worse than holding,
    not OVERFITTING."""
    evidence = _evidence(
        score_inputs=_inputs(excess_return=-2.0, excess_sharpe=-0.5, pbo=0.9),
    )
    result = decide(evidence)
    assert result.verdict == Verdict.REJECT
    assert "WORSE_THAN_HOLDING" in result.reason_codes
    assert "OVERFITTING" not in result.reason_codes


def test_overfit_strategy_rejected() -> None:
    """The prompt's own acceptance bar, at the decision layer: PBO > 0.5
    (the CSCV paper's cited overfit convention) rejects with OVERFITTING,
    given a strategy that otherwise beats the baseline."""
    evidence = _evidence(score_inputs=_inputs(pbo=0.75))
    result = decide(evidence)
    assert result.verdict == Verdict.REJECT
    assert "OVERFITTING" in result.reason_codes


def test_no_trades_is_dormant_not_rejected() -> None:
    evidence = _evidence(turnover=0.0)
    result = decide(evidence)
    assert result.verdict == Verdict.DORMANT


def test_regime_inconsistent_strategy_is_regime_specialist() -> None:
    evidence = _evidence(consistent_across_regimes=False)
    result = decide(evidence)
    assert result.verdict == Verdict.REGIME_SPECIALIST


def test_promotes_on_full_positive_evidence() -> None:
    evidence = _evidence()
    result = decide(evidence)
    assert result.verdict == Verdict.PROMOTE


def test_non_positive_dsr_is_quarantined_not_rejected() -> None:
    evidence = _evidence(score_inputs=_inputs(deflated_sharpe=-0.1))
    result = decide(evidence)
    assert result.verdict == Verdict.QUARANTINE
    assert "DSR_NOT_POSITIVE" in result.reason_codes


def test_metric_failure_blocks_promote_even_with_full_positive_evidence() -> None:
    """Found 2026-09-24: a metric that failed to compute (a real bug, not
    a declared absence) must never let a spec reach PROMOTE/VALIDATED on
    partial evidence -- otherwise a family whose IC computation silently
    broke would still get promoted on Sharpe/PBO/DSR alone, looking
    exactly like a fully-evidenced PROMOTE from the outside."""
    evidence = _evidence(metric_failures=("information_coefficient",))
    result = decide(evidence)
    assert result.verdict == Verdict.CONTINUE_RESEARCH
    assert "INCOMPLETE_EVIDENCE" in result.reason_codes


def test_no_metric_failures_still_promotes() -> None:
    """The gate only fires on a non-empty metric_failures -- the default
    empty tuple must not regress test_promotes_on_full_positive_evidence's
    own guarantee."""
    evidence = _evidence(metric_failures=())
    result = decide(evidence)
    assert result.verdict == Verdict.PROMOTE


def test_retire_only_reachable_from_a_prior_promote() -> None:
    fresh = decide(
        _evidence(
            score_inputs=_inputs(excess_return=-1.0, excess_sharpe=-0.2),
            previous_verdict=None,
        )
    )
    assert fresh.verdict == Verdict.REJECT

    regressed = decide(
        _evidence(
            score_inputs=_inputs(excess_return=-1.0, excess_sharpe=-0.2),
            previous_verdict=Verdict.PROMOTE.value,
        )
    )
    assert regressed.verdict == Verdict.RETIRE


def test_benchmark_mismatch_blocks_every_verdict_including_promote() -> None:
    """Law 8: a comparison against the wrong benchmark supports no verdict
    -- checked before WORSE_THAN_HOLDING, and never VALIDATED."""
    evidence = _evidence(benchmark_mismatch=True)
    result = decide(evidence)
    assert result.verdict == Verdict.CONTINUE_RESEARCH
    assert result.reason_codes == ["BENCHMARK_MISMATCH"]

    worse = _evidence(
        benchmark_mismatch=True,
        score_inputs=_inputs(excess_return=-2.0, excess_sharpe=-0.5),
    )
    assert decide(worse).reason_codes == ["BENCHMARK_MISMATCH"]

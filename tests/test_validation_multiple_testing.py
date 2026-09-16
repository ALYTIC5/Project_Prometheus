"""validation/multiple_testing.py -- PSR/DSR closed form. Pure functions,
no DB (trials_to_date is the only DB-touching function here and is a
one-line COUNT(*), not separately tested)."""
from __future__ import annotations

from prometheus.validation.multiple_testing import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)

_NORMAL_SKEW = 0.0
_NORMAL_KURTOSIS = 3.0  # non-excess convention -- Gaussian == 3.0


def test_psr_increases_with_higher_observed_sharpe() -> None:
    low = probabilistic_sharpe_ratio(0.1, 0.0, 252, _NORMAL_SKEW, _NORMAL_KURTOSIS)
    high = probabilistic_sharpe_ratio(1.5, 0.0, 252, _NORMAL_SKEW, _NORMAL_KURTOSIS)
    assert low is not None and high is not None
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_psr_at_exactly_the_benchmark_is_one_half() -> None:
    # z=0 -> Phi(0)=0.5 exactly, for any valid skew/kurtosis pair.
    psr = probabilistic_sharpe_ratio(0.5, 0.5, 100, _NORMAL_SKEW, _NORMAL_KURTOSIS)
    assert psr is not None
    assert abs(psr - 0.5) < 1e-9


def test_psr_none_below_two_observations() -> None:
    assert probabilistic_sharpe_ratio(1.0, 0.0, 1, _NORMAL_SKEW, _NORMAL_KURTOSIS) is None


def test_expected_max_sharpe_increases_with_trial_count() -> None:
    few = expected_max_sharpe(5, sharpe_std_across_trials=1.0)
    many = expected_max_sharpe(500, sharpe_std_across_trials=1.0)
    assert few is not None and many is not None
    assert many > few > 0.0


def test_expected_max_sharpe_none_below_two_trials_or_zero_spread() -> None:
    assert expected_max_sharpe(1, sharpe_std_across_trials=1.0) is None
    assert expected_max_sharpe(10, sharpe_std_across_trials=0.0) is None


def test_deflated_sharpe_lower_than_naive_psr_against_zero() -> None:
    """The whole point of deflation: benchmarking against E[max SR] (what
    many trials could produce by luck alone) is a strictly harder bar to
    clear than benchmarking the same Sharpe against zero -- so DSR must
    never exceed the naive PSR(0) for the same trial's own Sharpe."""
    trial_sharpes = [0.1, -0.2, 0.3, 0.05, -0.1, 0.4, 0.0, -0.3, 0.2, 0.15]
    this_sharpe = 0.8

    dsr_result = deflated_sharpe_ratio(
        trial_sharpes_for_variance=trial_sharpes,
        this_trial_sharpe=this_sharpe,
        n_trials_for_deflation=len(trial_sharpes),
        n_observations=252,
        skewness=_NORMAL_SKEW,
        kurtosis=_NORMAL_KURTOSIS,
    )
    naive_psr = probabilistic_sharpe_ratio(
        this_sharpe, 0.0, 252, _NORMAL_SKEW, _NORMAL_KURTOSIS
    )

    assert dsr_result.deflated_sharpe is not None
    assert naive_psr is not None
    assert dsr_result.deflated_sharpe < naive_psr


def test_deflated_sharpe_none_with_no_trial_history() -> None:
    result = deflated_sharpe_ratio(
        trial_sharpes_for_variance=[],
        this_trial_sharpe=0.5,
        n_trials_for_deflation=1,
        n_observations=100,
        skewness=_NORMAL_SKEW,
        kurtosis=_NORMAL_KURTOSIS,
    )
    assert result.deflated_sharpe is None
    assert result.expected_max_sharpe_null is None

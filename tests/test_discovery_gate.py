"""LORD++ discovery gate: the published rule computed exactly, FDR held on
simulated streams, degradation under correlation reported, and the
excess-return p-value behaving like a p-value."""
from __future__ import annotations

import math
import random
import statistics
from datetime import date, timedelta

import pytest

from prometheus.validation.discovery_gate import (
    ALPHA,
    MIN_OBSERVATIONS,
    W0,
    excess_return_pvalue,
    gamma,
    lord_threshold,
    wealth,
)

# ------------------------------------------------------------ the rule


def test_gamma_matches_the_papers_default_sequence() -> None:
    assert gamma(1) == pytest.approx(0.0722 * math.log(2))
    assert gamma(2) == pytest.approx(0.0722 * math.log(2) / (2 * math.exp(math.sqrt(math.log(2)))))
    assert all(gamma(j + 1) <= gamma(j) for j in range(2, 5000))
    assert sum(gamma(j) for j in range(1, 200_000)) < 1.0


def test_threshold_before_any_discovery_is_gamma_times_initial_wealth() -> None:
    assert lord_threshold(1, []) == pytest.approx(gamma(1) * W0)
    assert lord_threshold(7, []) == pytest.approx(gamma(7) * W0)


def test_threshold_after_discoveries_follows_lord_plus_plus() -> None:
    expected = gamma(9) * W0 + (ALPHA - W0) * gamma(9 - 3) + ALPHA * gamma(9 - 5)
    assert lord_threshold(9, [3, 5]) == pytest.approx(expected)


def test_later_discoveries_are_ignored_for_an_earlier_test() -> None:
    assert lord_threshold(4, [2, 6]) == pytest.approx(lord_threshold(4, [2]))


def test_wealth_accounting() -> None:
    assert wealth([], 0) == pytest.approx(W0)
    assert wealth([0.001], 1) == pytest.approx(W0 - 0.001 + (ALPHA - W0))
    assert wealth([0.001, 0.002], 3) == pytest.approx(W0 - 0.003 + (ALPHA - W0) + 2 * ALPHA)


def _run_lord(p_values: list[float]) -> tuple[list[bool], list[float]]:
    discoveries: list[int] = []
    decisions: list[bool] = []
    spent: list[float] = []
    wealth_trace: list[float] = []
    for t, p in enumerate(p_values, start=1):
        threshold = lord_threshold(t, discoveries)
        spent.append(threshold)
        reject = p <= threshold
        decisions.append(reject)
        if reject:
            discoveries.append(t)
        wealth_trace.append(wealth(spent, len(discoveries)))
    return decisions, wealth_trace


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _simulate(rho: float, *, reps: int, n: int, frac_true: float, effect: float, seed: int):
    """Mean false-discovery proportion and mean discoveries over `reps`
    streams of `n` one-sided z-tests; `rho` is the equicorrelation of the
    test statistics within a stream."""
    rng = random.Random(seed)
    fdps: list[float] = []
    discoveries: list[int] = []
    min_wealth = math.inf
    for _ in range(reps):
        shared = rng.gauss(0, 1)
        truth = [rng.random() < frac_true for _ in range(n)]
        z = [
            (effect if is_true else 0.0)
            + math.sqrt(rho) * shared
            + math.sqrt(1 - rho) * rng.gauss(0, 1)
            for is_true in truth
        ]
        p = [1 - _phi(v) for v in z]
        decisions, wealth_trace = _run_lord(p)
        rejected = sum(decisions)
        false = sum(1 for d, t in zip(decisions, truth, strict=True) if d and not t)
        fdps.append(false / max(rejected, 1))
        discoveries.append(rejected)
        min_wealth = min(min_wealth, min(wealth_trace))
    return statistics.mean(fdps), statistics.mean(discoveries), min_wealth


def test_fdr_is_controlled_on_independent_streams() -> None:
    """Verification #3 of the self-improvement prompt: 100 streams of 1000
    tests, 10% true effects. Realised FDR must stay at the 5% target (a
    0.01 allowance for 100-stream sampling error), the gate must still find
    real effects, and alpha-wealth must never go negative."""
    fdr, mean_discoveries, min_wealth = _simulate(
        0.0, reps=100, n=1000, frac_true=0.10, effect=3.0, seed=11
    )
    print(f"\nLORD++ independent: FDR={fdr:.4f} discoveries/stream={mean_discoveries:.1f}")
    assert fdr <= ALPHA + 0.01
    assert mean_discoveries > 10
    assert min_wealth >= 0


@pytest.mark.parametrize("rho", [0.3, 0.6])
def test_fdr_under_correlated_streams_is_reported_not_guaranteed(rho: float) -> None:
    """Backtests on shared data are correlated in ways LORD++'s guarantee
    does not cover. Measured and printed (docs/DECISIONS.md records the
    numbers); only sanity is asserted."""
    fdr, mean_discoveries, min_wealth = _simulate(
        rho, reps=100, n=1000, frac_true=0.10, effect=3.0, seed=13
    )
    print(f"\nLORD++ rho={rho}: FDR={fdr:.4f} discoveries/stream={mean_discoveries:.1f}")
    assert 0.0 <= fdr <= 1.0
    assert min_wealth >= 0


# ------------------------------------------------------------ the p-value


def _curves(strategy_returns: list[float], benchmark_returns: list[float]):
    start = date(2025, 1, 1)
    s_eq, b_eq = 1000.0, 1000.0
    strategy = [(start.isoformat() + "T00:00:00+00:00", s_eq)]
    benchmark = [(start, b_eq)]
    for i, (rs, rb) in enumerate(zip(strategy_returns, benchmark_returns, strict=True), start=1):
        s_eq *= 1 + rs
        b_eq *= 1 + rb
        day = start + timedelta(days=i)
        strategy.append((day.isoformat() + "T00:00:00+00:00", s_eq))
        benchmark.append((day, b_eq))
    return strategy, benchmark


def test_pvalue_is_small_for_a_real_edge_and_large_for_none() -> None:
    rng = random.Random(3)
    bench = [rng.gauss(0, 0.01) for _ in range(400)]
    edge = [b + 0.002 + rng.gauss(0, 0.002) for b in bench]
    worse = [b - 0.002 + rng.gauss(0, 0.002) for b in bench]
    strong = excess_return_pvalue(*_curves(edge, bench))
    weak = excess_return_pvalue(*_curves(worse, bench))
    assert strong is not None and strong.p_value < 0.001
    assert weak is not None and weak.p_value > 0.999
    assert strong.n_observations == 400


def test_pvalue_is_roughly_uniform_under_the_null() -> None:
    rng = random.Random(5)
    ps = []
    for _ in range(400):
        bench = [rng.gauss(0, 0.01) for _ in range(250)]
        strat = [b + rng.gauss(0, 0.005) for b in bench]
        result = excess_return_pvalue(*_curves(strat, bench))
        assert result is not None
        ps.append(result.p_value)
    rejections = sum(p <= 0.05 for p in ps) / len(ps)
    print(f"\nnull rejection rate at 5%: {rejections:.3f}")
    assert 0.02 <= rejections <= 0.09


def test_too_few_observations_gives_no_pvalue() -> None:
    rets = [0.001] * (MIN_OBSERVATIONS - 1)
    assert excess_return_pvalue(*_curves(rets, [0.0] * len(rets))) is None


def test_only_shared_dates_count() -> None:
    rng = random.Random(9)
    bench = [rng.gauss(0, 0.01) for _ in range(100)]
    strat = [b + rng.gauss(0.001, 0.003) for b in bench]
    strategy, benchmark = _curves(strat, bench)
    result = excess_return_pvalue(strategy, benchmark[:61])
    assert result is not None and result.n_observations == 60

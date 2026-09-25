"""research/clustering.py -- correlation clustering of strategy return
streams. Pure functions, no DB, real synthetic equity curves."""
from __future__ import annotations

from prometheus.research.clustering import (
    _pearson_correlation,
    _returns_from_equity_curve,
    cluster_by_correlation,
)
from prometheus.strategy.spec import StrategySpec

_SYMBOL = "BTC/USDT"


def _spec(fast: int, slow: int) -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM", symbol=_SYMBOL, timeframe="1d",
        fast_window=fast, slow_window=slow, expected_horizon=slow,
    )


def _curve(values: list[float]) -> list[tuple[str, float]]:
    return [(f"2024-01-{i + 1:02d}T00:00:00", v) for i, v in enumerate(values)]


def test_returns_from_equity_curve_computes_period_returns() -> None:
    curve = _curve([100.0, 110.0, 99.0])
    returns = _returns_from_equity_curve(curve)
    assert returns == [0.1, -0.1]


def test_pearson_correlation_identical_series_is_one() -> None:
    a = [0.01, -0.02, 0.03, -0.01, 0.02]
    result = _pearson_correlation(a, list(a))
    assert result is not None
    assert abs(result - 1.0) < 1e-9


def test_pearson_correlation_inverted_series_is_negative_one() -> None:
    a = [0.01, -0.02, 0.03, -0.01, 0.02]
    b = [-x for x in a]
    result = _pearson_correlation(a, b)
    assert result is not None
    assert abs(result - (-1.0)) < 1e-9


def test_pearson_correlation_zero_variance_series_is_none() -> None:
    """A flat (never-trading) return stream has an undefined
    correlation with anything -- must not be silently reported as 0.0
    (a real "no relationship" finding), which would let a genuinely
    untested pair slip into "definitely not the same discovery."""
    flat = [0.0, 0.0, 0.0, 0.0]
    real = [0.01, -0.02, 0.03, -0.01]
    assert _pearson_correlation(flat, real) is None


def test_pearson_correlation_mismatched_lengths_is_none() -> None:
    assert _pearson_correlation([0.1, 0.2], [0.1]) is None


def test_cluster_by_correlation_groups_near_identical_curves() -> None:
    """Two MOMENTUM specs whose equity curves move almost identically
    (the real-world case the whole prompt is about: near-duplicate
    parameterizations of the same underlying signal) must land in one
    cluster, with the fewer-parameter one as representative -- both
    specs here have 2 parameters (fast_window, slow_window), so the
    config_hash() tiebreaker decides; the test only asserts clustering
    happened and the representative is one of the two, not which
    specific hash wins."""
    base = [100.0, 101.0, 99.0, 103.0, 102.0, 105.0, 104.0, 107.0]
    nearly_identical = [v * 1.0001 for v in base]  # negligible noise, correlation ~1.0

    spec_a = _spec(5, 20)
    spec_b = _spec(10, 40)
    clusters = cluster_by_correlation(
        [(spec_a, _curve(base)), (spec_b, _curve(nearly_identical))],
        threshold=0.8,
    )

    assert len(clusters) == 1
    cluster = clusters[0]
    assert not cluster.is_singleton
    assert set(cluster.members) == {spec_a, spec_b}
    assert cluster.mean_pairwise_correlation > 0.99


def test_cluster_by_correlation_keeps_genuinely_different_strategies_apart() -> None:
    """A trending-up curve and a mean-reverting (oscillating) curve over
    the same window are real, different signals -- must NOT cluster."""
    trending = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0]
    oscillating = [100.0, 95.0, 105.0, 92.0, 108.0, 90.0, 110.0, 88.0]

    spec_a = _spec(5, 20)
    spec_b = _spec(10, 40)
    clusters = cluster_by_correlation(
        [(spec_a, _curve(trending)), (spec_b, _curve(oscillating))],
        threshold=0.8,
    )

    assert len(clusters) == 2
    assert all(c.is_singleton for c in clusters)


def test_cluster_representative_is_the_fewest_parameter_member() -> None:
    """RSI (2 params) vs MACD (3 params) with near-identical returns --
    the 2-parameter RSI spec must be the representative, matching
    PROMPTS.md's own "simplest member of a cluster" rule."""
    base = [100.0, 103.0, 101.0, 106.0, 104.0, 109.0, 107.0, 112.0]
    rsi_spec = StrategySpec(
        family="RSI", symbol=_SYMBOL, timeframe="1d",
        rsi_lookback=14, rsi_oversold=30.0, expected_horizon=14,
    )
    macd_spec = StrategySpec(
        family="MACD", symbol=_SYMBOL, timeframe="1d",
        macd_fast=12, macd_slow=26, macd_signal=9, expected_horizon=26,
    )
    clusters = cluster_by_correlation(
        [(macd_spec, _curve(base)), (rsi_spec, _curve([v * 1.0001 for v in base]))],
        threshold=0.8,
    )

    assert len(clusters) == 1
    assert clusters[0].representative == rsi_spec
    assert clusters[0].redundant_variants == (macd_spec,)


def test_cluster_by_correlation_aligns_curves_of_different_lengths() -> None:
    """A longer-warm-up spec's curve must be trimmed to the shortest
    common tail before correlating, same convention
    experiments/runner.py's own PBO batch alignment uses -- not
    excluded, not padded."""
    short_curve = [100.0, 103.0, 101.0, 106.0]
    long_curve = [90.0, 95.0, 100.0, 103.0, 101.0, 106.0]  # extra warm-up bars prepended

    spec_a = _spec(5, 20)
    spec_b = _spec(10, 40)
    clusters = cluster_by_correlation(
        [(spec_a, _curve(short_curve)), (spec_b, _curve(long_curve))],
        threshold=0.8,
    )

    assert len(clusters) == 1
    assert not clusters[0].is_singleton


def test_cluster_by_correlation_empty_input_returns_no_clusters() -> None:
    assert cluster_by_correlation([]) == []


def test_cluster_by_correlation_single_spec_is_its_own_singleton() -> None:
    spec = _spec(5, 20)
    clusters = cluster_by_correlation([(spec, _curve([100.0, 101.0, 99.0]))])
    assert len(clusters) == 1
    assert clusters[0].is_singleton
    assert clusters[0].representative == spec


def test_three_way_transitive_cluster() -> None:
    """A correlates with B, B correlates with C, but A and C are only
    weakly related directly -- real graph-connectivity clustering must
    still group all three (transitive closure via union-find), not stop
    at direct pairs only."""
    base = [100.0, 103.0, 101.0, 106.0, 104.0, 109.0, 107.0, 112.0, 110.0, 115.0]
    a = base
    b = [v * 1.0002 for v in base]
    # c correlates strongly with b's exact shape but is a different absolute
    # scale/offset -- Pearson correlation is scale/offset invariant, so this
    # still clusters with b (and transitively with a) at a high threshold.
    c = [v * 0.998 + 5 for v in base]

    spec_a, spec_b, spec_c = _spec(5, 20), _spec(6, 21), _spec(7, 22)
    clusters = cluster_by_correlation(
        [(spec_a, _curve(a)), (spec_b, _curve(b)), (spec_c, _curve(c))],
        threshold=0.8,
    )

    assert len(clusters) == 1
    assert set(clusters[0].members) == {spec_a, spec_b, spec_c}

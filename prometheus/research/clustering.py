"""Correlation clustering of strategy return streams -- the "100
strategies" prompt's own explicit reasoning: SMA/EMA/DEMA/TEMA/Hull
crossovers (and every other near-duplicate family this project's own
classic-template roster already contains, e.g. STOCHASTIC/WILLIAMS_R)
are largely the same signal wearing different names. If the validation
pipeline treats each as an independent discovery, one real effect shows
up as several "winners," inflating both the apparent survival rate and
(via `validation/multiple_testing.py`'s own trial-count-driven
deflation) the multiple-testing correction every OTHER strategy in the
same batch pays, since `trials_to_date` counts every row in `results`
regardless of how correlated its return stream is to five others.

A cluster counts as ONE discovery. This module answers "which of these
strategies are actually the same discovery" from real return-stream
correlation -- never from family name or parameter count alone (two
different families can converge on a correlated signal; two specs in
the same family with very different parameters need not).

Deliberately NOT wired into `elect_champions()`'s promotion eligibility
yet -- see `docs/DEFERRED.md`'s "Correlation clustering not yet gating
CHAMPION eligibility" entry for why that specific piece (which strategy
in a cluster is CHAMPION-eligible) is scoped as separate, more carefully
reviewed follow-up work, not built in the same pass as this module.
This ships the real clustering computation and its dashboard visibility;
the promotion-eligibility behavior change is the one piece with real
regression risk to the already-live paper-trading gate.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from prometheus.strategy.spec import StrategySpec

# Configurable per PROMPTS.md's own wording ("configurable, in research
# policy") -- 0.8 is a commonly cited "these are effectively the same
# signal" correlation threshold in the return-based style-clustering
# literature (e.g. how fund-of-funds style analysis groups near-
# duplicate strategies), not an invented number specific to this
# project. Exposed as a module constant rather than threaded through
# every caller's signature until a real caller needs a different value
# -- YAGNI, not a design commitment to it being fixed forever.
DEFAULT_CORRELATION_THRESHOLD = 0.8


@dataclass(frozen=True)
class Cluster:
    """One connected group of strategies whose return streams correlate
    above the threshold. `representative` is the simplest member (fewest
    tunable parameters, `spec.parameters`'s own count -- ties broken by
    `config_hash()` for a stable, deterministic pick, never by insertion
    order) -- the one PROMPTS.md's own wording says should remain
    CHAMPION-eligible; every other member is a `redundant_variant`."""

    representative: StrategySpec
    redundant_variants: tuple[StrategySpec, ...]
    mean_pairwise_correlation: float

    @property
    def members(self) -> tuple[StrategySpec, ...]:
        return (self.representative, *self.redundant_variants)

    @property
    def is_singleton(self) -> bool:
        return not self.redundant_variants


def _returns_from_equity_curve(equity_curve: list[tuple[str, float]]) -> list[float]:
    """Period returns, not equity levels -- correlating raw equity LEVELS
    gives spuriously high correlation for any two curves that both trend
    in the same direction (nearly everything does, in a bull market),
    the same reason portfolio correlation is always computed on returns,
    never on price levels."""
    values = [equity for _, equity in equity_curve]
    return [
        (values[i] - values[i - 1]) / values[i - 1] if values[i - 1] != 0 else 0.0
        for i in range(1, len(values))
    ]


def _pearson_correlation(a: list[float], b: list[float]) -> float | None:
    """None (not 0.0) when either series has zero variance -- a flat
    (never-trading) strategy has an undefined correlation with anything,
    not a real "zero correlation" finding; treated as "cannot cluster
    this pair" by the caller, never silently as "definitely different."
    """
    if len(a) < 2 or len(a) != len(b):
        return None
    stdev_a, stdev_b = statistics.pstdev(a), statistics.pstdev(b)
    if stdev_a == 0.0 or stdev_b == 0.0:
        return None
    mean_a, mean_b = statistics.fmean(a), statistics.fmean(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / len(a)
    return covariance / (stdev_a * stdev_b)


def cluster_by_correlation(
    specs_and_curves: list[tuple[StrategySpec, list[tuple[str, float]]]],
    *,
    threshold: float = DEFAULT_CORRELATION_THRESHOLD,
) -> list[Cluster]:
    """Aligns every equity curve to the shortest common length (same
    "most recent common tail" convention `experiments/runner.py`'s own
    PBO batch alignment already uses -- a longer-warm-up spec's curve is
    trimmed to match, not padded or excluded), converts to period
    returns, and groups strategies into connected components of an
    undirected graph whose edges are "pairwise correlation >= threshold"
    -- real graph-connectivity clustering (union-find), not a k-means or
    hierarchical variant that would need picking a cluster COUNT in
    advance (there is no principled way to know how many real effects
    89 candidate strategies collapse into ahead of time; connectivity
    clustering doesn't require guessing that number).

    A strategy whose return stream has zero variance (never traded, or
    the aligned common window happens to be entirely flat for it) cannot
    be correlated with anything and is returned as its own singleton
    cluster -- an honest "nothing to compare" rather than a fabricated
    grouping.
    """
    if not specs_and_curves:
        return []

    min_len = min(len(curve) for _spec, curve in specs_and_curves)
    returns_by_index: list[list[float]] = [
        _returns_from_equity_curve(curve[-min_len:]) for _spec, curve in specs_and_curves
    ]

    n = len(specs_and_curves)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    pairwise_correlations: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            correlation = _pearson_correlation(returns_by_index[i], returns_by_index[j])
            if correlation is not None and correlation >= threshold:
                pairwise_correlations[(i, j)] = correlation
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters: list[Cluster] = []
    for indices in groups.values():
        members = [specs_and_curves[i][0] for i in indices]
        # Fewest tunable parameters first; config_hash() as the
        # deterministic, stable tiebreaker (never insertion order, which
        # would make the "representative" choice depend on incidental
        # iteration order rather than the spec's own content).
        ordered = sorted(members, key=lambda s: (len(s.parameters), s.config_hash()))
        representative, *redundant = ordered

        pair_corrs = [
            corr
            for (a, b), corr in pairwise_correlations.items()
            if a in indices and b in indices
        ]
        mean_corr = statistics.fmean(pair_corrs) if pair_corrs else 0.0

        clusters.append(
            Cluster(
                representative=representative,
                redundant_variants=tuple(redundant),
                mean_pairwise_correlation=mean_corr,
            )
        )
    return clusters

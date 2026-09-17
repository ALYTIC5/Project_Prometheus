"""Crossover -- PROMPT 7. Combines two parent StrategySpecs, preserving
lineage. Only well-defined for two SAME-family, same-symbol, same-
timeframe parents: there is no shared numeric parameter space across
families without the DSL surface (deliberately deferred to Prompt 9, see
research/mutations.py's own docstring and docs/DEFERRED.md) -- crossing a
MOMENTUM parent with a BOLLINGER parent would mean picking arbitrarily
between fast_window and lookback_window, which are not comparable
quantities. Returns None for that case rather than forcing a meaningless
combination.

`StrategySpec.parent_id`/`core.db.Experiment.parent_experiment_id` are
single-parent by schema (no migration this prompt): the fitter parent
becomes `parent_id`; the second parent's identity is recorded inside
`change_set["secondary_parent_id"]` so lineage isn't silently lost, just
not first-class-queryable via `experiments/lineage.py`'s existing
ancestor/descendant CTEs (which only ever follow one parent edge) --
documented here, not hidden.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from prometheus.strategy.spec import StrategySpec


@dataclass(frozen=True)
class CrossoverResult:
    child: StrategySpec
    change_set: dict[str, Any]
    hypothesis: str


def crossover(
    parent_a: StrategySpec,
    parent_a_score: float | None,
    parent_b: StrategySpec,
    parent_b_score: float | None,
    rng: random.Random,
) -> CrossoverResult | None:
    """For each of the family's own parameter fields, independently pick
    parent A's value, parent B's value, or their average -- a real,
    seeded recombination, not a fixed 50/50 split (which would make every
    crossover of the same pair produce the same handful of children).
    The fitter parent (by the caller-supplied score; ties favor A) is
    `parent_id`; retries a bounded number of times if a particular
    recombination is invalid under the family's own validator (e.g.
    exit_window ending up >= breakout_window)."""
    if parent_a.family != parent_b.family:
        return None
    if parent_a.symbol != parent_b.symbol or parent_a.timeframe != parent_b.timeframe:
        return None

    fitter, other = (
        (parent_a, parent_b)
        if (parent_a_score or 0.0) >= (parent_b_score or 0.0)
        else (parent_b, parent_a)
    )

    fields = list(fitter.parameters.keys())
    for _attempt in range(5):
        updates: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for field in fields:
            a_val, b_val = getattr(parent_a, field), getattr(parent_b, field)
            is_int = isinstance(a_val, int)
            choice = rng.choice(("a", "b", "avg"))
            if choice == "a":
                updates[field] = a_val
            elif choice == "b":
                updates[field] = b_val
            else:
                avg = (a_val + b_val) / 2
                updates[field] = round(avg) if is_int else round(avg, 4)
            sources[field] = choice

        try:
            child = fitter.with_updates(
                **updates,
                parent_id=fitter.config_hash(),
                source="crossover",
            )
        except Exception:
            continue

        change_set = {
            "mutation_type": "CROSSOVER",
            "field_sources": sources,
            "secondary_parent_id": other.config_hash(),
        }
        hypothesis = (
            f"Combining {parent_a.family} parents "
            f"{parent_a.config_hash()[:8]} and {parent_b.config_hash()[:8]} "
            f"may inherit the best of both"
        )
        return CrossoverResult(child=child, change_set=change_set, hypothesis=hypothesis)
    return None

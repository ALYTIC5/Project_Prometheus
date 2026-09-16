"""experiments/ablation.py -- pairwise_interactions/triple_interactions.
Real, tested composition machinery -- exercised with synthetic no-op
component functions since no second real production component is
registered yet (docs/DEFERRED.md: nothing to interact with the baseline
until Prompt 7/9). No DB needed: these functions only compose callables."""
from __future__ import annotations

import random

from prometheus.experiments.ablation import pairwise_interactions, triple_interactions


def _add_one(bars: object, spec: object, positions: list[float], rng: random.Random) -> list[float]:
    return [p + 1.0 for p in positions]


def _double(bars: object, spec: object, positions: list[float], rng: random.Random) -> list[float]:
    return [p * 2.0 for p in positions]


def _negate(bars: object, spec: object, positions: list[float], rng: random.Random) -> list[float]:
    return [-p for p in positions]


def test_pairwise_interactions_covers_every_2_combination() -> None:
    components = {"add_one": _add_one, "double": _double, "negate": _negate}
    combined = pairwise_interactions(components)
    assert set(combined.keys()) == {
        ("add_one", "double"),
        ("add_one", "negate"),
        ("double", "negate"),
    }


def test_pairwise_interactions_composes_in_order() -> None:
    components = {"add_one": _add_one, "double": _double}
    combined = pairwise_interactions(components)
    fn = combined[("add_one", "double")]
    # (1 + 1) * 2 = 4, applied in the order the key names them.
    result = fn(None, None, [1.0, 2.0], random.Random(0))
    assert result == [4.0, 6.0]


def test_triple_interactions_covers_the_only_3_combination() -> None:
    components = {"add_one": _add_one, "double": _double, "negate": _negate}
    combined = triple_interactions(components)
    assert set(combined.keys()) == {("add_one", "double", "negate")}


def test_triple_interactions_composes_all_three_in_order() -> None:
    components = {"add_one": _add_one, "double": _double, "negate": _negate}
    combined = triple_interactions(components)
    fn = combined[("add_one", "double", "negate")]
    # -((1 + 1) * 2) = -4
    result = fn(None, None, [1.0], random.Random(0))
    assert result == [-4.0]


def test_each_composed_function_is_independent_not_sharing_closure_state() -> None:
    """A real risk with a naive loop-variable closure: every combination
    accidentally using the LAST pair/triple instead of its own. This
    proves each key's function actually applies its OWN two/three
    components, not whichever were bound last."""
    components = {"add_one": _add_one, "double": _double, "negate": _negate}
    combined = pairwise_interactions(components)
    add_double = combined[("add_one", "double")](None, None, [1.0], random.Random(0))
    add_negate = combined[("add_one", "negate")](None, None, [1.0], random.Random(0))
    assert add_double != add_negate
    assert add_double == [4.0]  # (1+1)*2
    assert add_negate == [-2.0]  # -(1+1)

"""Pure-logic tests for prometheus.api.routes.strategies._mutation_label --
no DB needed. The "live activity" dashboard view reads this to show
"tune fast_window" / "swap family" / "crossover" / "LLM hypothesis" next
to a strategy instead of a raw change_set blob."""
from __future__ import annotations

from prometheus.api.routes.strategies import _mutation_label


def test_no_change_set_has_no_label() -> None:
    assert _mutation_label(None) is None
    assert _mutation_label({}) is None


def test_parameter_tune_names_the_field() -> None:
    change_set = {
        "mutation_type": "PARAMETER_TUNE", "field": "fast_window", "old_value": 5, "new_value": 6,
    }
    assert _mutation_label(change_set) == "tune fast_window"


def test_swap_family_label() -> None:
    change_set = {
        "mutation_type": "SWAP_FAMILY", "field": "family",
        "old_value": "MOMENTUM", "new_value": "BOLLINGER",
    }
    assert _mutation_label(change_set) == "swap family"


def test_crossover_label() -> None:
    assert _mutation_label({"mutation_type": "CROSSOVER"}) == "crossover"


def test_llm_hypothesis_label() -> None:
    assert _mutation_label({"mutation_type": "LLM_HYPOTHESIS"}) == "LLM hypothesis"


def test_unknown_mutation_type_has_no_label() -> None:
    """An honest 'no label' for a mutation_type this dashboard doesn't
    know about yet, not a crash -- future mutation kinds degrade
    gracefully rather than breaking the whole strategies endpoint."""
    assert _mutation_label({"mutation_type": "SOMETHING_NEW"}) is None


def test_non_string_mutation_type_has_no_label() -> None:
    assert _mutation_label({"mutation_type": 123}) is None

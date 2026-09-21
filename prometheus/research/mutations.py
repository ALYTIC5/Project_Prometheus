"""Typed mutation operators -- PROMPT 7. Operates on `StrategySpec`'s REAL
fields only. PROMPTS.md names six operator kinds; four of them (add/remove
filter, change sizing, change rebalance, add vol targeting) need fields
`StrategySpec` deliberately doesn't have -- `strategy/spec.py`'s own
docstring already defers that whole DSL surface to Prompt 9. Building
fake filter/sizing fields with no consumer would be exactly the
decorative scaffolding CLAUDE.md's engineering rules forbid (see
docs/DEFERRED.md).

Two real operators built:
- PARAMETER_TUNE: nudge one of the spec's own numeric fields.
- SWAP_FAMILY: the real analogue of "swap indicator" -- change the
  family entirely.

Every mutation records a structured `change_set` (mutation_type, field,
old_value, new_value) and a `hypothesis` string --
`experiments/lineage.py`'s `generation_diffs`/`improving_changes` already
read `change_set.get("predicted_direction")` to score whether a mutation
did what it claimed; this module is lineage's first real producer of
that key.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from prometheus.strategy.spec import FAMILIES, StrategySpec

# How far a parameter tune nudges a field, as a fraction of its current
# value -- a real, bounded range (not "invent any delta"), wide enough to
# actually explore, narrow enough that a mutation is still recognizably
# related to its parent (a tune that's 10x the parent isn't a tune, it's
# a different strategy wearing the same lineage).
_TUNE_FRACTION_RANGE = (0.10, 0.35)

# Fields where a LONGER window is a real, citable, domain-grounded
# hypothesis about drawdown specifically (longer averaging/wider bands
# smooth out whipsaw-driven false signals -- standard technical-analysis
# reasoning, not invented): predicted_direction is only ever populated
# for these fields, on the MAX_DRAWDOWN_PCT metric lineage.py already
# supports. Fields not in this set (e.g. Bollinger's own entry threshold
# has no such directional claim) get no predicted_direction -- an honest
# "no hypothesis" rather than a fabricated one.
_SMOOTHING_FIELDS = {
    "slow_window", "fast_window", "lookback_window", "breakout_window",
    "exit_window", "band_multiplier", "rsi_lookback", "macd_fast",
    "macd_slow", "macd_signal", "rf_train_window", "gb_train_window",
    "lr_train_window", "svm_train_window", "stoch_lookback",
    "keltner_lookback", "keltner_multiplier", "williams_lookback",
    "cci_lookback", "ao_fast", "ao_slow", "supertrend_lookback",
    "supertrend_multiplier", "trix_lookback",
}


@dataclass(frozen=True)
class Mutation:
    child: StrategySpec
    change_set: dict[str, Any]
    hypothesis: str


# Every *_predict_threshold field (RANDOM_FOREST/GRADIENT_BOOSTING/
# LOGISTIC_REGRESSION/SVM all share this shape) has its entire valid
# range (see spec.py's model_validator: 0.0 < x < 1.0) below
# _clamp_positive's own floor of 1.0 -- every other field's valid range
# starts at or above 1 (a window/lookback of at least 1 bar). Both
# clamp bounds are exclusive to stay strictly inside the validator's own
# open interval.
_UNIT_INTERVAL_FIELDS = {
    "rf_predict_threshold", "gb_predict_threshold", "lr_predict_threshold",
    "svm_predict_threshold",
}
_UNIT_INTERVAL_MIN = 0.01
_UNIT_INTERVAL_MAX = 0.99


def _clamp_positive(value: float, *, is_int: bool, field: str | None = None) -> float:
    if field in _UNIT_INTERVAL_FIELDS:
        value = min(max(value, _UNIT_INTERVAL_MIN), _UNIT_INTERVAL_MAX)
        return round(value) if is_int else round(value, 4)
    value = max(value, 1.0)
    return round(value) if is_int else round(value, 4)


def parameter_tune(spec: StrategySpec, rng: random.Random) -> Mutation | None:
    """Nudge one of the spec's own family-specific numeric fields by a
    random fraction. Retries a bounded number of times if the nudge
    produces an invalid spec under the family's own model_validator
    (e.g. slow_window <= fast_window) -- returns None only if every
    attempt fails, an honest "no valid mutation found this time" rather
    than forcing an invalid one through."""
    fields = list(spec.parameters.keys())
    field = rng.choice(fields)
    old_value = getattr(spec, field)
    is_int = isinstance(old_value, int)

    for _attempt in range(5):
        fraction = rng.uniform(*_TUNE_FRACTION_RANGE)
        direction = rng.choice([1, -1])
        new_value = _clamp_positive(
            old_value * (1 + direction * fraction), is_int=is_int, field=field
        )
        if new_value == old_value:
            continue
        try:
            child = spec.with_updates(
                **{field: new_value}, parent_id=spec.config_hash(), source="mutation"
            )
        except Exception:
            continue

        predicted_direction = None
        if field in _SMOOTHING_FIELDS:
            # Longer window / wider band -> smoother signal -> predicted
            # LOWER drawdown; shorter/narrower -> predicted HIGHER
            # drawdown. Real, citable TA reasoning, scoped to the one
            # metric (MAX_DRAWDOWN_PCT) lineage.py actually supports.
            predicted_direction = "DECREASE" if new_value > old_value else "INCREASE"

        change_set = {
            "mutation_type": "PARAMETER_TUNE",
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        }
        if predicted_direction is not None:
            change_set["predicted_direction"] = predicted_direction
            change_set["predicted_metric"] = "MAX_DRAWDOWN_PCT"

        hypothesis = (
            f"Changing {field} from {old_value} to {new_value} "
            f"{'smooths the signal' if new_value > old_value else 'sharpens the signal'}"
        )
        return Mutation(child=child, change_set=change_set, hypothesis=hypothesis)
    return None


def swap_family(
    spec: StrategySpec, rng: random.Random, *, seed_specs_by_family: dict[str, list[StrategySpec]]
) -> Mutation | None:
    """The real analogue of "swap indicator": replace the spec's family
    (and therefore its whole parameter set -- MOMENTUM's fast/slow don't
    mean anything for BOLLINGER) with a randomly-chosen spec from a
    DIFFERENT family's own template set. `seed_specs_by_family` is
    caller-supplied (research/templates.py's real templates, or a
    baseline grid) rather than this module inventing new default
    parameters for a family it isn't otherwise responsible for.

    No predicted_direction: comparing fundamentally different signal
    types has no principled directional hypothesis to state, and stating
    one anyway would be exactly the kind of invented claim CLAUDE.md
    warns against. lineage.py's own `change_set.get("predicted_direction")`
    already handles a missing key as "no hypothesis" (None), not an error.

    A spec whose OWN family isn't in FAMILIES (the ML components --
    RANDOM_FOREST, GRADIENT_BOOSTING, LOGISTIC_REGRESSION, SVM --
    deliberately excluded, see spec.py) has no valid swap target:
    FAMILIES is the baseline-family ecosystem this operator swaps
    within, and no ML component must ever be reached by it, in either
    direction (inbound as `new_family`, or outbound as the source
    `spec.family` being replaced away from).
    """
    if spec.family not in FAMILIES:
        return None
    other_families = [f for f in FAMILIES if f != spec.family and seed_specs_by_family.get(f)]
    if not other_families:
        return None
    new_family = rng.choice(other_families)
    template = rng.choice(seed_specs_by_family[new_family])

    child = template.with_updates(
        symbol=spec.symbol,
        timeframe=spec.timeframe,
        parent_id=spec.config_hash(),
        source="mutation",
    )
    change_set = {
        "mutation_type": "SWAP_FAMILY",
        "field": "family",
        "old_value": spec.family,
        "new_value": new_family,
    }
    hypothesis = f"Swapping family from {spec.family} to {new_family} may find a different edge"
    return Mutation(child=child, change_set=change_set, hypothesis=hypothesis)

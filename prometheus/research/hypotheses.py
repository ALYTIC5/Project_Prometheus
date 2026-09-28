"""prometheus/research/hypotheses.py -- pre-registration (Phase 3).

Every spec is registered as a hypothesis before the job that backtests it
exists: its mechanism, the prediction (it beats its matched buy-and-hold),
the frozen parameter point, the benchmark universe and the generator's
prior probability of passing the discovery gate. The first registration of
a config_hash is final.

Priors (user decision 2026-09-28): deterministic generators use Laplace's
rule of succession on their own gate record, (d + 1) / (n + 2); an LLM
hypothesis carries the probability the model stated.

Near-duplicate (user decision): same family, symbol/universe and timeframe
as an existing hypothesis with every parameter within one step (+/-1 for
integers, +/-5% for floats). A near-duplicate still runs, at the lowest
priority, but can never be a discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.strategy.mechanisms import canonical_mechanism, mechanism_class
from prometheus.strategy.rotation_spec import _IDENTITY_FIELDS as ROTATION_IDENTITY_FIELDS
from prometheus.strategy.rotation_spec import RotationSpec
from prometheus.strategy.spec import _IDENTITY_FIELDS as STRATEGY_IDENTITY_FIELDS
from prometheus.strategy.spec import StrategySpec

PREDICTED_DIRECTION = "BEATS_MATCHED_BENCHMARK"
# Every generator enqueues at priority 0; a near-duplicate goes below all of
# them (queue.claim orders by priority DESC).
NEAR_DUPLICATE_PRIORITY = -1
_FLOAT_STEP = 0.05
# The parameter point is the spec's behavioural identity (what config_hash
# covers) minus the fields that already place it: family, symbol/universe,
# timeframe.
_PLACEMENT_FIELDS = frozenset({"family", "symbol", "universe", "timeframe"})


@dataclass(frozen=True)
class Registration:
    hypothesis_id: int
    created: bool
    near_duplicate_of: str | None
    prior_probability: float


def spec_parameters(spec: StrategySpec | RotationSpec) -> dict[str, Any]:
    identity = (
        STRATEGY_IDENTITY_FIELDS if isinstance(spec, StrategySpec) else ROTATION_IDENTITY_FIELDS
    )
    return {
        field: value
        for field, value in spec.model_dump(mode="json", include=set(identity)).items()
        if field not in _PLACEMENT_FIELDS and value is not None
    }


def _spec_symbol(spec: StrategySpec | RotationSpec) -> str | None:
    return spec.symbol if isinstance(spec, StrategySpec) else None


def benchmark_of(spec: StrategySpec | RotationSpec) -> dict[str, Any]:
    universe = [spec.symbol] if isinstance(spec, StrategySpec) else sorted(spec.universe)
    return {"kind": "buy_and_hold_equal_weight", "universe": universe}


def near_duplicate_among(
    spec: StrategySpec | RotationSpec, others: list[StrategySpec | RotationSpec]
) -> bool:
    """Pure form of the registration check, for tests and generators."""
    params, bench = spec_parameters(spec), benchmark_of(spec)
    return any(
        other.family == spec.family
        and other.timeframe == spec.timeframe
        and benchmark_of(other) == bench
        and is_one_step_neighbour(params, spec_parameters(other))
        for other in others
    )


def is_one_step_neighbour(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.keys() != b.keys() or a == b:
        return False
    for key, x in a.items():
        y = b[key]
        if isinstance(x, bool) or isinstance(y, bool):
            if x != y:
                return False
        elif isinstance(x, int) and isinstance(y, int):
            if abs(x - y) > 1:
                return False
        elif isinstance(x, int | float) and isinstance(y, int | float):
            scale = max(abs(float(x)), abs(float(y)))
            if abs(float(x) - float(y)) > _FLOAT_STEP * scale + 1e-12:
                return False
        elif x != y:
            return False
    return True


def laplace_prior(tests: int, discoveries: int) -> float:
    return (discoveries + 1) / (tests + 2)


_SELECT_EXISTING = text(
    "SELECT id, near_duplicate_of, prior_probability FROM hypotheses WHERE config_hash = :h"
)
_SELECT_STATS = text("SELECT tests, discoveries FROM hypothesis_gate_stats WHERE source = :s")
_SELECT_SIBLINGS = text(
    """
    SELECT config_hash, parameters, benchmark FROM hypotheses
     WHERE family = :family AND timeframe = :timeframe
       AND symbol IS NOT DISTINCT FROM :symbol
    """
)
_INSERT = text(
    """
    INSERT INTO hypotheses
        (config_hash, source, family, symbol, timeframe, parent_config_hash, mechanism,
         mechanism_class, predicted_direction, predicted_effect, predicted_horizon,
         parameters, benchmark, prior_probability, prior_basis, near_duplicate_of,
         mechanism_aligned, claim_ids)
    VALUES
        (:config_hash, :source, :family, :symbol, :timeframe, :parent_config_hash, :mechanism,
         :mechanism_class, :predicted_direction, :predicted_effect, :predicted_horizon,
         :parameters, :benchmark, :prior_probability, :prior_basis, :near_duplicate_of,
         :mechanism_aligned, :claim_ids)
    ON CONFLICT (config_hash) DO NOTHING
    RETURNING id
    """
).bindparams(
    bindparam("parameters", type_=JSONB),
    bindparam("benchmark", type_=JSONB),
    bindparam("claim_ids", type_=JSONB),
)


@dataclass(frozen=True)
class HypothesisRecord:
    hypothesis_id: int
    source: str
    prior_probability: float
    near_duplicate_of: str | None
    mechanism_aligned: bool


_SELECT_RECORD = text(
    """
    SELECT id, source, prior_probability, near_duplicate_of, mechanism_aligned
      FROM hypotheses WHERE config_hash = :h
    """
)


async def registered_hypothesis(session: AsyncSession, config_hash: str) -> HypothesisRecord | None:
    row = (await session.execute(_SELECT_RECORD, {"h": config_hash})).first()
    if row is None:
        return None
    return HypothesisRecord(
        int(row.id), row.source, float(row.prior_probability), row.near_duplicate_of,
        bool(row.mechanism_aligned),
    )


async def register_hypothesis(
    session: AsyncSession,
    spec: StrategySpec | RotationSpec,
    *,
    parent_config_hash: str | None = None,
    stated_prior: float | None = None,
    stated_mechanism: str | None = None,
    mechanism_family: str | None = None,
    predicted_effect: str | None = None,
    claim_ids: list[int] | None = None,
) -> Registration:
    """Registers `spec` unless it already is. `stated_prior`/`stated_mechanism`
    come from an LLM hypothesis; `mechanism_family` is the family the claim
    itself pointed at (MECHANISM_MISMATCH when its class differs from the
    spec's). Does not commit."""
    config_hash = spec.config_hash()
    existing = (await session.execute(_SELECT_EXISTING, {"h": config_hash})).first()
    if existing is not None:
        return Registration(
            existing.id, False, existing.near_duplicate_of, existing.prior_probability
        )

    if stated_prior is not None:
        prior, basis = stated_prior, "llm_stated"
    else:
        stats = (await session.execute(_SELECT_STATS, {"s": spec.source})).first()
        tests = int(stats.tests) if stats else 0
        discoveries = int(stats.discoveries) if stats else 0
        prior, basis = laplace_prior(tests, discoveries), f"laplace:{discoveries}/{tests}"

    parameters = spec_parameters(spec)
    benchmark = benchmark_of(spec)
    near_duplicate_of = None
    for sibling in (
        await session.execute(
            _SELECT_SIBLINGS,
            {"family": spec.family, "timeframe": spec.timeframe, "symbol": _spec_symbol(spec)},
        )
    ).all():
        if sibling.benchmark == benchmark and is_one_step_neighbour(parameters, sibling.parameters):
            near_duplicate_of = sibling.config_hash
            break

    spec_class = mechanism_class(spec.family)
    aligned = mechanism_family is None or mechanism_class(mechanism_family) == spec_class
    inserted = (
        await session.execute(
            _INSERT,
            {
                "config_hash": config_hash,
                "source": spec.source,
                "family": spec.family,
                "symbol": _spec_symbol(spec),
                "timeframe": spec.timeframe,
                "parent_config_hash": parent_config_hash,
                "mechanism": stated_mechanism or canonical_mechanism(spec.family),
                "mechanism_class": spec_class,
                "predicted_direction": PREDICTED_DIRECTION,
                "predicted_effect": predicted_effect,
                "predicted_horizon": spec.expected_horizon,
                "parameters": parameters,
                "benchmark": benchmark,
                "prior_probability": prior,
                "prior_basis": basis,
                "near_duplicate_of": near_duplicate_of,
                "mechanism_aligned": aligned,
                "claim_ids": claim_ids,
            },
        )
    ).scalar_one_or_none()
    if inserted is None:  # a concurrent registration won the race
        row = (await session.execute(_SELECT_EXISTING, {"h": config_hash})).one()
        return Registration(row.id, False, row.near_duplicate_of, row.prior_probability)
    return Registration(int(inserted), True, near_duplicate_of, prior)

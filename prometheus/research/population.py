"""Population selection -- PROMPT 7's selection modes for evolution.

Read-only. Law 9: research code sees the population only through the
breedable_strategies / breedable_scores views (migration 0024), which
exclude canaries inside the view. Status writes, verdict mapping and
champion election are judging decisions and live in
validation/promotion.py and validation/status.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BindParameter

from prometheus.strategy.rotation_spec import ROTATION_FAMILIES
from prometheus.strategy.spec import StrategySpec

# The full, real lifecycle -- used to validate inputs/outputs elsewhere
# (e.g. a status column write that isn't one of these is a bug, not a
# new state quietly introduced).
STRATEGY_STATES = (
    "CHAMPION",
    "VALIDATED",
    "PROMISING",
    "EXPERIMENTAL",
    "REGIME_SPECIALIST",
    "DORMANT",
    "QUARANTINED",
    "REJECTED",
    "RETIRED",
)


@dataclass(frozen=True)
class PopulationCandidate:
    strategy_id: str
    family: str
    spec: StrategySpec
    status: str
    score: float | None



# C1 (final-review fix wave): every selector in this module parses each
# row's `spec` JSON with StrategySpec.model_validate(). The `strategies`
# table is shared: experiments.runner.run_one inserts RotationSpec rows
# into it too, and a RotationSpec's dumped JSON has no `symbol` and
# carries `universe`/`top_n`/`rebalance_frequency_days` instead, so
# StrategySpec (extra="forbid", symbol required) raises ValidationError
# on one. That is not merely a parse failure to catch: the exception
# escaping select_for_exploration inside worker.py's
# _run_evolution_step propagates out of _run_research before
# mark_run(concern="research") can fire, leaving the research concern
# permanently "due" -- re-running and re-failing on every tick forever.
#
# Excluding rotation rows from these selectors is the correct
# SEMANTICS, not a workaround: every one of them exists to feed
# mutation/crossover of a single-symbol technical-indicator parameter
# vector (research/mutations.py, research/crossover.py), and a
# RotationSpec has no such vector -- "tune fast_window by one step" has
# no meaning for a universe-ranking spec. They are genuinely not
# candidates, so they are filtered in SQL rather than parsed and
# discarded.
_ROTATION_FAMILIES_ARG: dict[str, list[str]] = {"rotation_families": list(ROTATION_FAMILIES)}


def _rotation_families_param() -> BindParameter[str]:
    """A fresh expanding bindparam per query -- `expanding=True` is how
    SQLAlchemy safely binds a Python list against an IN clause, the same
    mechanism api/routes/strategies.py's _SELECT_ASSET_CLASS_BY_SYMBOL
    already uses."""
    return bindparam("rotation_families", expanding=True)


_SELECT_FOR_EXPLOITATION = text(
    """
    SELECT s.id, s.family, s.spec, s.status, ls.score
      FROM breedable_strategies s
      LEFT JOIN breedable_scores ls ON ls.strategy_id = s.id
     WHERE s.status IN ('VALIDATED', 'CHAMPION')
       AND s.family NOT IN :rotation_families
     ORDER BY ls.score DESC NULLS LAST
     LIMIT :limit
    """
).bindparams(_rotation_families_param())


async def select_for_exploitation(
    session: AsyncSession, *, limit: int
) -> list[PopulationCandidate]:
    """Best-scoring VALIDATED/CHAMPION strategies -- refine what's
    already working. `validation_results.strategy_fingerprint` is
    `StrategySpec.config_hash()`, not `strategies.id` -- joined here via
    the spec's own recomputed hash, matching how validate_grid itself
    looks up a spec's latest evidence."""
    rows = (
        await session.execute(
            _SELECT_FOR_EXPLOITATION, {"limit": limit, **_ROTATION_FAMILIES_ARG}
        )
    ).fetchall()
    return [
        PopulationCandidate(
            strategy_id=r.id,
            family=r.family,
            spec=StrategySpec.model_validate(r.spec),
            status=r.status,
            score=r.score,
        )
        for r in rows
    ]


_SELECT_FOR_EXPLORATION = text(
    "SELECT id, family, spec, status FROM breedable_strategies "
    "WHERE family NOT IN :rotation_families ORDER BY random() LIMIT :limit"
).bindparams(_rotation_families_param())


async def select_for_exploration(session: AsyncSession, *, limit: int) -> list[PopulationCandidate]:
    """A uniform random sample across the whole mutable population, any
    status, any single-symbol family -- encourages coverage of
    parameter/family space rather than only refining known-good regions.
    Rotation families are excluded (see the C1 note above): they have no
    mutable parameter vector for this sample to feed."""
    rows = (
        await session.execute(
            _SELECT_FOR_EXPLORATION, {"limit": limit, **_ROTATION_FAMILIES_ARG}
        )
    ).fetchall()
    return [
        PopulationCandidate(
            strategy_id=r.id, family=r.family, spec=StrategySpec.model_validate(r.spec),
            status=r.status, score=None,
        )
        for r in rows
    ]


_SELECT_ALL_FOR_DIVERSIFICATION = text(
    "SELECT id, family, spec, status FROM breedable_strategies "
    "WHERE family NOT IN :rotation_families"
).bindparams(_rotation_families_param())


async def select_for_diversification(
    session: AsyncSession, *, limit: int
) -> list[PopulationCandidate]:
    """Strategies whose own normalized parameter vector is FARTHEST from
    the current population's centroid, per family (comparing across
    families is meaningless -- different parameter spaces entirely).
    Real, derived selection (distance from the population's own actual
    center), not an arbitrary novelty score."""
    rows = (
        await session.execute(_SELECT_ALL_FOR_DIVERSIFICATION, _ROTATION_FAMILIES_ARG)
    ).fetchall()
    by_family: dict[str, list[tuple[str, str, StrategySpec, dict[str, float]]]] = {}
    for r in rows:
        spec = StrategySpec.model_validate(r.spec)
        by_family.setdefault(spec.family, []).append((r.id, r.status, spec, spec.parameters))

    candidates: list[tuple[float, PopulationCandidate]] = []
    for family, entries in by_family.items():
        if len(entries) < 2:
            continue
        fields = sorted(entries[0][3].keys())
        vectors = {sid: [params[f] for f in fields] for sid, _status, _spec, params in entries}
        mins = [min(v[i] for v in vectors.values()) for i in range(len(fields))]
        maxs = [max(v[i] for v in vectors.values()) for i in range(len(fields))]
        spans = [(maxs[i] - mins[i]) or 1.0 for i in range(len(fields))]
        normalized = {
            sid: [(v[i] - mins[i]) / spans[i] for i in range(len(fields))]
            for sid, v in vectors.items()
        }
        centroid = [
            sum(normalized[sid][i] for sid in normalized) / len(normalized)
            for i in range(len(fields))
        ]
        for sid, status, spec, _params in entries:
            dist = sum((normalized[sid][i] - centroid[i]) ** 2 for i in range(len(fields))) ** 0.5
            candidates.append(
                (
                    dist,
                    PopulationCandidate(
                        strategy_id=sid, family=family, spec=spec, status=status, score=None
                    ),
                )
            )

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [candidate for _dist, candidate in candidates[:limit]]


_SELECT_FOR_REVIVAL = text(
    """
    SELECT id, family, spec, status FROM breedable_strategies
     WHERE status IN ('DORMANT', 'QUARANTINED')
       AND family NOT IN :rotation_families
     ORDER BY created_at ASC
     LIMIT :limit
    """
).bindparams(_rotation_families_param())


async def select_for_revival(session: AsyncSession, *, limit: int) -> list[PopulationCandidate]:
    """DORMANT/QUARANTINED strategies, oldest first -- give a strategy
    that was held (not rejected) another look as more data accumulates,
    rather than leaving it permanently ignored."""
    rows = (
        await session.execute(_SELECT_FOR_REVIVAL, {"limit": limit, **_ROTATION_FAMILIES_ARG})
    ).fetchall()
    return [
        PopulationCandidate(
            strategy_id=r.id, family=r.family, spec=StrategySpec.model_validate(r.spec),
            status=r.status, score=None,
        )
        for r in rows
    ]


_SELECT_FOR_CROSS_BREEDING = text(
    """
    SELECT s.id, s.family, s.spec, s.status, ls.score
      FROM breedable_strategies s
      LEFT JOIN breedable_scores ls ON ls.strategy_id = s.id
     WHERE s.family = :family AND s.status IN ('VALIDATED', 'CHAMPION', 'PROMISING')
       AND s.family NOT IN :rotation_families
     ORDER BY ls.score DESC NULLS LAST
     LIMIT 2
    """
).bindparams(_rotation_families_param())


async def select_for_cross_breeding(
    session: AsyncSession, *, family: str
) -> tuple[PopulationCandidate, PopulationCandidate] | None:
    """The two best-scoring same-family candidates -- crossover.py needs
    a shared parameter space, which only exists within one family.
    Returns None if fewer than two real candidates exist for this family
    yet (an honest "not enough population" result, not a fabricated
    pair). The rotation-family exclusion is belt-and-braces here (every
    caller passes a member of spec.FAMILIES, which never contains a
    rotation family) but keeps the guarantee local to the query rather
    than resting on every present and future caller's discipline."""
    rows = (
        await session.execute(
            _SELECT_FOR_CROSS_BREEDING, {"family": family, **_ROTATION_FAMILIES_ARG}
        )
    ).fetchall()
    if len(rows) < 2:
        return None
    candidates = [
        PopulationCandidate(
            strategy_id=r.id, family=r.family, spec=StrategySpec.model_validate(r.spec),
            status=r.status, score=r.score,
        )
        for r in rows
    ]
    return candidates[0], candidates[1]

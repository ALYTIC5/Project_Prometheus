"""Population management -- PROMPT 7. CHAMPION / PROMISING / EXPERIMENTAL /
REGIME_SPECIALIST / DORMANT / QUARANTINED / REJECTED / RETIRED. Nothing is
ever hard-deleted: every function here only SELECTs or UPDATEs `strategies.
status` (mutable by design, see core.db.Strategy's own docstring) -- no
DELETE anywhere in this module.

The mapping below is not a second, invented state machine: PROMPT 5's
`validation.decision.Verdict` (PROMOTE/PROMISING/CONTINUE_RESEARCH/
REGIME_SPECIALIST/DORMANT/QUARANTINE/REJECT/RETIRE) already IS almost
exactly this lifecycle -- `experiments.runner._validate_one_spec` computes
one of these 8 verdicts every validation cycle today, but only ever acts
on the PROMOTE branch (writing `status = "VALIDATED"`); the other 7 are
silently discarded. `verdict_to_status` is the missing mapping, used for
EVERY verdict, not a parallel implementation.

CHAMPION is deliberately NOT what PROMOTE writes -- the frontend's own
`StrategyState` union (frontend/src/mapping/stateToVisual.ts) already
treats VALIDATED and CHAMPION as distinct states, and a "champion" here
means something more specific: the single best-scoring VALIDATED
strategy PER FAMILY (a real, derived count -- one per family, not an
arbitrary top-N -- see `elect_champions`), not every strategy that
clears the Oracle's bar.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BindParameter

from prometheus.strategy.rotation_spec import ROTATION_FAMILIES
from prometheus.strategy.spec import FAMILIES, StrategySpec

_VERDICT_TO_STATUS: dict[str, str] = {
    "PROMOTE": "VALIDATED",
    "PROMISING": "PROMISING",
    "CONTINUE_RESEARCH": "EXPERIMENTAL",
    "REGIME_SPECIALIST": "REGIME_SPECIALIST",
    "DORMANT": "DORMANT",
    "QUARANTINE": "QUARANTINED",
    "REJECT": "REJECTED",
    "RETIRE": "RETIRED",
}

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


def verdict_to_status(verdict: str) -> str:
    """The canonical, single source of truth for verdict -> strategies.
    status. Raises on an unknown verdict rather than silently defaulting
    -- a new Verdict member added to validation/decision.py without a
    corresponding entry here is a real gap, not something to paper over."""
    try:
        return _VERDICT_TO_STATUS[verdict]
    except KeyError:
        raise ValueError(f"no status mapping for verdict {verdict!r}") from None


@dataclass(frozen=True)
class PopulationCandidate:
    strategy_id: str
    family: str
    spec: StrategySpec
    status: str
    score: float | None


# `validation_results.strategy_fingerprint` is `StrategySpec.config_hash()`
# (a sha256 hex string), NOT `strategies.id` (a "FAMILY-NNN" id) -- these
# are different identifiers. The real join path is strategies -> its
# latest experiment (`experiments.strategy_id`) -> that experiment's own
# `config_hash` column (populated by `run_one` as `spec.config_hash()`,
# the exact same value `_validate_one_spec` uses as `strategy_fingerprint`)
# -> the latest validation_results row for that fingerprint. Reused as a
# CTE by every query below that needs a strategy's current score.
_LATEST_FINGERPRINT_CTE = """
    latest_experiment AS (
        SELECT DISTINCT ON (strategy_id) strategy_id, config_hash
          FROM experiments
         WHERE strategy_id IS NOT NULL
         ORDER BY strategy_id, created_at DESC
    ),
    latest_score AS (
        SELECT le.strategy_id, vr.score
          FROM latest_experiment le
          JOIN LATERAL (
              SELECT score FROM validation_results
               WHERE strategy_fingerprint = le.config_hash
               ORDER BY created_at DESC LIMIT 1
          ) vr ON true
    )
"""

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
    f"""
    WITH {_LATEST_FINGERPRINT_CTE}
    SELECT s.id, s.family, s.spec, s.status, ls.score
      FROM strategies s
      LEFT JOIN latest_score ls ON ls.strategy_id = s.id
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
    "SELECT id, family, spec, status FROM strategies "
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
    "SELECT id, family, spec, status FROM strategies WHERE family NOT IN :rotation_families"
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
    SELECT id, family, spec, status FROM strategies
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
    f"""
    WITH {_LATEST_FINGERPRINT_CTE}
    SELECT s.id, s.family, s.spec, s.status, ls.score
      FROM strategies s
      LEFT JOIN latest_score ls ON ls.strategy_id = s.id
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


_SELECT_BEST_VALIDATED_PER_FAMILY = text(
    f"""
    WITH {_LATEST_FINGERPRINT_CTE}
    SELECT DISTINCT ON (s.family) s.id
      FROM strategies s
      LEFT JOIN latest_score ls ON ls.strategy_id = s.id
     WHERE s.status = 'VALIDATED'
     ORDER BY s.family, ls.score DESC NULLS LAST
    """
)
_UPDATE_STATUS = text("UPDATE strategies SET status = :status WHERE id = :id")
_DEMOTE_STALE_CHAMPIONS = text(
    "UPDATE strategies SET status = 'VALIDATED' WHERE status = 'CHAMPION' AND id != ALL(:keep_ids)"
)


async def elect_champions(session: AsyncSession) -> list[str]:
    """One CHAMPION per family: the current best-scoring VALIDATED
    strategy. Real, derived count (one per real family, not an invented
    top-N). A family with zero VALIDATED strategies simply has no
    champion -- never fabricated. Any strategy currently CHAMPION that
    is no longer the best in its family is demoted back to VALIDATED
    (never REJECTED/RETIRED by this function -- losing the title is not
    the same as failing validation)."""
    best_ids = [
        row.id
        for row in (await session.execute(_SELECT_BEST_VALIDATED_PER_FAMILY)).fetchall()
    ]
    await session.execute(_DEMOTE_STALE_CHAMPIONS, {"keep_ids": best_ids})
    for strategy_id in best_ids:
        await session.execute(_UPDATE_STATUS, {"status": "CHAMPION", "id": strategy_id})
    return best_ids


_POPULATION_SUMMARY = text(
    "SELECT family, status, COUNT(*) AS n FROM strategies GROUP BY family, status"
)


async def population_summary(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Real `SELECT ... GROUP BY family, status` -- feeds
    `world.entities.District.population_by_status` with actual counts.
    Keys are lower-cased to match that field's own existing convention
    (already lower-cased for the 7 states it was scaffolded with)."""
    rows = (await session.execute(_POPULATION_SUMMARY)).fetchall()
    summary: dict[str, dict[str, int]] = {family: {} for family in FAMILIES}
    for row in rows:
        summary.setdefault(row.family, {})[row.status.lower()] = int(row.n)
    return summary

"""Pure function: db_state -> WorldState.

The world is a projection of database state. The frontend renders
WorldState and holds no business logic.

Key rule: NEVER raise on missing tables. If a source table doesn't
exist, the corresponding structure stays in SCAFFOLDING. Buildings
activate the moment their backing queries return real rows.

The construction_manifest in world/construction.py defines:
- which prompt builds each building
- which tables activate it
- what agent roles work there
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.population import STRATEGY_STATES, population_summary
from prometheus.world.construction import (
    BUILDING_LOCATIONS,
    CONSTRUCTION_MANIFEST,
    GOD_BY_BUILDING_KIND,
)
from prometheus.world.entities import (
    Agent,
    AgentRole,
    BenchmarkMetrics,
    ClimateState,
    ConstructionPhase,
    District,
    EntityLocation,
    LawCompliance,
    Scoreboard,
    ScoreboardVerdict,
    Structure,
    Treasury,
    WorldEntity,
    WorldEntityType,
    WorldEvent,
    WorldState,
)

LAWS: list[LawCompliance] = [
    LawCompliance(
        law_id=1,
        name="No look-ahead",
        compliant=True,
        last_violation=None,
        summary="Strategies see only data whose available_at <= decision timestamp",
    ),
    LawCompliance(
        law_id=2,
        name="No survivorship bias",
        compliant=True,
        last_violation=None,
        summary="Universe membership reconstructed as of decision date including dead symbols",
    ),
    LawCompliance(
        law_id=3,
        name="Holdout sacred",
        compliant=True,
        last_violation=None,
        summary="Final test slice is physically separated; second access = automatic REJECT",
    ),
    LawCompliance(
        law_id=4,
        name="Risk limits outside loop",
        compliant=True,
        last_violation=None,
        summary="Position size, exposure, leverage read from env at startup",
    ),
    LawCompliance(
        law_id=5,
        name="No real money, ever",
        compliant=True,
        last_violation=None,
        summary="Paper only; no code path may submit a real order",
    ),
    LawCompliance(
        law_id=6,
        name="History append-only",
        compliant=True,
        last_violation=None,
        summary="No UPDATE or DELETE on experiments/results/decisions",
    ),
    LawCompliance(
        law_id=7,
        name="Thresholds change globally",
        compliant=True,
        last_violation=None,
        summary="Validation thresholds changed only across entire experiment corpus",
    ),
    LawCompliance(
        law_id=8,
        name="Everything vs buy-and-hold",
        compliant=True,
        last_violation=None,
        summary="Every result compared against €1,000 equal-weight benchmark",
    ),
]


def determine_phase(
    structure_id: str,
    row_counts: dict[str, int],
) -> ConstructionPhase:
    """Map a structure id + observed row counts to its construction phase.

    Public because every consumer of building state (the world projection,
    /buildings, /health/ready) must agree on one answer. Nobody re-derives it.
    """
    manifest = CONSTRUCTION_MANIFEST.get(structure_id, {})
    activates_on = manifest.get("activates_on", [])
    kind = manifest.get("kind", structure_id)

    if kind == "vault":
        return ConstructionPhase.SEALED
    if kind == "monument":
        return ConstructionPhase.ACTIVE
    if kind == "watchtower":
        return ConstructionPhase.ACTIVE

    # No activation table configured means nothing can prove the building is
    # real yet, so it stays under construction. Defaulting to ACTIVE here would
    # let a future manifest entry silently claim to be finished.
    if not activates_on:
        return ConstructionPhase.SCAFFOLDING

    has_data = any(row_counts.get(table, 0) > 0 for table in activates_on)
    if has_data:
        return ConstructionPhase.ACTIVE
    return ConstructionPhase.SCAFFOLDING


def build_entities(
    structures: list[Structure],
    strategies: list[dict[str, Any]] | None = None,
    experiments: list[dict[str, Any]] | None = None,
) -> list[WorldEntity]:
    """Pure function: real DB rows -> normalized WorldEntity list.

    BUILDING (one per real structure), GOD (the 3 that stand at a real
    building), HERO (one per real `strategies` row, Prompt 4), and
    EXPERIMENT (one per real `experiments` row, Prompt 4) are populated.
    Every other WorldEntityType (TEMPLE/AGENT/ARENA_MATCH/...) has no real
    backend source yet -- strategy_families and jobs do not exist -- so
    this function never emits one, matching the districts=[]/agents=[] rule.

    HERO/EXPERIMENT entities have no real per-strategy world placement yet
    (that render work is separate, later, and not fabricated here) -- they
    anchor at the Forge/Arena's real location respectively, since that is
    where a strategy is genuinely generated/compared, not an arbitrary point.
    """
    entities: list[WorldEntity] = []

    for structure in structures:
        loc = BUILDING_LOCATIONS.get(structure.id, {})
        entities.append(
            WorldEntity(
                entity_id=f"building:{structure.id}",
                entity_type=WorldEntityType.BUILDING,
                source_entity_id=f"construction_manifest:{structure.id}",
                parent_entity_id=None,
                state=structure.construction_phase.value,
                health=1.0 if structure.construction_phase == ConstructionPhase.ACTIVE else 0.0,
                activity=structure.load,
                location=EntityLocation(
                    zone="world",
                    x=float(loc.get("x", 0)),
                    y=float(loc.get("y", 0)),
                ),
                metrics={"queue_depth": structure.queue_depth},
                reasons=[],
                evidence_refs=[],
            ),
        )

        god_name = GOD_BY_BUILDING_KIND.get(structure.kind)
        if god_name:
            entities.append(
                WorldEntity(
                    entity_id=f"god:{god_name}",
                    entity_type=WorldEntityType.GOD,
                    source_entity_id=f"construction_manifest:{structure.id}",
                    parent_entity_id=f"building:{structure.id}",
                    # A god's presence mirrors its building's real phase --
                    # borrowed verbatim from the same enum, never invented.
                    state=structure.construction_phase.value,
                    health=1.0 if structure.construction_phase == ConstructionPhase.ACTIVE else 0.0,
                    activity=0.0,
                    location=EntityLocation(
                        zone="world",
                        x=float(loc.get("x", 0)),
                        y=float(loc.get("y", 0)),
                    ),
                    metrics={},
                    reasons=[],
                    evidence_refs=[],
                ),
            )

    forge_loc = BUILDING_LOCATIONS.get("forge", {})
    forge_xy = (
        float(forge_loc.get("x", 0)) + float(forge_loc.get("width", 1)) / 2,
        float(forge_loc.get("y", 0)) + float(forge_loc.get("height", 1)) / 2,
    )
    for strategy in strategies or []:
        entities.append(
            WorldEntity(
                entity_id=f"hero:{strategy['id']}",
                entity_type=WorldEntityType.HERO,
                source_entity_id=f"strategy:{strategy['id']}",
                parent_entity_id=f"family:{strategy['family']}",
                # Real status, verbatim -- PROMISING/REJECTED, matching
                # frontend/src/mapping/stateToVisual.ts's StrategyState.
                state=strategy["status"],
                health=0.0,
                activity=0.0,
                location=EntityLocation(zone="world", x=forge_xy[0], y=forge_xy[1]),
                metrics={},
                reasons=[],
                evidence_refs=[],
            ),
        )

    arena_loc = BUILDING_LOCATIONS.get("arena", {})
    arena_xy = (
        float(arena_loc.get("x", 0)) + float(arena_loc.get("width", 1)) / 2,
        float(arena_loc.get("y", 0)) + float(arena_loc.get("height", 1)) / 2,
    )
    for experiment in experiments or []:
        payload = experiment.get("payload") or {}
        strategy_id = payload.get("strategy_id")
        entities.append(
            WorldEntity(
                entity_id=f"experiment:{experiment['id']}",
                entity_type=WorldEntityType.EXPERIMENT,
                source_entity_id=f"experiment:{experiment['id']}",
                parent_entity_id=f"hero:{strategy_id}" if strategy_id else None,
                state=experiment["status"],
                health=0.0,
                activity=0.0,
                location=EntityLocation(zone="world", x=arena_xy[0], y=arena_xy[1]),
                metrics={},
                reasons=[],
                evidence_refs=[f"experiment:{experiment['id']}"],
            ),
        )

    return entities


async def _count_rows(session: AsyncSession, table: str) -> int:
    try:
        result = await session.scalar(text(f"SELECT COUNT(*) FROM {table}"))
        return int(result) if result is not None else 0
    except Exception:
        # On Postgres a failed statement aborts the whole transaction — every
        # later query on this same session would raise identically until the
        # session is rolled back. Without this, one missing table poisons the
        # count for every alphabetically-later table in the same session.
        await session.rollback()
        return 0


async def collect_row_counts(session: AsyncSession) -> dict[str, int]:
    """Count rows in every table any building activates on."""
    tables_to_count = {
        t for m in CONSTRUCTION_MANIFEST.values() for t in m.get("activates_on", [])
    }
    return {table: await _count_rows(session, table) for table in sorted(tables_to_count)}


async def get_construction_phases(session: AsyncSession) -> dict[str, ConstructionPhase]:
    """Real construction phase per building, derived from real row counts."""
    row_counts = await collect_row_counts(session)
    return {
        structure_id: determine_phase(structure_id, row_counts)
        for structure_id in CONSTRUCTION_MANIFEST
    }


async def get_benchmark_curve(session: AsyncSession) -> list[dict[str, Any]]:
    """The €1,000 buy-and-hold equity curve. `benchmark_equity`'s column
    is `date` (migration 0005), not `available_at` -- this query named the
    wrong column and silently returned [] via the except branch below on
    every real deploy since Prompt 2 shipped, producing a flat
    `benchmark_value` on /scoreboard/. Found and fixed as part of
    PROMPT 5 (docs/DEFERRED.md)."""
    try:
        result = await session.execute(
            text(
                "SELECT date, equity FROM benchmark_equity ORDER BY date LIMIT 1000",
            ),
        )
        rows = result.fetchall()
        return [{"date": r[0].isoformat(), "equity": float(r[1])} for r in rows]
    except Exception:
        # Same shared-session poisoning risk as _count_rows: an aborted
        # statement must be rolled back or every later query on this session
        # (in build_world_state) fails too.
        await session.rollback()
        return []


async def _get_recent_events(session: AsyncSession) -> list[WorldEvent]:
    try:
        result = await session.execute(
            text(
                "SELECT event_type, subject_id, severity, created_at "
                "FROM world_events ORDER BY created_at DESC LIMIT 50",
            ),
        )
        rows = result.fetchall()
        return [
            WorldEvent(
                type=r[0],
                subject_id=r[1],
                severity=r[2] or "info",
                timestamp=r[3] or datetime.now(UTC),
            )
            for r in rows
        ]
    except Exception:
        await session.rollback()
        return []


async def _get_strategies(session: AsyncSession) -> list[dict[str, Any]]:
    """Real `strategies` rows (Prompt 4). Same defensive try/except as
    every other query here -- the migration adding this table is recent,
    and this file's own rule is never raise on a missing table."""
    try:
        result = await session.execute(
            text("SELECT id, family, status FROM strategies ORDER BY created_at DESC LIMIT 500"),
        )
        return [dict(r._mapping) for r in result]
    except Exception:
        await session.rollback()
        return []


async def _get_experiments(session: AsyncSession) -> list[dict[str, Any]]:
    try:
        result = await session.execute(
            text("SELECT id, status, payload FROM experiments ORDER BY created_at DESC LIMIT 500"),
        )
        return [dict(r._mapping) for r in result]
    except Exception:
        await session.rollback()
        return []


async def _get_component_registry(session: AsyncSession) -> list[dict[str, Any]]:
    """Real `component_registry` rows (PROMPT 6). Same defensive
    try/except/rollback as every other query here."""
    try:
        result = await session.execute(
            text(
                "SELECT component, version, verdict, n_experiments, mean_oos_improvement "
                "FROM component_registry ORDER BY updated_at DESC LIMIT 100",
            ),
        )
        return [dict(r._mapping) for r in result]
    except Exception:
        await session.rollback()
        return []


async def _get_in_flight_agents(session: AsyncSession) -> list[Agent]:
    """One Agent per claimed `jobs` row (docs/WORLD_MAPPING.md:
    agents[].id <- jobs.id) -- Prompt 4 fills what was empty in Prompt 1.
    Same defensive try/except/rollback as every other query here: a
    missing `jobs` table degrades to no agents, not an error."""
    try:
        result = await session.execute(
            text(
                "SELECT id, agent_role, current_stage, next_stage, progress_pct, experiment_id "
                "FROM jobs WHERE status = 'claimed'",
            ),
        )
        agents = []
        for row in result:
            try:
                role = AgentRole(row.agent_role)
            except ValueError:
                continue  # an agent_role this build doesn't know -- skip, don't fabricate
            agents.append(
                Agent(
                    id=row.id,
                    role=role,
                    from_location=row.current_stage,
                    to_location=row.next_stage,
                    progress=row.progress_pct,
                    experiment_id=row.experiment_id,
                ),
            )
        return agents
    except Exception:
        await session.rollback()
        return []


async def _get_districts(session: AsyncSession) -> list[District]:
    """One District per real strategy family (PROMPT 7). `strategies.
    family` (strategy/spec.py's own FAMILIES) already carries this --
    doesn't wait on the separate `strategy_families` table
    docs/WORLD_MAPPING.md's original Prompt-4 design named and never
    built (docs/DEFERRED.md). Reuses `population.population_summary`'s
    real `GROUP BY family, status` query rather than reimplementing it.
    `archetype` is the lower-cased family name -- the real value until a
    `strategy_families.archetype` table exists to say otherwise (also
    deferred). `health`/`activity`/`portfolio_weight`/`alert_flags` stay
    at their real defaults (0.0/[]): their own source tables
    (validation_results aggregation, running-experiment counts, paper
    portfolio, strategy_alerts) are each a real, separate query this
    prompt doesn't build -- same rule as every other SCAFFOLDING field
    in this file, never fabricated."""
    try:
        summary = await population_summary(session)
    except Exception:
        await session.rollback()
        return []

    districts = []
    for family, counts in summary.items():
        population_by_status = {state.lower(): 0 for state in STRATEGY_STATES}
        population_by_status.update(counts)
        total = sum(population_by_status.values())
        districts.append(
            District(
                id=family,
                name=f"{family} District",
                archetype=family.lower(),
                population_by_status=population_by_status,
                building_state=(
                    ConstructionPhase.ACTIVE if total > 0 else ConstructionPhase.PLANNED
                ),
            )
        )
    return districts


async def _get_pending_depth_by_stage(session: AsyncSession) -> dict[str, int]:
    try:
        result = await session.execute(
            text(
                "SELECT current_stage, COUNT(*) AS n FROM jobs "
                "WHERE status = 'pending' GROUP BY current_stage",
            ),
        )
        return {row.current_stage: int(row.n) for row in result}
    except Exception:
        await session.rollback()
        return {}


async def build_world_state(session: AsyncSession) -> WorldState:
    """Build the complete WorldState from database state.

    Pure function: given a DB session, returns a WorldState.
    Never raises on missing tables — gracefully degrades to SCAFFOLDING.
    """
    row_counts = await collect_row_counts(session)
    pending_by_stage = await _get_pending_depth_by_stage(session)
    component_registry = await _get_component_registry(session)
    # ORDER BY updated_at DESC means row 0 is the most recently evaluated
    # component -- initially that's the baseline itself (the only row
    # there is), exactly matching PROMPTS.md's "Initially it shows only
    # the baseline registration"; it naturally becomes whatever component
    # was last ablated once a real second one exists (Prompt 7/9).
    temple_verdict = component_registry[0]["verdict"] if component_registry else None

    structures: list[Structure] = []
    for struct_id, manifest in CONSTRUCTION_MANIFEST.items():
        phase = determine_phase(struct_id, row_counts)
        kind = manifest.get("kind", struct_id)
        description = manifest.get("description", "")
        prompt_num = manifest.get("prompt")

        structures.append(
            Structure(
                id=struct_id,
                kind=kind,
                construction_phase=phase,
                # load stays 0.0, deliberately: docs/WORLD_MAPPING.md defines
                # it as queue depth / capacity, and no per-building capacity
                # exists -- dividing by an invented number would make the
                # world lie about how "busy" a building is.
                load=0.0,
                queue_depth=pending_by_stage.get(struct_id, 0),
                status="active" if phase == ConstructionPhase.ACTIVE else "idle",
                verdict=temple_verdict if kind == "temple" else None,
                description=description,
                prompt_built=prompt_num,
            ),
        )

    # Treasury: try to get benchmark data, fallback to defaults
    benchmark_curve = await get_benchmark_curve(session)
    benchmark_value = benchmark_curve[-1]["equity"] if benchmark_curve else 1000.0
    benchmark_return = (benchmark_value - 1000.0) / 1000.0 * 100

    # Districts are per strategy FAMILY (docs/WORLD_MAPPING.md) -- real as
    # of PROMPT 7, from `strategies.family` via `_get_districts` (the
    # separate `strategy_families` table the original doc named is still
    # deferred, see docs/DEFERRED.md; family/archetype come straight off
    # `strategies` itself).
    districts: list[District] = await _get_districts(session)

    # Agents are per ACTIVE JOB (docs/WORLD_MAPPING.md: agents[].id <- jobs.id).
    # Real as of Prompt 4's jobs table -- empty exactly when nothing is
    # actually claimed, never fabricated.
    agents: list[Agent] = await _get_in_flight_agents(session)

    # No strategy has ever paper traded (that's Prompt 8 / the `harbour`
    # building). There is no real system_value to report and nothing to
    # compare against the benchmark yet, so system_value/excess stay None
    # and the verdict stays NOT_STARTED regardless of any pending/running
    # experiments — an experiment existing is not the same as a portfolio
    # existing.
    scoreboard = Scoreboard(
        system_value=None,
        benchmark_value=benchmark_value,
        excess=None,
        verdict=ScoreboardVerdict.NOT_STARTED,
    )

    events = await _get_recent_events(session)
    strategies = await _get_strategies(session)
    experiments = await _get_experiments(session)
    entities = build_entities(structures, strategies, experiments)

    build_progress = {
        "total": len(CONSTRUCTION_MANIFEST),
        "active": sum(1 for s in structures if s.construction_phase == ConstructionPhase.ACTIVE),
        "scaffolding": sum(
            1 for s in structures if s.construction_phase == ConstructionPhase.SCAFFOLDING
        ),
    }

    return WorldState(
        tick=row_counts.get("ohlcv_bars", 0),
        generated_at=datetime.now(UTC),
        source_data_version=None,
        climate=ClimateState(),
        districts=districts,
        agents=agents,
        structures=structures,
        entities=entities,
        events=events,
        treasury=Treasury(
            total_equity=None,
            benchmark=BenchmarkMetrics(equity=benchmark_value, return_pct=benchmark_return),
        ),
        laws=LAWS,
        scoreboard=scoreboard,
        build_progress=build_progress,
    )

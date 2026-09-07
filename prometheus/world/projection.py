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

from prometheus.world.construction import CONSTRUCTION_MANIFEST
from prometheus.world.entities import (
    Agent,
    BenchmarkMetrics,
    ClimateState,
    ConstructionPhase,
    District,
    LawCompliance,
    Scoreboard,
    ScoreboardVerdict,
    Structure,
    Treasury,
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
    """The €1,000 buy-and-hold equity curve. Empty until Prompt 2 fills it."""
    try:
        result = await session.execute(
            text(
                "SELECT available_at, equity FROM benchmark_equity "
                "ORDER BY available_at LIMIT 1000",
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


async def build_world_state(session: AsyncSession) -> WorldState:
    """Build the complete WorldState from database state.

    Pure function: given a DB session, returns a WorldState.
    Never raises on missing tables — gracefully degrades to SCAFFOLDING.
    """
    row_counts = await collect_row_counts(session)

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
                load=0.0,
                queue_depth=0,
                status="active" if phase == ConstructionPhase.ACTIVE else "idle",
                verdict=None,
                description=description,
                prompt_built=prompt_num,
            ),
        )

    # Treasury: try to get benchmark data, fallback to defaults
    benchmark_curve = await get_benchmark_curve(session)
    benchmark_value = benchmark_curve[-1]["equity"] if benchmark_curve else 1000.0
    benchmark_return = (benchmark_value - 1000.0) / 1000.0 * 100

    # Districts are per strategy FAMILY (docs/WORLD_MAPPING.md), and the
    # strategy_families table does not exist until Prompt 4. Pipeline buildings
    # are `structures`, not districts — conflating them would make the world
    # claim districts exist when none do. Empty until Prompt 4.
    districts: list[District] = []

    # Agents are per ACTIVE JOB (docs/WORLD_MAPPING.md: agents[].id <- jobs.id),
    # and the jobs table does not exist until Prompt 4. Empty until then; a
    # fabricated agent would be the world lying about work it is not doing.
    agents: list[Agent] = []

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
        events=events,
        treasury=Treasury(
            total_equity=None,
            benchmark=BenchmarkMetrics(equity=benchmark_value, return_pct=benchmark_return),
        ),
        laws=LAWS,
        scoreboard=scoreboard,
        build_progress=build_progress,
    )

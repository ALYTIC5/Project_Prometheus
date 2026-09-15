"""prometheus/world/projection.py's build_entities -- the W0 WorldEntity
contract. BUILDING, the 3 real GOD entities, and (Prompt 4) HERO/EXPERIMENT
are populated from real rows only. Every other WorldEntityType has no real
backend source at all yet and must never appear, matching the existing
districts=[]/agents=[] honesty rule.
"""
from __future__ import annotations

from prometheus.world.construction import (
    BUILDING_LOCATIONS,
    CONSTRUCTION_MANIFEST,
    GOD_BY_BUILDING_KIND,
)
from prometheus.world.entities import ConstructionPhase, Structure, WorldEntityType
from prometheus.world.projection import build_entities


def _structure(struct_id: str, phase: ConstructionPhase) -> Structure:
    manifest = CONSTRUCTION_MANIFEST[struct_id]
    return Structure(
        id=struct_id,
        kind=manifest["kind"],
        construction_phase=phase,
        description=manifest["description"],
        prompt_built=manifest["prompt"],
    )


def _all_structures(phase: ConstructionPhase = ConstructionPhase.ACTIVE) -> list[Structure]:
    return [_structure(sid, phase) for sid in CONSTRUCTION_MANIFEST]


def test_one_building_entity_per_structure() -> None:
    structures = _all_structures()
    entities = build_entities(structures)
    building_entities = [e for e in entities if e.entity_type == WorldEntityType.BUILDING]
    assert len(building_entities) == len(structures)
    assert {e.entity_id for e in building_entities} == {f"building:{s.id}" for s in structures}


def test_exactly_three_gods_for_the_three_real_god_buildings() -> None:
    entities = build_entities(_all_structures())
    god_entities = [e for e in entities if e.entity_type == WorldEntityType.GOD]
    assert len(god_entities) == len(GOD_BY_BUILDING_KIND) == 3
    expected_ids = {f"god:{name}" for name in GOD_BY_BUILDING_KIND.values()}
    assert {e.entity_id for e in god_entities} == expected_ids


def test_god_parent_points_at_its_real_building() -> None:
    entities = build_entities(_all_structures())
    gods = {e.entity_id: e for e in entities if e.entity_type == WorldEntityType.GOD}
    assert gods["god:oracle_validation"].parent_entity_id == "building:oracle"
    assert gods["god:risk_guardian"].parent_entity_id == "building:vault"
    assert gods["god:archive_keeper"].parent_entity_id == "building:archive"


def test_types_with_no_real_backend_source_are_never_populated() -> None:
    """No strategies/experiments passed -> no HERO/EXPERIMENT either, same
    as every other type with no real table behind it yet."""
    entities = build_entities(_all_structures())
    never_populated = {
        WorldEntityType.TEMPLE,
        WorldEntityType.HERO,
        WorldEntityType.AGENT,
        WorldEntityType.EXPERIMENT,
        WorldEntityType.ARENA_MATCH,
        WorldEntityType.RESEARCH_SOURCE,
        WorldEntityType.PORTFOLIO,
        WorldEntityType.ALERT,
        WorldEntityType.REGIME,
        WorldEntityType.ARCHIVE_ENTRY,
    }
    present_types = {e.entity_type for e in entities}
    assert present_types.isdisjoint(never_populated)


def test_hero_entities_come_from_real_strategy_rows() -> None:
    strategies = [
        {"id": "MOM-001", "family": "MOMENTUM", "status": "PROMISING"},
        {"id": "MOM-002", "family": "MOMENTUM", "status": "REJECTED"},
    ]
    entities = build_entities(_all_structures(), strategies=strategies)
    heroes = {e.entity_id: e for e in entities if e.entity_type == WorldEntityType.HERO}

    assert set(heroes) == {"hero:MOM-001", "hero:MOM-002"}
    assert heroes["hero:MOM-001"].state == "PROMISING"
    assert heroes["hero:MOM-001"].source_entity_id == "strategy:MOM-001"
    assert heroes["hero:MOM-001"].parent_entity_id == "family:MOMENTUM"


def test_hero_anchors_at_the_real_forge_location() -> None:
    strategies = [{"id": "MOM-001", "family": "MOMENTUM", "status": "PROMISING"}]
    entities = build_entities(_all_structures(), strategies=strategies)
    hero = next(e for e in entities if e.entity_id == "hero:MOM-001")

    forge = BUILDING_LOCATIONS["forge"]
    assert hero.location.x == forge["x"] + forge["width"] / 2
    assert hero.location.y == forge["y"] + forge["height"] / 2


def test_experiment_entities_come_from_real_experiment_rows() -> None:
    experiments = [
        {"id": "EXP-2026-000001", "status": "completed", "payload": {"strategy_id": "MOM-001"}},
    ]
    entities = build_entities(_all_structures(), experiments=experiments)
    exp = next(e for e in entities if e.entity_type == WorldEntityType.EXPERIMENT)

    assert exp.entity_id == "experiment:EXP-2026-000001"
    assert exp.source_entity_id == "experiment:EXP-2026-000001"
    assert exp.parent_entity_id == "hero:MOM-001"
    assert exp.state == "completed"
    assert "experiment:EXP-2026-000001" in exp.evidence_refs


def test_experiment_with_no_strategy_id_has_no_parent() -> None:
    experiments = [{"id": "EXP-2026-000002", "status": "completed", "payload": {}}]
    entities = build_entities(_all_structures(), experiments=experiments)
    exp = next(e for e in entities if e.entity_type == WorldEntityType.EXPERIMENT)
    assert exp.parent_entity_id is None


def test_state_is_copied_verbatim_from_the_real_construction_phase() -> None:
    structures = [_structure("library", ConstructionPhase.SCAFFOLDING)]
    entities = build_entities(structures)
    building = next(e for e in entities if e.entity_id == "building:library")
    assert building.state == "SCAFFOLDING"


def test_every_entity_has_a_traceable_source() -> None:
    entities = build_entities(_all_structures())
    for entity in entities:
        assert entity.source_entity_id
        assert entity.source_entity_id.startswith("construction_manifest:")


def test_is_a_pure_function_same_input_same_output() -> None:
    structures = _all_structures()
    strategies = [{"id": "MOM-001", "family": "MOMENTUM", "status": "PROMISING"}]
    experiments = [{"id": "EXP-2026-000001", "status": "completed", "payload": {}}]

    first = build_entities(structures, strategies, experiments)
    second = build_entities(structures, strategies, experiments)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]

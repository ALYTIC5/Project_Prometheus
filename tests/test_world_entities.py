"""prometheus/world/projection.py's build_entities -- the W0 WorldEntity
contract. Only BUILDING and the 3 real GOD entities are ever populated;
every other WorldEntityType has no real backend source yet and must never
appear, matching the existing districts=[]/agents=[] honesty rule.
"""
from __future__ import annotations

from prometheus.world.construction import CONSTRUCTION_MANIFEST, GOD_BY_BUILDING_KIND
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


def test_no_other_entity_type_is_ever_fabricated() -> None:
    entities = build_entities(_all_structures())
    fabricated_types = {
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
    assert present_types.isdisjoint(fabricated_types)


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
    first = build_entities(structures)
    second = build_entities(structures)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]

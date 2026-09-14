"""PixelLab character import (A0): the compass<->rotation-index contract
frontend/src/sprites/direction.ts must mirror exactly, and the
`{kind}_{phase}`-exact-match fix to pack_atlas.py/compute_anchors.py's
`_category_of` that keeps a compound character name like
`oracle_validation_idle_r0` from being misclassified as the `oracle`
building kind.
"""
from __future__ import annotations

from tools.art.compute_anchors import _category_of as anchors_category_of
from tools.art.import_pixellab import ROTATION_INDEX, _base_name
from tools.art.pack_atlas import CHARACTER_ROTATION_RE, _category_of as pack_category_of


def test_rotation_index_covers_all_8_compass_directions_exactly_once() -> None:
    assert set(ROTATION_INDEX.values()) == set(range(8))
    assert len(ROTATION_INDEX) == 8


def test_rotation_index_matches_pixellab_naming() -> None:
    assert ROTATION_INDEX["south"] == 0
    assert ROTATION_INDEX["south-west"] == 7


def test_base_name_strips_agent_prefix_only() -> None:
    assert _base_name("agent_scribe") == "scribe"
    assert _base_name("hero_scout") == "hero_scout"
    assert _base_name("oracle_validation") == "oracle_validation"


def test_character_rotation_regex_matches_pixellab_keys() -> None:
    m = CHARACTER_ROTATION_RE.match("scribe_idle_r0")
    assert m is not None
    assert m.group("base") == "scribe_idle"
    assert m.group("rot") == "0"
    assert CHARACTER_ROTATION_RE.match("scribe_idle_r7") is not None
    assert CHARACTER_ROTATION_RE.match("scribe_idle_r8") is None


def test_character_rotation_regex_does_not_match_legacy_facing_names() -> None:
    # The pre-existing {role}_{action}_{f|b} JPEG-sheet duplication scheme
    # must keep taking pack_atlas.py's other branch, not this one.
    assert CHARACTER_ROTATION_RE.match("builder_idle_f") is None
    assert CHARACTER_ROTATION_RE.match("builder_idle_b") is None


def test_compound_character_name_is_not_misclassified_as_a_building() -> None:
    # Regression: "oracle_validation_idle_r0" starts with the real "oracle"
    # building kind but is a god, not the Oracle building.
    assert pack_category_of("oracle_validation_idle_r0") == "characters"
    assert anchors_category_of("oracle_validation_idle_r0") == "agent"


def test_real_building_keys_still_classify_as_buildings() -> None:
    assert pack_category_of("oracle_active") == "buildings"
    assert anchors_category_of("oracle_active") == "building"

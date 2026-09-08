"""Validates the hand-authored city layout in prometheus/world/construction.py.

Not a tests/laws/ check -- this is data integrity for the world view's
presentation layer, not one of the constitutional LAWS.
"""

from __future__ import annotations

import itertools

from prometheus.world.construction import BUILDING_LOCATIONS, MONUMENT_CLEAR_RADIUS


def _bounds(loc: dict[str, float]) -> tuple[float, float, float, float]:
    return (loc["x"], loc["y"], loc["x"] + loc["width"], loc["y"] + loc["height"])


def _overlaps(a: dict[str, float], b: dict[str, float], gap: float = 0.0) -> bool:
    ax0, ay0, ax1, ay1 = _bounds(a)
    bx0, by0, bx1, by1 = _bounds(b)
    return (ax0 - gap) < bx1 and (bx0 - gap) < ax1 and (ay0 - gap) < by1 and (by0 - gap) < ay1


def test_no_two_buildings_overlap() -> None:
    for id_a, id_b in itertools.combinations(BUILDING_LOCATIONS, 2):
        assert not _overlaps(BUILDING_LOCATIONS[id_a], BUILDING_LOCATIONS[id_b]), (
            f"{id_a} and {id_b} footprints overlap"
        )


def test_minimum_one_tile_gap_between_all_buildings() -> None:
    for id_a, id_b in itertools.combinations(BUILDING_LOCATIONS, 2):
        assert not _overlaps(BUILDING_LOCATIONS[id_a], BUILDING_LOCATIONS[id_b], gap=1.0), (
            f"{id_a} and {id_b} are closer than the required 1-tile gap"
        )


def test_monument_clear_radius_is_unoccupied() -> None:
    monument = BUILDING_LOCATIONS["monument"]
    mx0, my0, mx1, my1 = _bounds(monument)
    clear_box = {
        "x": mx0 - MONUMENT_CLEAR_RADIUS,
        "y": my0 - MONUMENT_CLEAR_RADIUS,
        "width": (mx1 - mx0) + 2 * MONUMENT_CLEAR_RADIUS,
        "height": (my1 - my0) + 2 * MONUMENT_CLEAR_RADIUS,
    }
    for building_id, loc in BUILDING_LOCATIONS.items():
        if building_id == "monument":
            continue
        assert not _overlaps(clear_box, loc), (
            f"{building_id} occupies the monument's clear radius"
        )


def test_footprint_sizes_are_sane() -> None:
    valid_sizes = {1, 2, 3}
    for building_id, loc in BUILDING_LOCATIONS.items():
        assert loc["width"] in valid_sizes and loc["height"] in valid_sizes, (
            f"{building_id} has an unclassified footprint size {loc['width']}x{loc['height']}"
        )
        assert loc["width"] == loc["height"], (
            f"{building_id} footprint is not square ({loc['width']}x{loc['height']})"
        )

"""Law W11: world scale is enforced before generation and on every asset."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from prometheus.world.construction import BUILDING_LOCATIONS
from tools.art import compose_prompt, scale


@pytest.fixture(autouse=True)
def _fresh_yaml_cache():
    compose_prompt._clear_cache()
    yield
    compose_prompt._clear_cache()


def _png(tmp_path: Path, canvas: int, content_w: int, content_h: int) -> Path:
    arr = np.zeros((canvas, canvas, 4), dtype=np.uint8)
    x0 = (canvas - content_w) // 2
    y0 = (canvas - content_h) // 2
    arr[y0 : y0 + content_h, x0 : x0 + content_w] = [200, 200, 200, 255]
    path = tmp_path / "asset.png"
    Image.fromarray(arr, "RGBA").save(path)
    return path


# ---------------------------------------------------------------- preflight


def test_preflight_rejects_canvas_too_small_for_3x3_building():
    assert BUILDING_LOCATIONS["treasury"]["width"] == 3
    result = scale.preflight("treasury", 168)
    assert not result.ok
    assert "192" in result.errors[0]


def test_preflight_accepts_canvas_that_fits_building():
    assert scale.preflight("treasury", 256).ok
    assert scale.preflight("library", 168).ok  # backend 2x2 -> 128px


def test_preflight_uses_backend_footprint_not_theme_yaml():
    # theme.yaml says library is 3x3; the backend (what the renderer draws) says 2x2.
    theme = compose_prompt._load_theme()
    assert theme["buildings"]["library"]["footprint"] == [3, 3]
    assert "128" in scale.preflight("library", 168).expected


def test_preflight_refuses_building_without_backend_footprint():
    result = scale.preflight("evolution_lab", 256)
    assert not result.ok
    assert "BUILDING_LOCATIONS" in result.errors[0]


def test_preflight_props_must_use_32px_canvas():
    assert not scale.preflight("olive_tree", 64).ok
    assert scale.preflight("olive_tree", 32).ok


def test_preflight_tiles_must_be_tile_width():
    assert scale.preflight("grass", 64).ok
    assert not scale.preflight("grass", 32).ok


@pytest.mark.parametrize("category", ["deities", "agents", "heroes", "townsfolk"])
def test_preflight_refuses_categories_without_a_scale_rule(category):
    key = next(iter(compose_prompt._load_theme()[category]))
    result = scale.preflight(key, 48)
    assert not result.ok
    assert "no scale rule" in result.errors[0]


def test_every_generatable_category_is_either_ruled_or_refused():
    theme = compose_prompt._load_theme()
    for category in ("buildings", "tiles", "props", "deities", "agents", "heroes", "townsfolk"):
        for key in theme[category]:
            result = scale.preflight(key, 64)
            # Never an exception; always a decision.
            assert isinstance(result.ok, bool)


# ------------------------------------------------------------- check_scale


def test_check_scale_flags_oversized_prop(tmp_path: Path):
    # The R2 64px props were 34-60px wide: must fail.
    assert not scale.check_scale(_png(tmp_path, 64, 60, 58), "stone_bench").ok
    assert not scale.check_scale(_png(tmp_path, 64, 52, 57), "olive_tree").ok


def test_check_scale_accepts_prop_at_world_scale(tmp_path: Path):
    assert scale.check_scale(_png(tmp_path, 32, 22, 24), "stone_bench").ok
    assert scale.check_scale(_png(tmp_path, 32, 30, 32), "olive_tree").ok


def test_check_scale_flags_undersized_building(tmp_path: Path):
    # R2 treasury anchor: 122px wide on a 3x3 (192px) footprint.
    result = scale.check_scale(_png(tmp_path, 168, 122, 112), "treasury")
    assert not result.ok


def test_check_scale_accepts_building_matching_footprint(tmp_path: Path):
    assert scale.check_scale(_png(tmp_path, 256, 188, 170), "treasury").ok


def test_check_scale_tile_width(tmp_path: Path):
    assert scale.check_scale(_png(tmp_path, 64, 64, 40), "grass").ok
    assert not scale.check_scale(_png(tmp_path, 64, 60, 40), "grass").ok

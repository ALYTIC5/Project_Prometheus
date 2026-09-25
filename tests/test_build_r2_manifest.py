"""R2 world-wiring: the tile squash fix and the prop/tile manifest builder."""
from __future__ import annotations

import itertools
import json

import numpy as np
import pytest
from PIL import Image

from tools.art.build_r2_manifest import BUILDINGS, PROPS, TILE_TARGET, TILES, squash_tile
from tools.art.common import PUBLIC_SPRITES_DIR, SPRITES_DIR

GREEN = [100, 200, 100, 255]  # top face
BROWN = [120, 60, 30, 255]  # side faces -- must never reach the output


def _iso_block(top: int, half_h: int, thickness: int, w: int = 64) -> np.ndarray:
    """Synthetic PixelLab iso tile: a GREEN top-face diamond (rows
    top..top+2*half_h, equator at top+half_h) sitting on BROWN side faces
    `thickness` px deep, on a square transparent canvas."""
    arr = np.zeros((w, w, 4), dtype=np.uint8)
    cx = (w - 1) / 2
    for y in range(w):
        for x in range(w):
            dx = abs(x - cx) / (w / 2)
            # side faces: the diamond's lower half, pushed down by thickness
            ys = y - top - half_h
            lower_v = 0 <= ys - thickness <= half_h and dx + (ys - thickness) / half_h <= 1.0
            band = 0 <= ys <= thickness and dx <= 1.0
            if lower_v or band:
                arr[y, x] = BROWN
    for y in range(w):
        for x in range(w):
            dy = abs(y - (top + half_h)) / half_h
            if abs(x - cx) / (w / 2) + dy <= 1.0:
                arr[y, x] = GREEN
    return arr


def test_squash_tile_outputs_exact_target_size():
    out = squash_tile(_iso_block(top=22, half_h=18, thickness=6))  # face 64x36, like grass
    assert out.shape[:2][::-1] == TILE_TARGET  # (width, height) vs (h, w) shape


def test_squash_tile_drops_side_faces():
    # The bug this replaced: cropping the whole bbox squashed the brown side
    # faces INTO the ground diamond, striping every tile.
    out = squash_tile(_iso_block(top=10, half_h=18, thickness=12))
    opaque = out[out[:, :, 3] > 0][:, :3]
    assert not (opaque == BROWN[:3]).all(axis=1).any()


def test_squash_tile_ignores_blades_above_the_face():
    # Real grass tiles have blades poking above the diamond's top point;
    # measuring the face from the top then over-sized it and let the side
    # band back in (R2b pebbles/thyme tiles).
    tile = _iso_block(top=14, half_h=18, thickness=10)
    tile[8:14, 30:34] = GREEN  # blades sticking up 6px above the top point
    out = squash_tile(tile)
    opaque = out[out[:, :, 3] > 0][:, :3]
    assert not (opaque == BROWN[:3]).all(axis=1).any()


def test_squash_tile_is_a_clean_diamond():
    out = squash_tile(_iso_block(top=22, half_h=18, thickness=6))
    h, w = out.shape[:2]
    assert out[h // 2, w // 2, 3] == 255  # centre opaque
    for corner in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)):
        assert out[corner][3] == 0  # outside the diamond stays transparent
    # every pixel inside the diamond is opaque -- no holes for the renderer
    ys, xs = np.mgrid[0:h, 0:w]
    diamond = (np.abs(xs + 0.5 - w / 2) / (w / 2) + np.abs(ys + 0.5 - h / 2) / (h / 2)) <= 1.0
    assert (out[diamond, 3] == 255).all()


def test_squash_tile_rejects_empty_image():
    arr = np.zeros((64, 64, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        squash_tile(arr)


def test_squash_tile_preserves_colour():
    out = squash_tile(_iso_block(top=20, half_h=18, thickness=6))
    opaque = out[out[:, :, 3] > 0]
    assert (opaque[:, :3] == GREEN[:3]).all()


# --------------------------------------------------------------------------
# Structural checks on the SHIPPED manifest.production.json + atlas PNGs --
# not a regeneration from art/raw/ (gitignored, may not exist on a fresh
# checkout), just verifying what's actually committed and deployed has no
# packing bugs. Complements tools/art/scale.py (world scale) and
# check_asset.py (per-source-image quality), neither of which checks the
# PACKED result: frame/anchor bounds, no overlaps, clean alpha.
# --------------------------------------------------------------------------

MANIFEST_PATH = SPRITES_DIR / "manifest.production.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST_PATH.exists():
        pytest.skip(f"{MANIFEST_PATH} not built yet -- run tools.art.build_r2_manifest")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def atlases(manifest: dict) -> dict[str, np.ndarray]:
    names = {e["atlas"] for e in manifest.values() if e.get("atlas")}
    return {name: np.array(Image.open(PUBLIC_SPRITES_DIR / name).convert("RGBA")) for name in names}


def test_manifest_has_every_expected_key(manifest: dict):
    expected = {name for name, _ in TILES}
    expected |= {f"prop_{base}_{i}" for base, paths in PROPS for i in range(len(paths))}
    expected |= {f"{kind}_{phase}" for kind, phase, _path in BUILDINGS}
    assert expected <= manifest.keys()


def test_every_frame_fits_inside_its_atlas(manifest: dict, atlases: dict[str, np.ndarray]):
    for key, entry in manifest.items():
        atlas = atlases[entry["atlas"]]
        h, w = atlas.shape[:2]
        f = entry["frame"]
        assert f["x"] >= 0 and f["y"] >= 0, key
        assert f["x"] + f["width"] <= w, f"{key} exceeds atlas width"
        assert f["y"] + f["height"] <= h, f"{key} exceeds atlas height"


def test_every_anchor_is_within_its_frame(manifest: dict):
    for key, entry in manifest.items():
        f, a = entry["frame"], entry["anchor"]
        assert 0 <= a["x"] <= f["width"], key
        assert 0 <= a["y"] <= f["height"], key


def test_no_two_frames_in_the_same_atlas_overlap(manifest: dict):
    by_atlas: dict[str, list[tuple[str, dict]]] = {}
    for key, entry in manifest.items():
        by_atlas.setdefault(entry["atlas"], []).append((key, entry["frame"]))
    for atlas_name, frames in by_atlas.items():
        for (k1, f1), (k2, f2) in itertools.combinations(frames, 2):
            overlap_x = f1["x"] < f2["x"] + f2["width"] and f2["x"] < f1["x"] + f1["width"]
            overlap_y = f1["y"] < f2["y"] + f2["height"] and f2["y"] < f1["y"] + f1["height"]
            assert not (overlap_x and overlap_y), f"{k1} overlaps {k2} in {atlas_name}"


def test_atlas_alpha_is_binary(atlases: dict[str, np.ndarray]):
    # PixelLab's own alpha is already strictly binary; the squash/pack
    # pipeline (NEAREST resize, plain array copy) must not introduce
    # soft/antialiased edges.
    for name, img in atlases.items():
        alpha = img[:, :, 3]
        non_binary = int(((alpha != 0) & (alpha != 255)).sum())
        assert non_binary == 0, f"{name} has {non_binary} non-binary alpha pixels"


def test_tile_frames_are_exactly_tile_target_size(manifest: dict):
    for name, _ in TILES:
        assert (manifest[name]["frame"]["width"], manifest[name]["frame"]["height"]) == TILE_TARGET

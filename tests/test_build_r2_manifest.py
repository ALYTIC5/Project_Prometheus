"""R2 world-wiring: the tile squash fix and the prop/tile manifest builder."""
from __future__ import annotations

import itertools
import json

import numpy as np
import pytest
from PIL import Image

from tools.art.build_r2_manifest import PROPS, TILE_TARGET, TILES, squash_tile
from tools.art.common import PUBLIC_SPRITES_DIR, SPRITES_DIR


def _diamond(canvas_w: int, top_row: int, bottom_row: int) -> np.ndarray:
    """A synthetic top face: opaque rows [top_row, bottom_row], full width,
    like PixelLab's iso-tile output (see STYLE_BIBLE's measured 64x36/41)."""
    arr = np.zeros((canvas_w, canvas_w, 4), dtype=np.uint8)
    arr[top_row : bottom_row + 1, :] = [100, 200, 100, 255]
    return arr


def test_squash_tile_outputs_exact_target_size():
    tile = _diamond(64, top_row=22, bottom_row=63)  # 64x42, like grass_calibration
    out = squash_tile(tile)
    assert out.shape[:2][::-1] == TILE_TARGET  # (width, height) vs (h, w) shape


def test_squash_tile_crops_to_content_first():
    # Content only occupies rows 10-49 (40px tall) inside a taller 80px canvas
    # -- squash must crop to the opaque bbox, not squash the whole canvas.
    arr = np.zeros((80, 64, 4), dtype=np.uint8)
    arr[10:50, :] = [50, 50, 200, 255]
    out = squash_tile(arr)
    assert out.shape[:2][::-1] == TILE_TARGET
    assert (out[:, :, 3] > 0).all()  # fully opaque -- no transparent border introduced


def test_squash_tile_rejects_empty_image():
    arr = np.zeros((64, 64, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        squash_tile(arr)


def test_squash_tile_preserves_colour():
    tile = _diamond(64, top_row=20, bottom_row=60)
    out = squash_tile(tile)
    opaque = out[out[:, :, 3] > 0]
    assert (opaque[:, :3] == [100, 200, 100]).all()


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

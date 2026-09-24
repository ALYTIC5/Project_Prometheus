"""R2 world-wiring: the tile squash fix and the prop/tile manifest builder."""
from __future__ import annotations

import numpy as np
import pytest

from tools.art.build_r2_manifest import TILE_TARGET, squash_tile


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

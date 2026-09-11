"""tools/art/common.py's A3 scale math and A4 anchor math, on synthetic
opaque masks -- no real sprites needed.
"""
from __future__ import annotations

import numpy as np

from tools.art.common import (
    anchor_building,
    anchor_character,
    anchor_prop,
    bbox_of,
    footprint_width,
    scale_for,
)


def _roof_and_base(roof_width: int, base_width: int, height: int = 30) -> np.ndarray:
    """A synthetic building alpha: a wide roof band on top, a narrower
    base band occupying the bottom third."""
    alpha = np.zeros((height, 100), dtype=bool)
    roof_h = height * 2 // 3
    alpha[:roof_h, 50 - roof_width // 2 : 50 + roof_width // 2] = True
    alpha[roof_h:, 50 - base_width // 2 : 50 + base_width // 2] = True
    return alpha


def test_footprint_width_ignores_roof_overhang() -> None:
    alpha = _roof_and_base(roof_width=100, base_width=60)
    assert footprint_width(alpha, bottom_frac=0.33) == 60


def test_scale_factor_for_known_footprint() -> None:
    # watchtower is TOWER (64px canonical width)
    assert scale_for("watchtower", measured_width=32) == 2.0
    # oracle/forge/arena are LARGE (192px canonical width)
    assert scale_for("oracle", measured_width=256) == 0.75


def test_anchor_building_centroid_on_asymmetric_shape() -> None:
    alpha = np.zeros((20, 20), dtype=bool)
    alpha[10:15, 5:10] = True  # body, off-centre to the left
    alpha[15, 5:15] = True  # base row extends further right at the very bottom
    x, y = anchor_building(alpha, band_frac=0.5)
    assert y == 15.0
    assert 5.0 <= x <= 15.0


def test_anchor_character_uses_smaller_band() -> None:
    alpha = np.zeros((100, 20), dtype=bool)
    alpha[:, 8:12] = True
    x, y = anchor_character(alpha)
    assert y == 99.0
    assert 8.0 <= x <= 12.0


def test_anchor_prop_is_exact_bbox_bottom_centre() -> None:
    alpha = np.zeros((10, 10), dtype=bool)
    alpha[2:8, 3:7] = True
    x0, y0, x1, y1 = bbox_of(alpha)
    x, y = anchor_prop(alpha)
    assert x == (x0 + x1) / 2.0
    assert y == float(y1)


def test_anchors_stay_within_frame_bounds() -> None:
    for base_width in (10, 30, 50, 90):
        alpha = _roof_and_base(roof_width=90, base_width=base_width, height=40)
        h, w = alpha.shape
        x, y = anchor_building(alpha)
        assert 0.0 <= x <= w
        assert 0.0 <= y <= h

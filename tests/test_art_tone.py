"""tools/art/compare_reference.py's pure luminance/saturation/frame-occupied math."""
from __future__ import annotations

import numpy as np
import pytest

from tools.art.compare_reference import DEFAULT_BACKGROUND, compute_metrics


def _solid_image(rgb: tuple[int, int, int], size: int = 8) -> np.ndarray:
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, :3] = rgb
    img[:, :, 3] = 255
    return img


def test_white_image_has_max_brightness_and_zero_saturation() -> None:
    metrics = compute_metrics(_solid_image((255, 255, 255)), background=(0, 0, 0))
    assert metrics["full_frame"]["brightness"]["median"] == 1.0
    assert metrics["full_frame"]["saturation_median"] == 0.0


def test_black_image_has_zero_brightness() -> None:
    metrics = compute_metrics(_solid_image((0, 0, 0)), background=(255, 255, 255))
    assert metrics["full_frame"]["brightness"]["median"] == 0.0


def test_pure_red_has_full_saturation() -> None:
    metrics = compute_metrics(_solid_image((255, 0, 0)), background=(0, 0, 0))
    assert metrics["full_frame"]["saturation_median"] == 1.0


def test_frame_occupied_excludes_background_pixels() -> None:
    img = _solid_image(DEFAULT_BACKGROUND, size=10)
    img[2:5, 2:5, :3] = (255, 255, 255)  # a 3x3 "city" patch in a background field
    metrics = compute_metrics(img)
    assert metrics["frame_occupied_pct"] == pytest.approx(9.0)
    assert metrics["city_only"]["pixel_count"] == 9


def test_city_only_brightness_ignores_dark_background() -> None:
    img = _solid_image((0, 0, 0), size=10)  # background is black
    img[0:5, :, :3] = (255, 255, 255)  # half the frame is a bright "city"
    metrics = compute_metrics(img, background=(0, 0, 0))
    full_frame_median = metrics["full_frame"]["brightness"]["median"]
    city_only_median = metrics["city_only"]["brightness"]["median"]
    assert full_frame_median < city_only_median
    assert city_only_median == 1.0

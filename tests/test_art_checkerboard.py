"""tools/art/common.py's checkerboard detection: period + two-grey
autocorrelation, solid-panel rejection, and JPEG-jitter tolerance. All
synthetic arrays, no Mockups/ files touched.
"""
from __future__ import annotations

import numpy as np

from tools.art.common import (
    AUTOCORR_CONFIDENCE_MIN,
    classify_checkerboard,
    detect_checkerboard,
    local_std_windows,
)


def _checkerboard(
    period: int, size: int = 512, grey_a: int = 0xCC, grey_b: int = 0xFF
) -> np.ndarray:
    coords = np.arange(size)
    parity = (coords[:, None] // period + coords[None, :] // period) % 2
    gray = np.where(parity == 0, grey_a, grey_b).astype(np.uint8)
    return np.stack([gray, gray, gray], axis=-1)


def test_detects_period_16() -> None:
    report = detect_checkerboard(_checkerboard(16))
    assert report.ok
    assert report.period == 16
    assert abs(report.grey_a[0] - report.grey_b[0]) > 30


def test_detects_period_8_and_32() -> None:
    for period in (8, 32):
        report = detect_checkerboard(_checkerboard(period))
        assert report.ok
        assert report.period == period


def test_low_confidence_on_noise() -> None:
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 256, size=(256, 256, 3), dtype=np.uint8)
    report = detect_checkerboard(noise)
    assert report.ok is False


def test_solid_region_scores_below_checkerboard() -> None:
    checker = _checkerboard(16).mean(axis=2)
    solid = np.full((64, 64), 220.0)
    checker_std = local_std_windows(checker, window=64, stride=64)[0, 0]
    solid_std = local_std_windows(solid, window=64, stride=64)[0, 0]
    assert solid_std < checker_std


def test_classification_tolerates_jpeg_jitter() -> None:
    board = _checkerboard(16)
    rng = np.random.default_rng(1)
    jitter = rng.integers(-8, 9, size=board.shape)
    jittered = np.clip(board.astype(int) + jitter, 0, 255).astype(np.uint8)
    report = detect_checkerboard(board)
    mask = classify_checkerboard(jittered, report)
    assert mask.mean() >= 0.99


def test_confidence_threshold_is_meaningful() -> None:
    # sanity: the threshold constant itself is a real fraction, not 0/1.
    assert 0.0 < AUTOCORR_CONFIDENCE_MIN < 1.0

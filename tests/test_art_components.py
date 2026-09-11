"""tools/art/common.py's connected-component labelling and merge-by-gap --
the A2 slicing algorithm, exercised on tiny synthetic boolean grids.
"""
from __future__ import annotations

import numpy as np

from tools.art.common import label_components, merge_boxes_by_gap


def test_labels_two_disjoint_blobs() -> None:
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    mask[6:8, 6:8] = True
    labels, n = label_components(mask)
    assert n == 2
    assert labels[1, 1] != labels[6, 6]
    assert labels[1, 1] == labels[2, 2]


def test_diagonal_touch_is_one_component() -> None:
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = True
    mask[1, 1] = True  # touches (0,0) only diagonally
    labels, n = label_components(mask)
    assert n == 1
    assert labels[0, 0] == labels[1, 1]


def test_merge_by_gap_joins_near_boxes() -> None:
    # three boxes with gaps 3, 3, 40 between consecutive ones
    boxes = [(0, 0, 4, 4), (7, 0, 11, 4), (14, 0, 18, 4), (58, 0, 62, 4)]
    groups = merge_boxes_by_gap(boxes, gap=6)
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 3]


def test_merge_is_transitive_across_passes() -> None:
    # A-B gap 5, B-C gap 5, A-C gap 20 -- threshold 6 must still join all three
    # via repeated passes (merging A+B first enlarges the box enough to reach C).
    a = (0, 0, 4, 4)
    b = (9, 0, 13, 4)
    c = (18, 0, 22, 4)
    groups = merge_boxes_by_gap([a, b, c], gap=6)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_min_area_rejects_noise_keeps_real_blob() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[0, 0] = True  # 1px noise speck
    mask[5:19, 5:19] = True  # 196px real blob
    labels, n = label_components(mask)
    assert n == 2
    areas = {label_id: int((labels == label_id).sum()) for label_id in range(1, n + 1)}
    small = [a for a in areas.values() if a < 120]
    big = [a for a in areas.values() if a >= 120]
    assert small == [1]
    assert big == [196]

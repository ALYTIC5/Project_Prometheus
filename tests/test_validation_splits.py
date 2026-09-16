"""validation/splits.py -- derive_folds. Pure function, no DB."""
from __future__ import annotations

import pytest

from prometheus.validation.splits import Fold, derive_folds


def test_train_and_test_never_overlap() -> None:
    for fold in derive_folds(n_bars=500, expected_horizon=10):
        assert set(fold.train_idx).isdisjoint(fold.test_idx)


def test_purge_embargo_gap_has_no_train_observation_within_horizon_of_test() -> None:
    """The real Law-1-adjacent property this module exists for: no
    training observation sits within `expected_horizon` bars of ANY test
    observation, on either side -- the gap a purge/embargo window is
    supposed to guarantee."""
    horizon = 15
    for fold in derive_folds(n_bars=500, expected_horizon=horizon):
        test_set = set(fold.test_idx)
        for train_i in fold.train_idx:
            nearest_gap = min(abs(train_i - test_i) for test_i in test_set)
            assert nearest_gap > horizon, (
                f"train index {train_i} is within {nearest_gap} <= horizon={horizon} "
                f"of a test index"
            )


def test_all_indices_within_bounds() -> None:
    n_bars = 300
    for fold in derive_folds(n_bars=n_bars, expected_horizon=8):
        for idx in (*fold.train_idx, *fold.test_idx):
            assert 0 <= idx < n_bars


def test_falls_back_to_walk_forward_below_cpcv_minimum() -> None:
    # Deliberately below CPCV's own n_splits*2 + 2*horizon floor
    # (6*2 + 2*5 = 22 for horizon=5).
    folds = derive_folds(n_bars=15, expected_horizon=5)
    assert len(folds) >= 1
    for fold in folds:
        assert isinstance(fold, Fold)
        assert set(fold.train_idx).isdisjoint(fold.test_idx)


def test_rejects_non_positive_inputs() -> None:
    with pytest.raises(ValueError):
        derive_folds(n_bars=0, expected_horizon=5)
    with pytest.raises(ValueError):
        derive_folds(n_bars=100, expected_horizon=0)

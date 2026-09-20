"""RANDOM_FOREST family's signal: the one function in this codebase
that is NOT a pure vectorized polars expression -- see
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md for
the full design and the no-look-ahead argument. A random-forest fit is
a real, sequential, greedy algorithm; it cannot be expressed as a
column expression the way every other family's signal can.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestClassifier

from prometheus.backtest.ml_features import FEATURE_COLUMNS, build_feature_frame

_N_ESTIMATORS = 100
_MAX_DEPTH = 4
_MIN_SAMPLES_LEAF = 10
_RANDOM_STATE = 0
_MIN_TRAINING_ROWS = 2 * _MIN_SAMPLES_LEAF


def random_forest_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    """Walk-forward: refit every `retrain_interval` bars on the trailing
    `train_window` bars, predict forward until the next refit. `raw[i]`
    is this bar's own predicted direction (computed from bar i's own
    features, same "uses today's close" convention every other family's
    raw condition uses); the final `position` column applies the SAME
    shift(1) discipline every other family ends with, so today's
    prediction becomes tomorrow's held position, never today's own.

    Flat (position 0.0) for every bar before the first checkpoint, and
    for any checkpoint whose training window has too few labeled rows
    or never saw a real "up" example -- honest "not enough signal here",
    same posture as every other family's rolling-window warm-up nulls
    defaulting to 0.0 via fill_null. n_jobs=1/random_state=0 make every
    fit exactly reproducible (CLAUDE.md's deterministic-core rule)."""
    frame = build_feature_frame(bars)
    n = frame.height
    features = frame.select(FEATURE_COLUMNS).to_numpy()
    labels = frame["label"].to_numpy()

    raw = [0.0] * n
    for checkpoint in range(train_window, n, retrain_interval):
        train_start = checkpoint - train_window
        train_features = features[train_start:checkpoint]
        train_labels = labels[train_start:checkpoint]
        # NOTE: filters on BOTH labels and features (not just labels, as
        # the original design sketch had it) -- f_vol10's rolling_std(10)
        # and the pct_change-based feature columns are null/NaN for the
        # first ~9 bars of ANY input frame, and the first checkpoint's
        # train_start is always 0, so the first training window always
        # contains NaN-valued FEATURE rows, not just NaN-labeled ones.
        # np.isfinite (not np.isnan) is required here: f_vol_chg is
        # volume.pct_change(1), which is +inf for any bar immediately
        # following a zero-volume bar -- a realistic case (illiquid
        # symbols, exchange outages, newly-listed pairs), not just NaN.
        # RandomForestClassifier.fit() raises ValueError: Input contains
        # NaN/infinity on any such row, so both NaN and inf must be
        # excluded together, on both labels and features.
        valid = np.isfinite(train_labels) & np.isfinite(train_features).all(axis=1)
        train_features = train_features[valid]
        train_labels = train_labels[valid]
        if train_features.shape[0] < _MIN_TRAINING_ROWS:
            continue

        model = RandomForestClassifier(
            n_estimators=_N_ESTIMATORS,
            max_depth=_MAX_DEPTH,
            min_samples_leaf=_MIN_SAMPLES_LEAF,
            random_state=_RANDOM_STATE,
            n_jobs=1,
        )
        model.fit(train_features, train_labels)
        if 1.0 not in model.classes_:
            continue  # never saw a real "up" example -- stays flat

        predict_end = min(checkpoint + retrain_interval, n)
        predict_features = features[checkpoint:predict_end]
        if predict_features.shape[0] == 0:
            continue
        # Same non-finite hazard as the training side, but on the
        # prediction slice: a row here with a non-finite feature (e.g.
        # f_vol_chg == +inf right after a zero-volume bar) would crash
        # model.predict_proba(). Rows that can't be scored are left at
        # their default 0.0 -- the module's own documented "not enough
        # signal here -> stay flat" posture, not a new behavior.
        finite_rows = np.isfinite(predict_features).all(axis=1)
        if not finite_rows.any():
            continue
        up_index = list(model.classes_).index(1.0)
        probabilities = model.predict_proba(predict_features[finite_rows])
        finite_offsets = np.flatnonzero(finite_rows)
        for offset, prob_row in zip(finite_offsets, probabilities, strict=True):
            raw[checkpoint + offset] = 1.0 if prob_row[up_index] >= predict_threshold else 0.0

    raw_series = pl.Series("_raw_prediction", raw)
    return frame.with_columns(raw_series.shift(1).fill_null(0.0).alias("position"))

"""Walk-forward-retrained ML strategy signals: the only functions in
this codebase that are NOT pure vectorized polars expressions -- see
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md for
the full design and the no-look-ahead argument. A real model fit is a
sequential, greedy/iterative algorithm; it cannot be expressed as a
column expression the way every classic-template family's signal can.

`_walk_forward_signal` is the one shared, correctness-tested loop every
ML family below calls -- each family supplies its own `build_model`
factory (fixed hyperparameters, closed over nothing mutable) and
whether its model needs `scale_features` (tree-based models don't;
linear/kernel models do, since they're sensitive to the wildly
different scales across FEATURE_COLUMNS -- returns ~0.01-0.05, RSI
~0-100, MACD histogram varying by symbol). Refitting a StandardScaler
per checkpoint (never a single scaler fit once over the whole series)
is the same walk-forward discipline the model itself follows: fitting a
scaler on future data would leak exactly the same way fitting a model
on future data would.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
import polars as pl
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from prometheus.backtest.ml_features import FEATURE_COLUMNS, build_feature_frame


class _ClassifierProtocol(Protocol):
    """Structural type for the sklearn classifiers used here -- every
    family's model exposes fit/predict_proba/classes_, regardless of
    which sklearn class it actually is."""

    classes_: Any

    def fit(self, X: Any, y: Any) -> Any: ...
    def predict_proba(self, X: Any) -> Any: ...


_MIN_SAMPLES_LEAF = 10
_MIN_TRAINING_ROWS = 2 * _MIN_SAMPLES_LEAF


def _walk_forward_signal(
    bars: pl.DataFrame,
    train_window: int,
    retrain_interval: int,
    predict_threshold: float,
    build_model: Callable[[], _ClassifierProtocol],
    *,
    scale_features: bool,
) -> pl.DataFrame:
    """Walk-forward: refit every `retrain_interval` bars on the trailing
    `train_window` bars, predict forward until the next refit. `raw[i]`
    is this bar's own predicted direction (computed from bar i's own
    features, same "uses today's close" convention every other family's
    raw condition uses); the final `position` column applies the SAME
    shift(1) discipline every other family ends with, so today's
    prediction becomes tomorrow's held position, never today's own.

    Flat (position 0.0) for every bar before the first checkpoint, for
    any checkpoint whose training window has too few labeled rows or
    never saw a real "up" example, and for any individual bar whose own
    features are non-finite (NaN or +-inf -- f_vol_chg is +inf for any
    bar immediately following a zero-volume bar, a realistic case, not
    a contrived one) -- honest "not enough signal here", same posture
    as every other family's rolling-window warm-up nulls defaulting to
    0.0 via fill_null. Every model factory this module calls pins its
    own random_state/n_jobs=1 so every fit is exactly reproducible
    (CLAUDE.md's deterministic-core rule)."""
    frame = build_feature_frame(bars)
    n = frame.height
    features = frame.select(FEATURE_COLUMNS).to_numpy()
    labels = frame["label"].to_numpy()

    raw = [0.0] * n
    strength = [0.0] * n
    for checkpoint in range(train_window, n, retrain_interval):
        train_start = checkpoint - train_window
        train_features = features[train_start:checkpoint]
        train_labels = labels[train_start:checkpoint]
        # np.isfinite (not np.isnan): RandomForestClassifier.fit() (and
        # every other classifier here) raises ValueError: Input contains
        # NaN/infinity on any row with either -- both must be excluded
        # together, on both labels and features.
        valid = np.isfinite(train_labels) & np.isfinite(train_features).all(axis=1)
        train_features = train_features[valid]
        train_labels = train_labels[valid]
        if train_features.shape[0] < _MIN_TRAINING_ROWS:
            continue
        # A training window with only one real class present (e.g. a
        # sustained one-directional move with no "up" -- or no "down" --
        # example anywhere in the window) is a real, non-contrived case,
        # not an edge case to dismiss: tree ensembles (RandomForest/
        # GradientBoosting) happily fit a degenerate single-class model,
        # but LogisticRegression and CalibratedClassifierCV(SVC) both
        # raise ValueError on it ("needs samples of at least 2 classes").
        # Checked before fit() rather than relying on the post-fit
        # `1.0 not in model.classes_` guard below, which assumes fit()
        # itself succeeded -- for these two models it would not.
        if len(np.unique(train_labels)) < 2:
            continue

        predict_end = min(checkpoint + retrain_interval, n)
        predict_features = features[checkpoint:predict_end]
        if predict_features.shape[0] == 0:
            continue
        finite_rows = np.isfinite(predict_features).all(axis=1)
        if not finite_rows.any():
            continue
        scoreable_features = predict_features[finite_rows]

        if scale_features:
            scaler = StandardScaler()
            train_features = scaler.fit_transform(train_features)
            scoreable_features = scaler.transform(scoreable_features)

        model = build_model()
        model.fit(train_features, train_labels)
        if 1.0 not in model.classes_:
            continue  # never saw a real "up" example -- stays flat

        up_index = list(model.classes_).index(1.0)
        probabilities = model.predict_proba(scoreable_features)
        finite_offsets = np.flatnonzero(finite_rows)
        for offset, prob_row in zip(finite_offsets, probabilities, strict=True):
            predicted_up_probability = prob_row[up_index]
            raw[checkpoint + offset] = 1.0 if predicted_up_probability >= predict_threshold else 0.0
            # Centered on 0: the continuous confidence the model's fit at
            # THIS checkpoint assigned to "up", same predict_proba() call
            # the binary position already thresholds -- not a second,
            # separately-fit estimate.
            strength[checkpoint + offset] = predicted_up_probability - 0.5

    raw_series = pl.Series("_raw_prediction", raw)
    return frame.with_columns(
        raw_series.shift(1).fill_null(0.0).alias("position"),
        pl.Series("_signal_strength", strength),
    )


# RANDOM_FOREST -- a small, shallow forest: cheap and hard to overfit on
# a few-hundred-row daily-bar training window.
_RF_N_ESTIMATORS = 100
_RF_MAX_DEPTH = 4
_RF_RANDOM_STATE = 0


def random_forest_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    return _walk_forward_signal(
        bars,
        train_window,
        retrain_interval,
        predict_threshold,
        lambda: RandomForestClassifier(
            n_estimators=_RF_N_ESTIMATORS,
            max_depth=_RF_MAX_DEPTH,
            min_samples_leaf=_MIN_SAMPLES_LEAF,
            random_state=_RF_RANDOM_STATE,
            n_jobs=1,
        ),
        scale_features=False,
    )


# GRADIENT_BOOSTING -- shallower trees than RANDOM_FOREST (boosting
# compounds errors across estimators, so each tree must be weaker) and
# a real, standard learning_rate; a small, cited default combination,
# not an invented one.
_GB_N_ESTIMATORS = 100
_GB_MAX_DEPTH = 3
_GB_LEARNING_RATE = 0.1
_GB_RANDOM_STATE = 0


def gradient_boosting_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    return _walk_forward_signal(
        bars,
        train_window,
        retrain_interval,
        predict_threshold,
        lambda: GradientBoostingClassifier(
            n_estimators=_GB_N_ESTIMATORS,
            max_depth=_GB_MAX_DEPTH,
            learning_rate=_GB_LEARNING_RATE,
            min_samples_leaf=_MIN_SAMPLES_LEAF,
            random_state=_GB_RANDOM_STATE,
        ),
        scale_features=False,
    )


# LOGISTIC_REGRESSION -- the simplest real ML baseline: linear, fast,
# and a genuine floor to compare RANDOM_FOREST/GRADIENT_BOOSTING against
# ("is the extra model complexity even earning its keep"). Needs
# scale_features=True: unlike a tree split, a linear decision boundary
# is sensitive to FEATURE_COLUMNS' wildly different scales.
_LR_MAX_ITER = 1000
_LR_RANDOM_STATE = 0


def logistic_regression_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    return _walk_forward_signal(
        bars,
        train_window,
        retrain_interval,
        predict_threshold,
        lambda: LogisticRegression(max_iter=_LR_MAX_ITER, random_state=_LR_RANDOM_STATE),
        scale_features=True,
    )


# SVM -- an RBF-kernel support vector classifier. Needs a real
# predict_proba, which a plain SVC doesn't expose without Platt
# scaling; sklearn's own currently-recommended way to get calibrated
# probabilities out of an SVC (SVC's own `probability=True` is
# deprecated as of sklearn 1.9, removed in 1.11) is to wrap it in
# CalibratedClassifierCV -- `ensemble=False` fits exactly one
# calibrator on one internal train/calibration split per checkpoint,
# not sklearn's own default 5-model ensemble, keeping this the same
# order of per-checkpoint compute cost as the other three models. The
# most compute-expensive of the four models here regardless (kernel
# SVMs scale worse than trees/linear models with training-set size) --
# its own grid (research/ml/generate.py) is deliberately smaller than
# the others' for this reason. Needs scale_features=True: an RBF
# kernel's distance computation is directly scale-sensitive.
_SVM_KERNEL = "rbf"
_SVM_C = 1.0
_SVM_RANDOM_STATE = 0


def svm_signal(
    bars: pl.DataFrame, train_window: int, retrain_interval: int, predict_threshold: float
) -> pl.DataFrame:
    return _walk_forward_signal(
        bars,
        train_window,
        retrain_interval,
        predict_threshold,
        lambda: CalibratedClassifierCV(
            SVC(kernel=_SVM_KERNEL, C=_SVM_C, random_state=_SVM_RANDOM_STATE),
            ensemble=False,
        ),
        scale_features=True,
    )

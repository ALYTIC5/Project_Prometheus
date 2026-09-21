"""ML strategy generators -- each deliberately NOT folded into
research/generate.py's generate_baseline_grid: every family here is a
generation component to be measured against that baseline
(experiments/ablation.py's register_*_component functions), not a
member of it. See
docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md.
"""
from __future__ import annotations

from prometheus.strategy.spec import (
    FAMILY_GRADIENT_BOOSTING,
    FAMILY_LOGISTIC_REGRESSION,
    FAMILY_RANDOM_FOREST,
    FAMILY_SVM,
    StrategySpec,
)

# 2x2x2 = 8 specs per symbol -- roughly the same order of magnitude as
# BOLLINGER's own 3x3=9, not an open-ended search. Shared by
# RANDOM_FOREST, GRADIENT_BOOSTING, and LOGISTIC_REGRESSION -- all three
# are roughly the same per-fit compute cost (a shallow tree ensemble or
# a linear model on a few-hundred-row window).
_TRAIN_WINDOWS = (120, 250)  # ~6mo / ~1yr of daily bars
_RETRAIN_INTERVALS = (20, 40)  # ~1mo / ~2mo
_PREDICT_THRESHOLDS = (0.5, 0.55)

# SVM's own, smaller grid: a kernel SVM's per-fit cost scales worse with
# training-set size than a shallow tree ensemble or a linear model, so
# its grid is deliberately narrower (1x2x2 = 4, not 2x2x2 = 8) -- the
# single fixed train_window is this family's own defensible default
# (roughly the same 6mo window RANDOM_FOREST/GRADIENT_BOOSTING already
# use at their own smaller setting), not every combination explored.
_SVM_TRAIN_WINDOWS = (120,)
_SVM_RETRAIN_INTERVALS = (20, 40)
_SVM_PREDICT_THRESHOLDS = (0.5, 0.55)


def generate_random_forest_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for train_window in _TRAIN_WINDOWS:
        for retrain_interval in _RETRAIN_INTERVALS:
            for threshold in _PREDICT_THRESHOLDS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_RANDOM_FOREST,
                        symbol=symbol,
                        timeframe=timeframe,
                        rf_train_window=train_window,
                        rf_retrain_interval=retrain_interval,
                        rf_predict_threshold=threshold,
                        # The model's actual, honest claim: predicts one
                        # bar ahead, regardless of train_window/retrain
                        # cadence.
                        expected_horizon=1,
                    )
                )
    return specs


def generate_gradient_boosting_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for train_window in _TRAIN_WINDOWS:
        for retrain_interval in _RETRAIN_INTERVALS:
            for threshold in _PREDICT_THRESHOLDS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_GRADIENT_BOOSTING,
                        symbol=symbol,
                        timeframe=timeframe,
                        gb_train_window=train_window,
                        gb_retrain_interval=retrain_interval,
                        gb_predict_threshold=threshold,
                        expected_horizon=1,
                    )
                )
    return specs


def generate_logistic_regression_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for train_window in _TRAIN_WINDOWS:
        for retrain_interval in _RETRAIN_INTERVALS:
            for threshold in _PREDICT_THRESHOLDS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_LOGISTIC_REGRESSION,
                        symbol=symbol,
                        timeframe=timeframe,
                        lr_train_window=train_window,
                        lr_retrain_interval=retrain_interval,
                        lr_predict_threshold=threshold,
                        expected_horizon=1,
                    )
                )
    return specs


def generate_svm_grid(symbol: str, timeframe: str) -> list[StrategySpec]:
    specs = []
    for train_window in _SVM_TRAIN_WINDOWS:
        for retrain_interval in _SVM_RETRAIN_INTERVALS:
            for threshold in _SVM_PREDICT_THRESHOLDS:
                specs.append(
                    StrategySpec(
                        family=FAMILY_SVM,
                        symbol=symbol,
                        timeframe=timeframe,
                        svm_train_window=train_window,
                        svm_retrain_interval=retrain_interval,
                        svm_predict_threshold=threshold,
                        expected_horizon=1,
                    )
                )
    return specs

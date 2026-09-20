"""RANDOM_FOREST's own generator -- deliberately NOT folded into
research/generate.py's generate_baseline_grid: RANDOM_FOREST is a new
generation component to be measured against that baseline
(experiments/ablation.register_ml_component), not a sixth member of
it. See docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md.
"""
from __future__ import annotations

from prometheus.strategy.spec import FAMILY_RANDOM_FOREST, StrategySpec

# 2x2x2 = 8 specs per symbol -- roughly the same order of magnitude as
# BOLLINGER's own 3x3=9, not an open-ended search.
_TRAIN_WINDOWS = (120, 250)  # ~6mo / ~1yr of daily bars
_RETRAIN_INTERVALS = (20, 40)  # ~1mo / ~2mo
_PREDICT_THRESHOLDS = (0.5, 0.55)


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

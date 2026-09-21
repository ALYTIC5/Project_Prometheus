from __future__ import annotations

from prometheus.research.generate import generate_baseline_grid
from prometheus.research.ml.generate import (
    generate_gradient_boosting_grid,
    generate_logistic_regression_grid,
    generate_random_forest_grid,
    generate_svm_grid,
)
from prometheus.strategy.spec import (
    FAMILY_GRADIENT_BOOSTING,
    FAMILY_LOGISTIC_REGRESSION,
    FAMILY_RANDOM_FOREST,
    FAMILY_SVM,
)


def test_generate_random_forest_grid_produces_real_specs() -> None:
    specs = generate_random_forest_grid("BTC/USDT", "1d")
    assert len(specs) == 8
    assert all(spec.family == FAMILY_RANDOM_FOREST for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)
    assert all(spec.rf_retrain_interval <= spec.rf_train_window for spec in specs)  # type: ignore[operator]


def test_every_spec_uses_the_requested_symbol_and_timeframe() -> None:
    specs = generate_random_forest_grid("ETH/USDT", "4h")
    assert all(spec.symbol == "ETH/USDT" and spec.timeframe == "4h" for spec in specs)


def test_is_deterministic() -> None:
    first = generate_random_forest_grid("BTC/USDT", "1d")
    second = generate_random_forest_grid("BTC/USDT", "1d")
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_generate_random_forest_grid_not_in_baseline_grid() -> None:
    baseline_families = {spec.family for spec in generate_baseline_grid("BTC/USDT", "1d")}
    assert FAMILY_RANDOM_FOREST not in baseline_families


def test_generate_gradient_boosting_grid_produces_real_specs() -> None:
    specs = generate_gradient_boosting_grid("BTC/USDT", "1d")
    assert len(specs) == 8
    assert all(spec.family == FAMILY_GRADIENT_BOOSTING for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)
    assert all(spec.gb_retrain_interval <= spec.gb_train_window for spec in specs)  # type: ignore[operator]


def test_generate_logistic_regression_grid_produces_real_specs() -> None:
    specs = generate_logistic_regression_grid("BTC/USDT", "1d")
    assert len(specs) == 8
    assert all(spec.family == FAMILY_LOGISTIC_REGRESSION for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)
    assert all(spec.lr_retrain_interval <= spec.lr_train_window for spec in specs)  # type: ignore[operator]


def test_generate_svm_grid_produces_a_smaller_real_grid() -> None:
    """SVM's grid is deliberately narrower than the other three ML
    families' (4, not 8) -- a kernel SVM's per-fit compute cost scales
    worse with training-set size, so its own generator explores fewer
    combinations, not a bug."""
    specs = generate_svm_grid("BTC/USDT", "1d")
    assert len(specs) == 4
    assert all(spec.family == FAMILY_SVM for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)
    assert all(spec.svm_retrain_interval <= spec.svm_train_window for spec in specs)  # type: ignore[operator]


def test_none_of_the_ml_grids_appear_in_baseline_grid() -> None:
    baseline_families = {spec.family for spec in generate_baseline_grid("BTC/USDT", "1d")}
    assert FAMILY_GRADIENT_BOOSTING not in baseline_families
    assert FAMILY_LOGISTIC_REGRESSION not in baseline_families
    assert FAMILY_SVM not in baseline_families

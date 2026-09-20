from __future__ import annotations

from prometheus.research.generate import generate_baseline_grid
from prometheus.research.ml.generate import generate_random_forest_grid
from prometheus.strategy.spec import FAMILY_RANDOM_FOREST


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

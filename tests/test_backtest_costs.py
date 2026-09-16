from __future__ import annotations

from prometheus.backtest.costs import (
    CostConfig,
    apply_cost,
    load_cost_config,
    make_cost_model,
)


def test_load_cost_config_reads_the_real_repo_file() -> None:
    config, content_hash = load_cost_config()
    assert config.taker_fee_bps > 0
    assert config.slippage_bps > 0
    assert len(content_hash) == 64
    int(content_hash, 16)  # raises if not valid hex


def test_load_cost_config_hash_is_deterministic() -> None:
    _, hash_a = load_cost_config()
    _, hash_b = load_cost_config()
    assert hash_a == hash_b


def test_make_cost_model_scales_linearly_with_notional() -> None:
    config = CostConfig(taker_fee_bps=10.0, slippage_bps=5.0)
    cost_model = make_cost_model(config)
    assert cost_model(1000.0) == 1000.0 * (15.0 / 10_000)
    assert cost_model(2000.0) == 2 * cost_model(1000.0)


def test_make_cost_model_of_zero_notional_is_zero() -> None:
    config = CostConfig(taker_fee_bps=10.0, slippage_bps=5.0)
    assert make_cost_model(config)(0.0) == 0.0


def test_apply_cost_is_the_default_config_bound_at_import() -> None:
    """apply_cost -- the zero-argument default every call site
    (benchmark.py, engine.py) imports -- must match what loading
    config/costs.yaml fresh and building a model from it produces."""
    config, _ = load_cost_config()
    assert apply_cost(1000.0) == make_cost_model(config)(1000.0)

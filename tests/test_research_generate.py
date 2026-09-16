from __future__ import annotations

import pytest

from prometheus.research.generate import (
    generate_baseline_grid,
    generate_bollinger_grid,
    generate_grid,
    generate_vol_breakout_grid,
)
from prometheus.strategy.spec import FAMILY_BOLLINGER, FAMILY_MOMENTUM, FAMILY_VOL_BREAKOUT


def test_generates_only_valid_slow_greater_than_fast_pairs() -> None:
    specs = generate_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.slow_window > spec.fast_window for spec in specs)


def test_every_spec_uses_the_requested_symbol_and_timeframe() -> None:
    specs = generate_grid("ETH/USDT", "4h")
    assert all(spec.symbol == "ETH/USDT" and spec.timeframe == "4h" for spec in specs)


def test_is_deterministic() -> None:
    first = generate_grid("BTC/USDT", "1d")
    second = generate_grid("BTC/USDT", "1d")
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_generate_grid_rejects_a_non_momentum_family() -> None:
    """generate_grid only ever produces fast_window/slow_window-shaped
    (MOMENTUM) specs -- the `family` parameter is not a generic
    passthrough, and StrategySpec's own per-family validator would
    reject a MOMENTUM-shaped spec claiming any other family anyway."""
    with pytest.raises(ValueError, match="MOMENTUM"):
        generate_grid("BTC/USDT", "1d", family=FAMILY_BOLLINGER)


def test_generate_bollinger_grid_produces_real_bollinger_specs() -> None:
    specs = generate_bollinger_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_BOLLINGER for spec in specs)
    assert all(
        spec.lookback_window is not None and spec.band_multiplier is not None for spec in specs
    )


def test_generate_vol_breakout_grid_produces_real_breakout_specs() -> None:
    specs = generate_vol_breakout_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_VOL_BREAKOUT for spec in specs)
    assert all(spec.exit_window < spec.breakout_window for spec in specs)  # type: ignore[operator]


def test_generate_baseline_grid_combines_all_three_families() -> None:
    specs = generate_baseline_grid("BTC/USDT", "1d")
    families = {spec.family for spec in specs}
    assert families == {FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT}

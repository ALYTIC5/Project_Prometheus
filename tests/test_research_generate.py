from __future__ import annotations

import pytest

from prometheus.research.generate import (
    generate_awesome_oscillator_grid,
    generate_baseline_grid,
    generate_bollinger_grid,
    generate_cci_grid,
    generate_grid,
    generate_keltner_grid,
    generate_macd_grid,
    generate_parabolic_sar_grid,
    generate_rsi_grid,
    generate_stochastic_grid,
    generate_supertrend_grid,
    generate_trix_grid,
    generate_vol_breakout_grid,
    generate_williams_r_grid,
)
from prometheus.strategy.spec import (
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_CCI,
    FAMILY_KELTNER,
    FAMILY_MACD,
    FAMILY_MOMENTUM,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RSI,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_TRIX,
    FAMILY_VOL_BREAKOUT,
    FAMILY_WILLIAMS_R,
)


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


def test_generate_rsi_grid_produces_real_rsi_specs() -> None:
    specs = generate_rsi_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_RSI for spec in specs)
    assert all(spec.rsi_lookback is not None and spec.rsi_oversold is not None for spec in specs)


def test_generate_macd_grid_produces_real_macd_specs() -> None:
    specs = generate_macd_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_MACD for spec in specs)
    assert all(spec.macd_fast < spec.macd_slow for spec in specs)  # type: ignore[operator]


def test_generate_stochastic_grid_produces_real_stochastic_specs() -> None:
    specs = generate_stochastic_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_STOCHASTIC for spec in specs)
    assert all(
        spec.stoch_lookback is not None and spec.stoch_oversold is not None for spec in specs
    )


def test_generate_parabolic_sar_grid_produces_real_sar_specs() -> None:
    specs = generate_parabolic_sar_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_PARABOLIC_SAR for spec in specs)
    assert all(spec.sar_af_start <= spec.sar_af_max for spec in specs)  # type: ignore[operator]


def test_generate_keltner_grid_produces_real_keltner_specs() -> None:
    specs = generate_keltner_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_KELTNER for spec in specs)
    assert all(
        spec.keltner_lookback is not None and spec.keltner_multiplier is not None
        for spec in specs
    )


def test_generate_williams_r_grid_produces_real_williams_specs() -> None:
    specs = generate_williams_r_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_WILLIAMS_R for spec in specs)
    assert all(
        spec.williams_lookback is not None and spec.williams_oversold is not None
        for spec in specs
    )


def test_generate_cci_grid_produces_real_cci_specs() -> None:
    specs = generate_cci_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_CCI for spec in specs)
    assert all(spec.cci_lookback is not None and spec.cci_oversold is not None for spec in specs)


def test_generate_awesome_oscillator_grid_produces_real_ao_specs() -> None:
    specs = generate_awesome_oscillator_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_AWESOME_OSCILLATOR for spec in specs)
    assert all(spec.ao_fast < spec.ao_slow for spec in specs)  # type: ignore[operator]


def test_generate_supertrend_grid_produces_real_supertrend_specs() -> None:
    specs = generate_supertrend_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_SUPERTREND for spec in specs)
    assert all(
        spec.supertrend_lookback is not None and spec.supertrend_multiplier is not None
        for spec in specs
    )


def test_generate_trix_grid_produces_real_trix_specs() -> None:
    specs = generate_trix_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_TRIX for spec in specs)
    assert all(spec.trix_lookback is not None for spec in specs)


def test_generate_baseline_grid_combines_all_thirteen_families() -> None:
    specs = generate_baseline_grid("BTC/USDT", "1d")
    families = {spec.family for spec in specs}
    assert families == {
        FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT, FAMILY_RSI, FAMILY_MACD,
        FAMILY_STOCHASTIC, FAMILY_PARABOLIC_SAR, FAMILY_KELTNER,
        FAMILY_WILLIAMS_R, FAMILY_CCI, FAMILY_AWESOME_OSCILLATOR, FAMILY_SUPERTREND, FAMILY_TRIX,
    }

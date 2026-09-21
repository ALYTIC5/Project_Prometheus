from __future__ import annotations

import pytest

from prometheus.research.generate import (
    generate_awesome_oscillator_grid,
    generate_baseline_grid,
    generate_bollinger_grid,
    generate_bollinger_pctb_grid,
    generate_cci_grid,
    generate_consecutive_down_grid,
    generate_gap_fade_grid,
    generate_grid,
    generate_ibs_grid,
    generate_keltner_grid,
    generate_keltner_reversion_grid,
    generate_macd_grid,
    generate_mfi_grid,
    generate_n_day_low_grid,
    generate_parabolic_sar_grid,
    generate_rsi2_connors_grid,
    generate_rsi_grid,
    generate_sma_distance_grid,
    generate_stochastic_grid,
    generate_supertrend_grid,
    generate_trix_grid,
    generate_ultimate_oscillator_grid,
    generate_vol_breakout_grid,
    generate_williams_r_grid,
    generate_zscore_grid,
)
from prometheus.strategy.spec import (
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_GAP_FADE,
    FAMILY_IBS,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_MACD,
    FAMILY_MFI,
    FAMILY_MOMENTUM,
    FAMILY_N_DAY_LOW,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RSI,
    FAMILY_SMA_DISTANCE,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_TRIX,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_VOL_BREAKOUT,
    FAMILY_WILLIAMS_R,
    FAMILY_ZSCORE,
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


def test_generate_baseline_grid_combines_all_twenty_three_families() -> None:
    specs = generate_baseline_grid("BTC/USDT", "1d")
    families = {spec.family for spec in specs}
    assert families == {
        FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT, FAMILY_RSI, FAMILY_MACD,
        FAMILY_STOCHASTIC, FAMILY_PARABOLIC_SAR, FAMILY_KELTNER,
        FAMILY_WILLIAMS_R, FAMILY_CCI, FAMILY_AWESOME_OSCILLATOR, FAMILY_SUPERTREND, FAMILY_TRIX,
        FAMILY_KELTNER_REVERSION, FAMILY_BOLLINGER_PCTB, FAMILY_ZSCORE, FAMILY_IBS,
        FAMILY_N_DAY_LOW, FAMILY_CONSECUTIVE_DOWN, FAMILY_SMA_DISTANCE,
        FAMILY_ULTIMATE_OSCILLATOR, FAMILY_MFI, FAMILY_GAP_FADE,
    }


def test_generate_rsi2_connors_grid_uses_lookback_2_and_extreme_oversold() -> None:
    specs = generate_rsi2_connors_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_RSI for spec in specs)
    assert all(spec.rsi_lookback == 2 for spec in specs)
    assert all(spec.rsi_oversold < 20.0 for spec in specs)  # type: ignore[operator]  # Connors' own extreme zone


def test_generate_keltner_reversion_grid() -> None:
    specs = generate_keltner_reversion_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_KELTNER_REVERSION for spec in specs)
    assert all(spec.keltner_rev_lookback is not None for spec in specs)


def test_generate_bollinger_pctb_grid() -> None:
    specs = generate_bollinger_pctb_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_BOLLINGER_PCTB for spec in specs)
    assert all(0.0 <= spec.pctb_oversold < 1.0 for spec in specs)  # type: ignore[operator]


def test_generate_zscore_grid() -> None:
    specs = generate_zscore_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_ZSCORE for spec in specs)
    assert all(spec.zscore_oversold < 0.0 for spec in specs)  # type: ignore[operator]


def test_generate_ibs_grid() -> None:
    specs = generate_ibs_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_IBS for spec in specs)
    assert all(spec.expected_horizon == 1 for spec in specs)


def test_generate_n_day_low_grid() -> None:
    specs = generate_n_day_low_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_N_DAY_LOW for spec in specs)


def test_generate_consecutive_down_grid() -> None:
    specs = generate_consecutive_down_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_CONSECUTIVE_DOWN for spec in specs)
    assert all(spec.consecutive_down_days > 0 for spec in specs)  # type: ignore[operator]


def test_generate_sma_distance_grid() -> None:
    specs = generate_sma_distance_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_SMA_DISTANCE for spec in specs)


def test_generate_ultimate_oscillator_grid_uses_williams_7_14_28() -> None:
    specs = generate_ultimate_oscillator_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_ULTIMATE_OSCILLATOR for spec in specs)
    assert all((spec.uo_short, spec.uo_mid, spec.uo_long) == (7, 14, 28) for spec in specs)


def test_generate_mfi_grid() -> None:
    specs = generate_mfi_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_MFI for spec in specs)


def test_generate_gap_fade_grid() -> None:
    specs = generate_gap_fade_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_GAP_FADE for spec in specs)
    assert all(spec.gap_fade_threshold > 0.0 for spec in specs)  # type: ignore[operator]

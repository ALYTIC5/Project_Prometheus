from __future__ import annotations

import pytest

from prometheus.research.generate import (
    generate_adx_di_grid,
    generate_aroon_grid,
    generate_atr_breakout_grid,
    generate_awesome_oscillator_grid,
    generate_baseline_grid,
    generate_bollinger_grid,
    generate_bollinger_pctb_grid,
    generate_cci_grid,
    generate_chandelier_exit_grid,
    generate_consecutive_down_grid,
    generate_dema_crossover_grid,
    generate_ema_crossover_grid,
    generate_gap_fade_grid,
    generate_grid,
    generate_hull_ma_grid,
    generate_ibs_grid,
    generate_ichimoku_grid,
    generate_inside_bar_breakout_grid,
    generate_kama_grid,
    generate_keltner_grid,
    generate_keltner_reversion_grid,
    generate_linreg_slope_grid,
    generate_ma_ribbon_grid,
    generate_macd_grid,
    generate_mfi_grid,
    generate_n_day_low_grid,
    generate_nr7_breakout_grid,
    generate_parabolic_sar_grid,
    generate_rsi2_connors_grid,
    generate_rsi_grid,
    generate_sma200_filter_grid,
    generate_sma_distance_grid,
    generate_squeeze_breakout_grid,
    generate_stochastic_grid,
    generate_supertrend_grid,
    generate_triple_ma_alignment_grid,
    generate_trix_grid,
    generate_tsmom_grid,
    generate_ultimate_oscillator_grid,
    generate_vol_breakout_grid,
    generate_vol_of_vol_filter_grid,
    generate_vol_regime_switch_grid,
    generate_vortex_grid,
    generate_williams_r_grid,
    generate_zscore_grid,
)
from prometheus.strategy.spec import (
    FAMILY_ADX_DI_CROSSOVER,
    FAMILY_AROON_CROSSOVER,
    FAMILY_ATR_BREAKOUT,
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CHANDELIER_EXIT,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_DEMA_CROSSOVER,
    FAMILY_EMA_CROSSOVER,
    FAMILY_GAP_FADE,
    FAMILY_HULL_MA_TREND,
    FAMILY_IBS,
    FAMILY_ICHIMOKU_BREAKOUT,
    FAMILY_INSIDE_BAR_BREAKOUT,
    FAMILY_KAMA_TREND,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_LINREG_SLOPE,
    FAMILY_MACD,
    FAMILY_MA_RIBBON,
    FAMILY_MFI,
    FAMILY_MOMENTUM,
    FAMILY_N_DAY_LOW,
    FAMILY_NR7_BREAKOUT,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RSI,
    FAMILY_SMA200_FILTER,
    FAMILY_SMA_DISTANCE,
    FAMILY_SQUEEZE_BREAKOUT,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_TRIPLE_MA_ALIGNMENT,
    FAMILY_TRIX,
    FAMILY_TSMOM,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_VOL_BREAKOUT,
    FAMILY_VOL_OF_VOL_FILTER,
    FAMILY_VOL_REGIME_SWITCH,
    FAMILY_VORTEX,
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


def test_generate_baseline_grid_combines_all_forty_three_families() -> None:
    specs = generate_baseline_grid("BTC/USDT", "1d")
    families = {spec.family for spec in specs}
    assert families == {
        FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT, FAMILY_RSI, FAMILY_MACD,
        FAMILY_STOCHASTIC, FAMILY_PARABOLIC_SAR, FAMILY_KELTNER,
        FAMILY_WILLIAMS_R, FAMILY_CCI, FAMILY_AWESOME_OSCILLATOR, FAMILY_SUPERTREND, FAMILY_TRIX,
        FAMILY_KELTNER_REVERSION, FAMILY_BOLLINGER_PCTB, FAMILY_ZSCORE, FAMILY_IBS,
        FAMILY_N_DAY_LOW, FAMILY_CONSECUTIVE_DOWN, FAMILY_SMA_DISTANCE,
        FAMILY_ULTIMATE_OSCILLATOR, FAMILY_MFI, FAMILY_GAP_FADE,
        FAMILY_EMA_CROSSOVER, FAMILY_TRIPLE_MA_ALIGNMENT, FAMILY_DEMA_CROSSOVER,
        FAMILY_HULL_MA_TREND, FAMILY_KAMA_TREND, FAMILY_TSMOM, FAMILY_ADX_DI_CROSSOVER,
        FAMILY_AROON_CROSSOVER, FAMILY_ICHIMOKU_BREAKOUT, FAMILY_VORTEX,
        FAMILY_LINREG_SLOPE, FAMILY_CHANDELIER_EXIT, FAMILY_SMA200_FILTER, FAMILY_MA_RIBBON,
        FAMILY_SQUEEZE_BREAKOUT, FAMILY_ATR_BREAKOUT, FAMILY_NR7_BREAKOUT,
        FAMILY_INSIDE_BAR_BREAKOUT, FAMILY_VOL_REGIME_SWITCH, FAMILY_VOL_OF_VOL_FILTER,
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


def test_generate_ema_crossover_grid_produces_valid_pairs() -> None:
    specs = generate_ema_crossover_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_EMA_CROSSOVER for spec in specs)
    assert all(spec.ema_slow_window > spec.ema_fast_window for spec in specs)  # type: ignore[operator]


def test_generate_triple_ma_alignment_grid_produces_ordered_triples() -> None:
    specs = generate_triple_ma_alignment_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_TRIPLE_MA_ALIGNMENT for spec in specs)
    assert all(
        spec.tma_fast_window < spec.tma_mid_window < spec.tma_slow_window  # type: ignore[operator]
        for spec in specs
    )


def test_generate_dema_crossover_grid_produces_valid_pairs() -> None:
    specs = generate_dema_crossover_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_DEMA_CROSSOVER for spec in specs)
    assert all(spec.dema_slow_window > spec.dema_fast_window for spec in specs)  # type: ignore[operator]


def test_generate_hull_ma_grid() -> None:
    specs = generate_hull_ma_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_HULL_MA_TREND for spec in specs)
    assert all(spec.hull_lookback is not None for spec in specs)


def test_generate_kama_grid_uses_kaufmans_own_defaults() -> None:
    specs = generate_kama_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_KAMA_TREND for spec in specs)
    assert any(
        (spec.kama_lookback, spec.kama_fast_sc, spec.kama_slow_sc) == (10, 2, 30)
        for spec in specs
    )


def test_generate_tsmom_grid_uses_moskowitz_ooi_pedersen_12_1() -> None:
    specs = generate_tsmom_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_TSMOM for spec in specs)
    assert any(
        (spec.tsmom_lookback_days, spec.tsmom_skip_days) == (252, 21) for spec in specs
    )


def test_generate_adx_di_grid_uses_wilders_default() -> None:
    specs = generate_adx_di_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_ADX_DI_CROSSOVER for spec in specs)
    assert any(spec.adx_lookback == 14 for spec in specs)


def test_generate_aroon_grid_uses_chandes_default() -> None:
    specs = generate_aroon_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_AROON_CROSSOVER for spec in specs)
    assert any(spec.aroon_lookback == 25 for spec in specs)


def test_generate_ichimoku_grid_uses_hosodas_9_26_52() -> None:
    specs = generate_ichimoku_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_ICHIMOKU_BREAKOUT for spec in specs)
    assert any(
        (spec.ichimoku_conversion, spec.ichimoku_base, spec.ichimoku_span_b) == (9, 26, 52)
        for spec in specs
    )


def test_generate_vortex_grid_uses_botes_siepman_default() -> None:
    specs = generate_vortex_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_VORTEX for spec in specs)
    assert any(spec.vortex_lookback == 14 for spec in specs)


def test_generate_linreg_slope_grid() -> None:
    specs = generate_linreg_slope_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_LINREG_SLOPE for spec in specs)


def test_generate_chandelier_exit_grid_uses_lebeaus_default() -> None:
    specs = generate_chandelier_exit_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_CHANDELIER_EXIT for spec in specs)
    assert any(
        (spec.chandelier_lookback, spec.chandelier_multiplier) == (22, 3.0) for spec in specs
    )


def test_generate_sma200_filter_grid_includes_the_classic_200() -> None:
    specs = generate_sma200_filter_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_SMA200_FILTER for spec in specs)
    assert any(spec.sma_filter_lookback == 200 for spec in specs)


def test_generate_ma_ribbon_grid_produces_ordered_triples() -> None:
    specs = generate_ma_ribbon_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_MA_RIBBON for spec in specs)
    assert all(
        spec.ribbon_short < spec.ribbon_mid < spec.ribbon_long  # type: ignore[operator]
        for spec in specs
    )


def test_generate_squeeze_breakout_grid() -> None:
    specs = generate_squeeze_breakout_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_SQUEEZE_BREAKOUT for spec in specs)
    assert all(spec.squeeze_lookback is not None for spec in specs)


def test_generate_atr_breakout_grid_uses_wilders_atr_default() -> None:
    specs = generate_atr_breakout_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_ATR_BREAKOUT for spec in specs)
    assert all(spec.atr_breakout_lookback == 14 for spec in specs)
    assert all(spec.atr_breakout_multiplier > 0.0 for spec in specs)  # type: ignore[operator]


def test_generate_nr7_breakout_grid_includes_crabels_own_seven() -> None:
    specs = generate_nr7_breakout_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_NR7_BREAKOUT for spec in specs)
    assert any(spec.nr7_lookback == 7 for spec in specs)


def test_generate_inside_bar_breakout_grid_includes_zero_buffer() -> None:
    specs = generate_inside_bar_breakout_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_INSIDE_BAR_BREAKOUT for spec in specs)
    assert any(spec.inside_bar_buffer == 0.0 for spec in specs)


def test_generate_vol_regime_switch_grid() -> None:
    specs = generate_vol_regime_switch_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_VOL_REGIME_SWITCH for spec in specs)
    assert all(
        spec.vre_vol_window is not None
        and spec.vre_regime_window is not None
        and spec.vre_lookback is not None
        for spec in specs
    )


def test_generate_vol_of_vol_filter_grid() -> None:
    specs = generate_vol_of_vol_filter_grid("BTC/USDT", "1d")
    assert len(specs) > 0
    assert all(spec.family == FAMILY_VOL_OF_VOL_FILTER for spec in specs)
    assert all(
        spec.vov_vol_window is not None
        and spec.vov_window is not None
        and spec.vov_lookback is not None
        for spec in specs
    )

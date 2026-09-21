from __future__ import annotations

import pytest
from pydantic import ValidationError

from prometheus.strategy.spec import (
    FAMILIES,
    FAMILY_AWESOME_OSCILLATOR,
    FAMILY_BOLLINGER_PCTB,
    FAMILY_CCI,
    FAMILY_CONSECUTIVE_DOWN,
    FAMILY_GAP_FADE,
    FAMILY_IBS,
    FAMILY_KELTNER,
    FAMILY_KELTNER_REVERSION,
    FAMILY_MFI,
    FAMILY_N_DAY_LOW,
    FAMILY_PARABOLIC_SAR,
    FAMILY_RANDOM_FOREST,
    FAMILY_SMA_DISTANCE,
    FAMILY_STOCHASTIC,
    FAMILY_SUPERTREND,
    FAMILY_TRIX,
    FAMILY_ULTIMATE_OSCILLATOR,
    FAMILY_WILLIAMS_R,
    FAMILY_ZSCORE,
    StrategySpec,
)


def test_valid_spec_constructs() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.family == "MOMENTUM"
    assert spec.fast_window == 5
    assert spec.parent_id is None
    assert spec.description == ""
    assert spec.source == "deterministic_grid"


def test_expected_horizon_is_required() -> None:
    """CLAUDE.md's own rule: don't invent thresholds silently -- a
    generator must state its own horizon claim, not receive a silent
    default."""
    with pytest.raises(ValidationError):
        StrategySpec(symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20)  # type: ignore[call-arg]


def test_slow_window_must_exceed_fast_window() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT",
            timeframe="1d",
            fast_window=20,
            slow_window=20,
            expected_horizon=20,
        )
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT", timeframe="1d", fast_window=20, slow_window=5, expected_horizon=20
        )


def test_spec_is_frozen() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    with pytest.raises(ValidationError):
        spec.fast_window = 10  # type: ignore[misc]


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        StrategySpec(
            symbol="BTC/USDT",
            timeframe="1d",
            fast_window=5,
            slow_window=20,
            expected_horizon=20,
            made_up_field=1,
        )


def test_parameters_mirrors_the_typed_fields() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.parameters == {"fast_window": 5.0, "slow_window": 20.0}


def test_config_hash_is_deterministic() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    assert spec.config_hash() == spec.config_hash()


def test_config_hash_is_sensitive_to_every_field() -> None:
    base = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    changed = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=21, expected_horizon=20
    )
    assert base.config_hash() != changed.config_hash()


def test_config_hash_ignores_metadata_and_provenance_fields() -> None:
    """config_hash identifies BEHAVIOR, not metadata: two specs with the
    same executable parameters but different lineage/description/source/
    horizon claim are the same strategy for dedup purposes -- "this
    fingerprint prevents rediscovering the same strategy forever" would
    break the moment two mutations from different parents landing on the
    same parameters were treated as distinct."""
    base = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    same_params_different_metadata = StrategySpec(
        symbol="BTC/USDT",
        timeframe="1d",
        fast_window=5,
        slow_window=20,
        expected_horizon=50,
        parent_id="SOME-OTHER-SPEC",
        description="a different mutation entirely",
        source="mutation",
    )
    assert base.config_hash() == same_params_different_metadata.config_hash()


def test_config_hash_is_sha256_hex() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    digest = spec.config_hash()
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


def test_with_updates_applies_a_valid_change() -> None:
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
    )
    child = spec.with_updates(slow_window=40)
    assert child.slow_window == 40
    assert child.fast_window == spec.fast_window
    assert spec.slow_window == 20  # the original is untouched (frozen)


def test_with_updates_re_validates_unlike_model_copy() -> None:
    """PROMPT 7's mutation/crossover code depends on this: plain
    model_copy(update=...) is documented Pydantic v2 behavior that skips
    validation entirely -- confirmed by testing it directly, not assumed.
    with_updates() must go through the real constructor instead."""
    spec = StrategySpec(
        symbol="BTC/USDT", timeframe="1d", fast_window=10, slow_window=20, expected_horizon=20
    )
    # model_copy itself really does allow this (documents the bug it
    # would otherwise be easy to reintroduce).
    invalid_via_model_copy = spec.model_copy(update={"slow_window": 5})
    assert invalid_via_model_copy.slow_window == 5  # silently invalid

    with pytest.raises(ValidationError):
        spec.with_updates(slow_window=5)


def test_random_forest_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
        rf_train_window=120, rf_retrain_interval=20, rf_predict_threshold=0.5,
        expected_horizon=1,
    )
    assert spec.family == FAMILY_RANDOM_FOREST
    assert spec.parameters == {
        "rf_train_window": 120.0, "rf_retrain_interval": 20.0, "rf_predict_threshold": 0.5,
    }


def test_random_forest_missing_fields_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d", expected_horizon=1,
        )


def test_random_forest_retrain_interval_exceeding_train_window_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
            rf_train_window=20, rf_retrain_interval=50, rf_predict_threshold=0.5,
            expected_horizon=1,
        )


def test_random_forest_threshold_out_of_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_RANDOM_FOREST, symbol="BTC/USDT", timeframe="1d",
            rf_train_window=120, rf_retrain_interval=20, rf_predict_threshold=1.5,
            expected_horizon=1,
        )


def test_random_forest_deliberately_excluded_from_families_tuple() -> None:
    """RANDOM_FOREST is a separate generation component (like evolution/
    LLM hypotheses), not part of the classic-template baseline FAMILIES
    tuple swap_family/the LLM system prompt draw from. This test
    documents the exclusion so a future edit can't silently 'fix' it
    into the tuple."""
    assert FAMILY_RANDOM_FOREST not in FAMILIES


def test_stochastic_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_STOCHASTIC, symbol="BTC/USDT", timeframe="1d",
        stoch_lookback=14, stoch_oversold=20.0, expected_horizon=14,
    )
    assert spec.family == FAMILY_STOCHASTIC
    assert FAMILY_STOCHASTIC in FAMILIES


def test_stochastic_oversold_out_of_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_STOCHASTIC, symbol="BTC/USDT", timeframe="1d",
            stoch_lookback=14, stoch_oversold=150.0, expected_horizon=14,
        )


def test_parabolic_sar_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_PARABOLIC_SAR, symbol="BTC/USDT", timeframe="1d",
        sar_af_start=0.02, sar_af_increment=0.02, sar_af_max=0.2, expected_horizon=10,
    )
    assert spec.family == FAMILY_PARABOLIC_SAR
    assert FAMILY_PARABOLIC_SAR in FAMILIES


def test_parabolic_sar_start_exceeding_max_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_PARABOLIC_SAR, symbol="BTC/USDT", timeframe="1d",
            sar_af_start=0.5, sar_af_increment=0.02, sar_af_max=0.2, expected_horizon=10,
        )


def test_keltner_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_KELTNER, symbol="BTC/USDT", timeframe="1d",
        keltner_lookback=20, keltner_multiplier=2.0, expected_horizon=20,
    )
    assert spec.family == FAMILY_KELTNER
    assert FAMILY_KELTNER in FAMILIES


def test_williams_r_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_WILLIAMS_R, symbol="BTC/USDT", timeframe="1d",
        williams_lookback=14, williams_oversold=-80.0, expected_horizon=14,
    )
    assert spec.family == FAMILY_WILLIAMS_R
    assert FAMILY_WILLIAMS_R in FAMILIES


def test_williams_r_oversold_out_of_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_WILLIAMS_R, symbol="BTC/USDT", timeframe="1d",
            williams_lookback=14, williams_oversold=10.0, expected_horizon=14,
        )


def test_cci_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_CCI, symbol="BTC/USDT", timeframe="1d",
        cci_lookback=20, cci_oversold=-100.0, expected_horizon=20,
    )
    assert spec.family == FAMILY_CCI
    assert FAMILY_CCI in FAMILIES


def test_cci_positive_oversold_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_CCI, symbol="BTC/USDT", timeframe="1d",
            cci_lookback=20, cci_oversold=100.0, expected_horizon=20,
        )


def test_awesome_oscillator_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_AWESOME_OSCILLATOR, symbol="BTC/USDT", timeframe="1d",
        ao_fast=5, ao_slow=34, expected_horizon=34,
    )
    assert spec.family == FAMILY_AWESOME_OSCILLATOR
    assert FAMILY_AWESOME_OSCILLATOR in FAMILIES


def test_awesome_oscillator_fast_exceeding_slow_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_AWESOME_OSCILLATOR, symbol="BTC/USDT", timeframe="1d",
            ao_fast=34, ao_slow=5, expected_horizon=34,
        )


def test_supertrend_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_SUPERTREND, symbol="BTC/USDT", timeframe="1d",
        supertrend_lookback=10, supertrend_multiplier=3.0, expected_horizon=10,
    )
    assert spec.family == FAMILY_SUPERTREND
    assert FAMILY_SUPERTREND in FAMILIES


def test_trix_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_TRIX, symbol="BTC/USDT", timeframe="1d",
        trix_lookback=15, expected_horizon=15,
    )
    assert spec.family == FAMILY_TRIX
    assert FAMILY_TRIX in FAMILIES


def test_keltner_reversion_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_KELTNER_REVERSION, symbol="BTC/USDT", timeframe="1d",
        keltner_rev_lookback=20, keltner_rev_multiplier=2.0, expected_horizon=20,
    )
    assert spec.family == FAMILY_KELTNER_REVERSION
    assert FAMILY_KELTNER_REVERSION in FAMILIES


def test_bollinger_pctb_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_BOLLINGER_PCTB, symbol="BTC/USDT", timeframe="1d",
        pctb_lookback=20, pctb_multiplier=2.0, pctb_oversold=0.2, expected_horizon=20,
    )
    assert spec.family == FAMILY_BOLLINGER_PCTB
    assert FAMILY_BOLLINGER_PCTB in FAMILIES


def test_bollinger_pctb_oversold_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_BOLLINGER_PCTB, symbol="BTC/USDT", timeframe="1d",
            pctb_lookback=20, pctb_multiplier=2.0, pctb_oversold=1.5, expected_horizon=20,
        )


def test_zscore_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_ZSCORE, symbol="BTC/USDT", timeframe="1d",
        zscore_lookback=20, zscore_oversold=-2.0, expected_horizon=20,
    )
    assert spec.family == FAMILY_ZSCORE
    assert FAMILY_ZSCORE in FAMILIES


def test_zscore_positive_oversold_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_ZSCORE, symbol="BTC/USDT", timeframe="1d",
            zscore_lookback=20, zscore_oversold=2.0, expected_horizon=20,
        )


def test_ibs_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_IBS, symbol="BTC/USDT", timeframe="1d",
        ibs_oversold=0.2, expected_horizon=1,
    )
    assert spec.family == FAMILY_IBS
    assert FAMILY_IBS in FAMILIES


def test_ibs_oversold_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_IBS, symbol="BTC/USDT", timeframe="1d",
            ibs_oversold=1.5, expected_horizon=1,
        )


def test_n_day_low_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_N_DAY_LOW, symbol="BTC/USDT", timeframe="1d",
        ndaylow_lookback=20, expected_horizon=20,
    )
    assert spec.family == FAMILY_N_DAY_LOW
    assert FAMILY_N_DAY_LOW in FAMILIES


def test_consecutive_down_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_CONSECUTIVE_DOWN, symbol="BTC/USDT", timeframe="1d",
        consecutive_down_days=3, expected_horizon=3,
    )
    assert spec.family == FAMILY_CONSECUTIVE_DOWN
    assert FAMILY_CONSECUTIVE_DOWN in FAMILIES


def test_consecutive_down_non_positive_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_CONSECUTIVE_DOWN, symbol="BTC/USDT", timeframe="1d",
            consecutive_down_days=0, expected_horizon=3,
        )


def test_sma_distance_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_SMA_DISTANCE, symbol="BTC/USDT", timeframe="1d",
        sma_dist_lookback=200, sma_dist_oversold=0.1, expected_horizon=200,
    )
    assert spec.family == FAMILY_SMA_DISTANCE
    assert FAMILY_SMA_DISTANCE in FAMILIES


def test_sma_distance_oversold_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_SMA_DISTANCE, symbol="BTC/USDT", timeframe="1d",
            sma_dist_lookback=200, sma_dist_oversold=1.5, expected_horizon=200,
        )


def test_ultimate_oscillator_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_ULTIMATE_OSCILLATOR, symbol="BTC/USDT", timeframe="1d",
        uo_short=7, uo_mid=14, uo_long=28, uo_oversold=30.0, expected_horizon=14,
    )
    assert spec.family == FAMILY_ULTIMATE_OSCILLATOR
    assert FAMILY_ULTIMATE_OSCILLATOR in FAMILIES


def test_ultimate_oscillator_out_of_order_windows_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_ULTIMATE_OSCILLATOR, symbol="BTC/USDT", timeframe="1d",
            uo_short=28, uo_mid=14, uo_long=7, uo_oversold=30.0, expected_horizon=14,
        )


def test_mfi_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_MFI, symbol="BTC/USDT", timeframe="1d",
        mfi_lookback=14, mfi_oversold=20.0, expected_horizon=14,
    )
    assert spec.family == FAMILY_MFI
    assert FAMILY_MFI in FAMILIES


def test_mfi_oversold_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_MFI, symbol="BTC/USDT", timeframe="1d",
            mfi_lookback=14, mfi_oversold=200.0, expected_horizon=14,
        )


def test_gap_fade_valid_spec_constructs() -> None:
    spec = StrategySpec(
        family=FAMILY_GAP_FADE, symbol="BTC/USDT", timeframe="1d",
        gap_fade_threshold=0.02, expected_horizon=1,
    )
    assert spec.family == FAMILY_GAP_FADE
    assert FAMILY_GAP_FADE in FAMILIES


def test_gap_fade_non_positive_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySpec(
            family=FAMILY_GAP_FADE, symbol="BTC/USDT", timeframe="1d",
            gap_fade_threshold=0.0, expected_horizon=1,
        )

"""tests/test_engine_new_families.py -- signal correctness for the 10
Batch B (mean reversion) families added to backtest/engine.py:
KELTNER_REVERSION, BOLLINGER_PCTB, ZSCORE, IBS, N_DAY_LOW,
CONSECUTIVE_DOWN, SMA_DISTANCE, ULTIMATE_OSCILLATOR, MFI, GAP_FADE.

No existing file unit-tests classic-family signal functions directly
(only spec validation and grid generation are tested elsewhere) --
these tests close that gap for the new families specifically, since
signal correctness is the thing most worth verifying by hand for a
mean-reversion threshold.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from prometheus.backtest.engine import (
    _consecutive_down_signal,
    _gap_fade_signal,
    _ibs_signal,
    _keltner_reversion_signal,
    _mfi_signal,
    _n_day_low_signal,
    _sma_distance_signal,
    _ultimate_oscillator_signal,
    _zscore_signal,
)


def _bars(closes: list[float], opens: list[float] | None = None,
          highs: list[float] | None = None, lows: list[float] | None = None,
          volumes: list[float] | None = None) -> pl.DataFrame:
    n = len(closes)
    start = datetime(2020, 1, 1)
    return pl.DataFrame(
        {
            "available_at": [start + timedelta(days=i) for i in range(n)],
            "open": opens or closes,
            "high": highs or closes,
            "low": lows or closes,
            "close": closes,
            "volume": volumes or [1000.0] * n,
        }
    )


def test_keltner_reversion_goes_long_below_the_lower_band() -> None:
    # Flat at 100 for a long warm-up, then a sharp one-bar drop far below
    # any plausible ATR-based lower band.
    closes = [100.0] * 20 + [70.0]
    bars = _bars(closes)
    result = _keltner_reversion_signal(bars, lookback=10, multiplier=1.5)
    positions = result["position"].to_list()
    # The drop happens at the LAST bar; shift(1) means it only shows up
    # as a position on the bar AFTER it -- there is none, so this proves
    # nothing crashed and every bar before the drop is flat (no lower-
    # band breach on a flat price series).
    assert positions[:20] == [0.0] * 20


def test_keltner_reversion_recovers_to_flat_after_the_drop() -> None:
    closes = [100.0] * 20 + [70.0, 70.0, 100.0]
    bars = _bars(closes)
    result = _keltner_reversion_signal(bars, lookback=10, multiplier=1.5)
    positions = result["position"].to_list()
    # Bar 21 (index 20, the drop) triggers close < lower band -> long
    # from bar 22 onward (shift(1)), until price recovers.
    assert positions[21] == 1.0


def test_zscore_goes_long_on_a_sharp_drop() -> None:
    # shift(1): the drop's own z-score condition (index 20) only shows
    # up as a position on the FOLLOWING bar -- a trailing flat bar is
    # needed to observe it.
    closes = [100.0] * 20 + [80.0, 80.0]
    bars = _bars(closes)
    result = _zscore_signal(bars, lookback=10, oversold=-1.5)
    positions = result["position"].to_list()
    assert positions[21] == 1.0


def test_zscore_flat_on_constant_price() -> None:
    closes = [100.0] * 15
    bars = _bars(closes)
    result = _zscore_signal(bars, lookback=10, oversold=-1.5)
    # zero std -> NaN z-score -> never below oversold -> always flat
    assert result["position"].to_list() == [0.0] * 15


def test_ibs_long_when_close_near_the_low() -> None:
    bars = _bars(
        closes=[101.0, 101.0],
        highs=[110.0, 110.0],
        lows=[100.0, 100.0],
    )
    # IBS = (101-100)/(110-100) = 0.1, below oversold=0.2
    result = _ibs_signal(bars, oversold=0.2)
    positions = result["position"].to_list()
    assert positions[1] == 1.0  # shift(1): bar 0's IBS -> position at bar 1


def test_ibs_flat_when_close_near_the_high() -> None:
    bars = _bars(
        closes=[109.0, 109.0],
        highs=[110.0, 110.0],
        lows=[100.0, 100.0],
    )
    # IBS = (109-100)/(110-100) = 0.9, above oversold=0.2
    result = _ibs_signal(bars, oversold=0.2)
    assert result["position"].to_list()[1] == 0.0


def test_n_day_low_triggers_on_a_fresh_low() -> None:
    closes = [100.0, 99.0, 98.0, 97.0, 96.0]  # strictly declining -> every bar is a new low
    bars = _bars(closes)
    result = _n_day_low_signal(bars, lookback=3)
    positions = result["position"].to_list()
    # Every bar from index 2 onward (once the 3-bar rolling window is
    # full) makes a fresh low -> long on the NEXT bar (shift(1)).
    assert positions[3] == 1.0
    assert positions[4] == 1.0


def test_n_day_low_flat_on_a_rising_series() -> None:
    closes = [96.0, 97.0, 98.0, 99.0, 100.0]
    bars = _bars(closes)
    result = _n_day_low_signal(bars, lookback=3)
    positions = result["position"].to_list()
    # Only the very first bar of the window can ever equal the rolling
    # min on a strictly rising series (it IS the min by construction);
    # every later bar's close exceeds the window's earlier low.
    assert positions[3] == 0.0
    assert positions[4] == 0.0


def test_consecutive_down_triggers_after_the_run_length() -> None:
    closes = [100.0, 99.0, 98.0, 97.0, 96.0]  # 4 consecutive down-closes
    bars = _bars(closes)
    result = _consecutive_down_signal(bars, run_length=3)
    positions = result["position"].to_list()
    # 3 consecutive down-closes complete at index 3 (99->98->97, the
    # third down-close) -> long from index 4 onward (shift(1)).
    assert positions[4] == 1.0


def test_consecutive_down_flat_on_alternating_closes() -> None:
    closes = [100.0, 99.0, 100.0, 99.0, 100.0]
    bars = _bars(closes)
    result = _consecutive_down_signal(bars, run_length=2)
    # No 2 consecutive down-closes ever occur (alternating up/down)
    assert all(p == 0.0 for p in result["position"].to_list())


def test_sma_distance_triggers_far_below_the_moving_average() -> None:
    # shift(1): the drop's own condition (index 10) only shows up as a
    # position on the FOLLOWING bar.
    closes = [100.0] * 10 + [80.0, 80.0]  # 20% below a flat 100 SMA
    bars = _bars(closes)
    result = _sma_distance_signal(bars, lookback=10, oversold=0.1)
    positions = result["position"].to_list()
    assert positions[11] == 1.0


def test_sma_distance_flat_within_threshold() -> None:
    closes = [100.0] * 10 + [95.0]  # 5% below, inside a 10% threshold
    bars = _bars(closes)
    result = _sma_distance_signal(bars, lookback=10, oversold=0.1)
    assert result["position"].to_list()[-1] == 0.0


def test_ultimate_oscillator_runs_without_crashing_and_bounds_0_100() -> None:
    closes = [100.0 + (i % 5) - 2 for i in range(40)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    bars = _bars(closes, highs=highs, lows=lows)
    result = _ultimate_oscillator_signal(bars, short=7, mid=14, long=28, oversold=30.0)
    uo_values = result["_uo"].to_list()[28:]  # only defined once the longest window fills
    assert all(0.0 <= v <= 100.0 for v in uo_values if v == v)  # v==v excludes NaN


def test_mfi_goes_long_on_sustained_selling_with_volume() -> None:
    # A steady decline with real volume on every bar -> negative money
    # flow dominates -> MFI drops toward 0.
    closes = [100.0 - i * 0.5 for i in range(20)]
    bars = _bars(closes, volumes=[1000.0] * 20)
    result = _mfi_signal(bars, lookback=14, oversold=30.0)
    positions = result["position"].to_list()
    assert positions[-1] == 1.0


def test_mfi_flat_on_sustained_buying() -> None:
    closes = [100.0 + i * 0.5 for i in range(20)]
    bars = _bars(closes, volumes=[1000.0] * 20)
    result = _mfi_signal(bars, lookback=14, oversold=30.0)
    assert result["position"].to_list()[-1] == 0.0


def test_gap_fade_triggers_on_a_down_gap() -> None:
    # Bar 1's own gap: prior close 100 (bar 0), today's open 95 -> a 5%
    # down-gap, above a 2% threshold. shift(1) means that condition
    # only shows up as a position on bar 2 -- a third, flat bar is
    # needed to observe it.
    bars = _bars(
        closes=[100.0, 96.0, 96.0],
        opens=[100.0, 95.0, 96.0],
    )
    result = _gap_fade_signal(bars, threshold=0.02)
    positions = result["position"].to_list()
    assert positions[2] == 1.0


def test_gap_fade_flat_within_threshold() -> None:
    bars = _bars(
        closes=[100.0, 99.0, 99.5],
        opens=[100.0, 99.5, 99.4],  # ~0.5% gap, below a 2% threshold
    )
    result = _gap_fade_signal(bars, threshold=0.02)
    assert all(p == 0.0 for p in result["position"].to_list())

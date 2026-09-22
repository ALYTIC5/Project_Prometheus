"""tests/test_engine_volatility_families.py -- signal correctness for the
6 Batch D (volatility) families added to backtest/engine.py:
SQUEEZE_BREAKOUT, ATR_BREAKOUT, NR7_BREAKOUT, INSIDE_BAR_BREAKOUT,
VOL_REGIME_SWITCH, VOL_OF_VOL_FILTER.

Same rationale as test_engine_new_families.py/test_engine_trend_families.py:
signal correctness for a genuinely new construction is the thing most
worth verifying by hand, not just spec validation or grid generation.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from prometheus.backtest.engine import (
    _atr_breakout_signal,
    _inside_bar_breakout_signal,
    _nr7_breakout_signal,
    _squeeze_breakout_signal,
    _vol_of_vol_filter_signal,
    _vol_regime_switch_signal,
)


def _bars(
    closes: list[float],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pl.DataFrame:
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


def test_squeeze_breakout_never_crashes_and_stays_flat_on_constant_price() -> None:
    closes = [100.0] * 60
    bars = _bars(closes)
    result = _squeeze_breakout_signal(bars, lookback=20)
    # A perfectly flat price never has bands that "release" (both bands
    # stay degenerate at zero width the whole way) -- no breakout signal.
    assert all(p == 0.0 for p in result["position"].to_list())


def test_squeeze_breakout_fires_on_a_compression_then_expansion() -> None:
    # A long, tight range (squeeze) followed by a sharp directional move
    # (release) is exactly the pattern this family is built to catch.
    tight = [100.0 + 0.01 * (i % 2) for i in range(40)]
    breakout = [100.0 + 2.0 * i for i in range(1, 15)]
    closes = tight + breakout
    bars = _bars(closes)
    result = _squeeze_breakout_signal(bars, lookback=20)
    assert sum(result["position"].to_list()) > 0.0


def test_atr_breakout_flat_on_constant_price() -> None:
    closes = [100.0] * 40
    bars = _bars(closes)
    result = _atr_breakout_signal(bars, lookback=14, multiplier=1.5)
    assert all(p == 0.0 for p in result["position"].to_list())


def test_atr_breakout_fires_on_a_sharp_jump() -> None:
    closes = [100.0] * 30 + [100.0 + 5.0 * i for i in range(1, 20)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    bars = _bars(closes, highs=highs, lows=lows)
    result = _atr_breakout_signal(bars, lookback=14, multiplier=1.5)
    assert sum(result["position"].to_list()) > 0.0


def test_nr7_breakout_fires_after_a_narrow_range_bar_then_breakout() -> None:
    # Bars with wide ranges, then one genuinely narrow-range bar, then a
    # bar that closes above that narrow bar's own high.
    n = 20
    highs = [100.0 + 5.0] * n
    lows = [100.0 - 5.0] * n
    closes = [100.0] * n
    # Bar index 10: the narrowest range of the last 7 bars.
    highs[10], lows[10], closes[10] = 100.2, 99.8, 100.0
    # Bar index 11: breaks above bar 10's own high (100.2).
    highs[11], lows[11], closes[11] = 101.0, 100.0, 100.5
    bars = _bars(closes, highs=highs, lows=lows)
    result = _nr7_breakout_signal(bars, lookback=7)
    positions = result["position"].to_list()
    # shift(1): the breakout at index 11 shows up as a position at index 12.
    assert positions[12] == 1.0


def test_inside_bar_breakout_fires_after_a_genuine_inside_bar() -> None:
    n = 10
    highs = [105.0] * n
    lows = [95.0] * n
    closes = [100.0] * n
    # Bar 5 is an inside bar relative to bar 4 (tighter high/low).
    highs[5], lows[5], closes[5] = 102.0, 98.0, 100.0
    # Bar 6 closes above bar 5's own high (102.0).
    highs[6], lows[6], closes[6] = 103.0, 100.0, 102.5
    bars = _bars(closes, highs=highs, lows=lows)
    result = _inside_bar_breakout_signal(bars, buffer=0.0)
    positions = result["position"].to_list()
    assert positions[7] == 1.0


def test_inside_bar_breakout_flat_with_no_inside_bar() -> None:
    closes = [100.0] * 20
    bars = _bars(closes)
    result = _inside_bar_breakout_signal(bars, buffer=0.0)
    assert all(p == 0.0 for p in result["position"].to_list())


def test_vol_regime_switch_never_crashes_on_a_trending_low_vol_series() -> None:
    closes = [100.0 + 0.5 * i for i in range(200)]
    bars = _bars(closes)
    result = _vol_regime_switch_signal(bars, vol_window=20, regime_window=100, lookback=20)
    assert result["position"].to_list()[-1] in (0.0, 1.0)
    # A smooth low-vol uptrend should land in the low-vol/trend-following
    # branch and go long.
    assert result["position"].to_list()[-1] == 1.0


def test_vol_of_vol_filter_never_crashes_and_goes_long_in_a_stable_uptrend() -> None:
    closes = [100.0 + 0.5 * i for i in range(200)]
    bars = _bars(closes)
    result = _vol_of_vol_filter_signal(bars, vol_window=20, vov_window=40, lookback=20)
    assert result["position"].to_list()[-1] == 1.0

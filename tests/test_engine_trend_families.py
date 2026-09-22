"""tests/test_engine_trend_families.py -- signal correctness for the 14
Batch C (trend) families added to backtest/engine.py: EMA_CROSSOVER,
TRIPLE_MA_ALIGNMENT, DEMA_CROSSOVER, HULL_MA_TREND, KAMA_TREND, TSMOM,
ADX_DI_CROSSOVER, AROON_CROSSOVER, ICHIMOKU_BREAKOUT, VORTEX,
LINREG_SLOPE, CHANDELIER_EXIT, SMA200_FILTER, MA_RIBBON.

Same rationale as test_engine_new_families.py (Batch B): signal
correctness for a genuinely new construction is the thing most worth
verifying by hand, not just spec validation or grid generation.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from prometheus.backtest.engine import (
    _adx_di_signal,
    _aroon_signal,
    _chandelier_exit_signal,
    _dema_crossover_signal,
    _ema_crossover_signal,
    _hull_ma_signal,
    _ichimoku_signal,
    _kama_signal,
    _linreg_slope_signal,
    _ma_ribbon_signal,
    _sma200_filter_signal,
    _triple_ma_alignment_signal,
    _tsmom_signal,
    _vortex_signal,
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


def _uptrend(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * i for i in range(n)]


def _downtrend(n: int, start: float = 200.0, step: float = 1.0) -> list[float]:
    return [start - step * i for i in range(n)]


def test_ema_crossover_goes_long_in_a_sustained_uptrend() -> None:
    closes = _uptrend(80)
    bars = _bars(closes)
    result = _ema_crossover_signal(bars, fast=5, slow=20)
    assert result["position"].to_list()[-1] == 1.0


def test_ema_crossover_stays_flat_in_a_sustained_downtrend() -> None:
    closes = _downtrend(80)
    bars = _bars(closes)
    result = _ema_crossover_signal(bars, fast=5, slow=20)
    assert result["position"].to_list()[-1] == 0.0


def test_triple_ma_alignment_requires_all_three_in_order() -> None:
    closes = _uptrend(80)
    bars = _bars(closes)
    result = _triple_ma_alignment_signal(bars, fast=5, mid=15, slow=30)
    assert result["position"].to_list()[-1] == 1.0


def test_triple_ma_alignment_flat_when_flat_price() -> None:
    closes = [100.0] * 80
    bars = _bars(closes)
    result = _triple_ma_alignment_signal(bars, fast=5, mid=15, slow=30)
    assert result["position"].to_list()[-1] == 0.0


def test_dema_crossover_goes_long_in_a_sustained_uptrend() -> None:
    closes = _uptrend(100)
    bars = _bars(closes)
    result = _dema_crossover_signal(bars, fast=10, slow=30)
    assert result["position"].to_list()[-1] == 1.0


def test_hull_ma_rises_and_goes_long_in_a_sustained_uptrend() -> None:
    closes = _uptrend(60)
    bars = _bars(closes)
    result = _hull_ma_signal(bars, lookback=16)
    assert result["position"].to_list()[-1] == 1.0


def test_hull_ma_flat_on_constant_price() -> None:
    closes = [100.0] * 60
    bars = _bars(closes)
    result = _hull_ma_signal(bars, lookback=16)
    # A flat price never has a rising HMA -- always flat.
    assert result["position"].to_list()[-1] == 0.0


def test_kama_tracks_a_sustained_uptrend_long() -> None:
    closes = _uptrend(60)
    bars = _bars(closes)
    result = _kama_signal(bars, lookback=10, fast_sc=2, slow_sc=30)
    assert result["position"].to_list()[-1] == 1.0


def test_kama_returns_all_flat_when_shorter_than_lookback() -> None:
    closes = _uptrend(5)
    bars = _bars(closes)
    result = _kama_signal(bars, lookback=10, fast_sc=2, slow_sc=30)
    assert all(p == 0.0 for p in result["position"].to_list())


def test_tsmom_goes_long_when_trailing_return_positive() -> None:
    closes = _uptrend(120)
    bars = _bars(closes)
    result = _tsmom_signal(bars, lookback_days=90, skip_days=5)
    assert result["position"].to_list()[-1] == 1.0


def test_tsmom_stays_flat_when_trailing_return_negative() -> None:
    closes = _downtrend(120)
    bars = _bars(closes)
    result = _tsmom_signal(bars, lookback_days=90, skip_days=5)
    assert result["position"].to_list()[-1] == 0.0


def test_adx_di_goes_long_in_a_strong_directional_uptrend() -> None:
    n = 60
    closes = _uptrend(n, step=2.0)
    highs = [c + 1.0 for c in closes]
    lows = [c - 0.2 for c in closes]
    bars = _bars(closes, highs=highs, lows=lows)
    result = _adx_di_signal(bars, lookback=14)
    assert result["position"].to_list()[-1] == 1.0


def test_adx_di_flat_when_no_directional_trend() -> None:
    n = 60
    closes = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    bars = _bars(closes, highs=highs, lows=lows)
    result = _adx_di_signal(bars, lookback=14)
    # No directional movement at all -- ADX stays near zero, never > 25.
    assert result["position"].to_list()[-1] == 0.0


def test_aroon_goes_long_when_recent_bar_made_the_window_high() -> None:
    n = 40
    closes = _uptrend(n)
    bars = _bars(closes)
    result = _aroon_signal(bars, lookback=14)
    assert result["position"].to_list()[-1] == 1.0


def test_ichimoku_goes_long_above_the_shifted_cloud() -> None:
    n = 150
    closes = _uptrend(n, step=1.5)
    bars = _bars(closes)
    result = _ichimoku_signal(bars, conversion=9, base=26, span_b=52)
    assert result["position"].to_list()[-1] == 1.0


def test_vortex_goes_long_in_a_sustained_uptrend() -> None:
    n = 40
    closes = _uptrend(n)
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    bars = _bars(closes, highs=highs, lows=lows)
    result = _vortex_signal(bars, lookback=14)
    assert result["position"].to_list()[-1] == 1.0


def test_linreg_slope_positive_in_a_sustained_uptrend() -> None:
    closes = _uptrend(40)
    bars = _bars(closes)
    result = _linreg_slope_signal(bars, lookback=20)
    assert result["position"].to_list()[-1] == 1.0


def test_linreg_slope_negative_in_a_sustained_downtrend() -> None:
    closes = _downtrend(40)
    bars = _bars(closes)
    result = _linreg_slope_signal(bars, lookback=20)
    assert result["position"].to_list()[-1] == 0.0


def test_chandelier_exit_long_while_price_holds_above_the_stop() -> None:
    closes = _uptrend(40)
    bars = _bars(closes)
    result = _chandelier_exit_signal(bars, lookback=22, multiplier=3.0)
    assert result["position"].to_list()[-1] == 1.0


def test_chandelier_exit_flat_after_a_sharp_drop_below_the_stop() -> None:
    closes = _uptrend(40) + [50.0, 50.0]
    bars = _bars(closes)
    result = _chandelier_exit_signal(bars, lookback=22, multiplier=3.0)
    assert result["position"].to_list()[-1] == 0.0


def test_sma200_filter_long_above_its_own_sma() -> None:
    closes = _uptrend(60)
    bars = _bars(closes)
    result = _sma200_filter_signal(bars, lookback=50)
    assert result["position"].to_list()[-1] == 1.0


def test_ma_ribbon_long_when_aligned_and_expanding() -> None:
    # A plain linear uptrend's SMA spread converges to a CONSTANT once
    # every window is fully inside the linear regime (rolling means
    # separated by a fixed lag advance in lockstep) -- never "expanding"
    # by this signal's own stricter definition. An accelerating
    # (quadratic) uptrend keeps the spread genuinely growing bar over
    # bar, which is what this family is built to detect.
    closes = [100.0 + 0.02 * i * i for i in range(60)]
    bars = _bars(closes)
    result = _ma_ribbon_signal(bars, short=5, mid=15, long=30)
    assert result["position"].to_list()[-1] == 1.0


def test_ma_ribbon_flat_on_constant_price() -> None:
    closes = [100.0] * 60
    bars = _bars(closes)
    result = _ma_ribbon_signal(bars, short=5, mid=15, long=30)
    assert result["position"].to_list()[-1] == 0.0

"""backtest/engine.py's classic-template signal generators beyond
MOMENTUM: BOLLINGER, VOL_BREAKOUT, RSI, MACD, STOCHASTIC, PARABOLIC_SAR,
KELTNER, WILLIAMS_R, CCI, AWESOME_OSCILLATOR, SUPERTREND, and TRIX
(every family after the first three added later with the same
justification). Real synthetic price paths, same _bar_row pattern
tests/test_null_strategies.py already establishes."""
from __future__ import annotations

import polars as pl

from prometheus.backtest.engine import run_backtest, signal_for
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec
from tests.test_null_strategies import _bar_row

_SYMBOL = "BTC/USDT"


def _bollinger_spec(lookback: int = 10, multiplier: float = 2.0) -> StrategySpec:
    return StrategySpec(
        family="BOLLINGER",
        symbol=_SYMBOL,
        timeframe="1d",
        lookback_window=lookback,
        band_multiplier=multiplier,
        expected_horizon=lookback,
    )


def _breakout_spec(breakout_window: int = 20, exit_window: int = 10) -> StrategySpec:
    return StrategySpec(
        family="VOL_BREAKOUT",
        symbol=_SYMBOL,
        timeframe="1d",
        breakout_window=breakout_window,
        exit_window=exit_window,
        expected_horizon=breakout_window,
    )


def _rsi_spec(lookback: int = 14, oversold: float = 30.0) -> StrategySpec:
    return StrategySpec(
        family="RSI",
        symbol=_SYMBOL,
        timeframe="1d",
        rsi_lookback=lookback,
        rsi_oversold=oversold,
        expected_horizon=lookback,
    )


def _macd_spec(fast: int = 12, slow: int = 26, signal: int = 9) -> StrategySpec:
    return StrategySpec(
        family="MACD",
        symbol=_SYMBOL,
        timeframe="1d",
        macd_fast=fast,
        macd_slow=slow,
        macd_signal=signal,
        expected_horizon=slow,
    )


def _stochastic_spec(lookback: int = 14, oversold: float = 20.0) -> StrategySpec:
    return StrategySpec(
        family="STOCHASTIC",
        symbol=_SYMBOL,
        timeframe="1d",
        stoch_lookback=lookback,
        stoch_oversold=oversold,
        expected_horizon=lookback,
    )


def _sar_spec(af_start: float = 0.02, af_increment: float = 0.02, af_max: float = 0.2) -> StrategySpec:
    return StrategySpec(
        family="PARABOLIC_SAR",
        symbol=_SYMBOL,
        timeframe="1d",
        sar_af_start=af_start,
        sar_af_increment=af_increment,
        sar_af_max=af_max,
        expected_horizon=10,
    )


def _keltner_spec(lookback: int = 20, multiplier: float = 2.0) -> StrategySpec:
    return StrategySpec(
        family="KELTNER",
        symbol=_SYMBOL,
        timeframe="1d",
        keltner_lookback=lookback,
        keltner_multiplier=multiplier,
        expected_horizon=lookback,
    )


def _williams_r_spec(lookback: int = 14, oversold: float = -80.0) -> StrategySpec:
    return StrategySpec(
        family="WILLIAMS_R",
        symbol=_SYMBOL,
        timeframe="1d",
        williams_lookback=lookback,
        williams_oversold=oversold,
        expected_horizon=lookback,
    )


def _cci_spec(lookback: int = 20, oversold: float = -100.0) -> StrategySpec:
    return StrategySpec(
        family="CCI",
        symbol=_SYMBOL,
        timeframe="1d",
        cci_lookback=lookback,
        cci_oversold=oversold,
        expected_horizon=lookback,
    )


def _ao_spec(fast: int = 5, slow: int = 34) -> StrategySpec:
    return StrategySpec(
        family="AWESOME_OSCILLATOR",
        symbol=_SYMBOL,
        timeframe="1d",
        ao_fast=fast,
        ao_slow=slow,
        expected_horizon=slow,
    )


def _supertrend_spec(lookback: int = 10, multiplier: float = 3.0) -> StrategySpec:
    return StrategySpec(
        family="SUPERTREND",
        symbol=_SYMBOL,
        timeframe="1d",
        supertrend_lookback=lookback,
        supertrend_multiplier=multiplier,
        expected_horizon=lookback,
    )


def _trix_spec(lookback: int = 15) -> StrategySpec:
    return StrategySpec(
        family="TRIX",
        symbol=_SYMBOL,
        timeframe="1d",
        trix_lookback=lookback,
        expected_horizon=lookback,
    )


def _flat_bars(n: int, price: float = 100.0) -> pl.DataFrame:
    return pl.DataFrame([_bar_row(_SYMBOL, i, price) for i in range(n)])


def test_bollinger_never_crossing_bands_never_trades() -> None:
    """Identical close every bar: std == 0, bands collapse to the mean
    itself, close is never strictly below the lower band -- a genuinely
    null case, same shape as the momentum null test."""
    bars = _flat_bars(40)
    spec = _bollinger_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_bollinger_enters_long_on_a_real_dip_below_the_lower_band() -> None:
    """A flat price series with one sharp, real dip: the dip bar (and the
    bars right after, before the rolling mean/std recover) should push
    close below the lower band and produce a real long entry somewhere
    in the series -- not asserting exact bar timing, just that turnover
    is genuinely nonzero, proving the signal actually fires."""
    prices = [100.0] * 15 + [80.0] * 5 + [100.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _bollinger_spec(lookback=10, multiplier=1.5)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_bollinger_no_lookahead_planted_future_dip_is_unreachable() -> None:
    """A dip planted only in the LAST bar must not affect any position
    held before that bar -- the shift(1) discipline test_no_lookahead.py
    already applies to momentum, mirrored here for Bollinger."""
    prices = [100.0] * 30 + [1.0]  # extreme dip only on the final bar
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _bollinger_spec(lookback=10, multiplier=1.5)
    signaled = signal_for(bars, spec)
    # The position held DURING the final bar is decided from bars before
    # it -- the plant on the final bar's own close can only affect a
    # position on some LATER bar, which does not exist here.
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_vol_breakout_never_breaking_out_never_trades() -> None:
    bars = _flat_bars(40)
    spec = _breakout_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_vol_breakout_enters_long_on_a_real_breakout_and_persists() -> None:
    """Flat, then a genuine new high, then a plateau -- Donchian entry is
    STATEFUL (persists after the breakout bar, not re-evaluated fresh
    every bar the way momentum/Bollinger are), so this asserts the
    position stays long across the plateau, not just on the breakout bar
    itself."""
    prices = [100.0] * 25 + [150.0] + [150.0] * 14
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _breakout_spec(breakout_window=20, exit_window=10)
    signaled = signal_for(bars, spec)
    positions = signaled["position"].to_list()
    assert sum(positions) > 0.0
    # Once entered, position should still be held several bars later
    # (persisted via forward_fill, not a one-bar blip).
    assert positions[-1] == 1.0


def test_vol_breakout_exits_on_a_real_breakdown() -> None:
    """Breakout up, hold, then a genuine breakdown below the exit
    channel -- position must return to flat, proving the exit condition
    (not just the entry) actually fires."""
    prices = [100.0] * 25 + [150.0] * 15 + [50.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _breakout_spec(breakout_window=20, exit_window=10)
    signaled = signal_for(bars, spec)
    assert signaled["position"].to_list()[-1] == 0.0


def test_vol_breakout_no_lookahead_planted_future_breakout_is_unreachable() -> None:
    prices = [100.0] * 30 + [1000.0]  # extreme breakout only on the final bar
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _breakout_spec(breakout_window=20, exit_window=10)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_rsi_never_dipping_never_trades() -> None:
    """Identical close every bar: avg_gain and avg_loss are both 0.0, so
    RSI is 0/0 == NaN in polars, and `NaN < oversold` is false for every
    bar -- a genuinely null case, same shape as the other families'
    flat-price tests."""
    bars = _flat_bars(40)
    spec = _rsi_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_rsi_enters_long_on_a_real_dip() -> None:
    """A sustained decline drives avg_loss well above avg_gain, pushing
    RSI below the oversold threshold and producing a real long entry --
    not asserting exact bar timing, just that turnover is genuinely
    nonzero, proving the signal actually fires."""
    prices = [100.0] * 5 + [100.0 - i * 3 for i in range(1, 16)] + [55.0] * 10
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _rsi_spec(lookback=14, oversold=30.0)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_rsi_no_lookahead_planted_future_dip_is_unreachable() -> None:
    prices = [100.0] * 30 + [1.0]  # extreme dip only on the final bar
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _rsi_spec(lookback=14, oversold=30.0)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_macd_flat_prices_never_trades() -> None:
    """Identical close every bar: both EMAs equal the constant price, the
    MACD line is exactly 0.0, and the signal line (an EMA of a constant
    0.0 series) is also exactly 0.0 -- `0.0 > 0.0` is false for every
    bar, a genuinely null case."""
    bars = _flat_bars(60)
    spec = _macd_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_macd_enters_long_on_a_sustained_uptrend() -> None:
    """A sustained uptrend pulls the fast EMA above the slow EMA harder
    than the signal line (a further-smoothed EMA of the MACD line) can
    keep up with, producing a real long entry -- not asserting exact bar
    timing, just that turnover is genuinely nonzero."""
    prices = [100.0 + i * 2 for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _macd_spec(fast=5, slow=13, signal=5)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_macd_no_lookahead_planted_future_spike_is_unreachable() -> None:
    prices = [100.0] * 40 + [1000.0]  # extreme spike only on the final bar
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _macd_spec(fast=5, slow=13, signal=5)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_stochastic_never_dipping_never_trades() -> None:
    bars = _flat_bars(40)
    spec = _stochastic_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_stochastic_enters_long_on_a_real_dip() -> None:
    prices = [100.0] * 15 + [80.0] * 5 + [100.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _stochastic_spec(lookback=14, oversold=20.0)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_stochastic_no_lookahead_planted_future_dip_is_unreachable() -> None:
    prices = [100.0] * 30 + [1.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _stochastic_spec(lookback=14, oversold=20.0)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_sar_starts_long_and_flips_on_a_real_breakdown() -> None:
    """A sustained uptrend keeps SAR in an uptrend (position 1.0);
    a sharp, sustained breakdown must flip it to downtrend (0.0) --
    proving the reversal condition actually fires, not just the
    always-long default."""
    prices = [100.0 + i for i in range(20)] + [120.0 - i * 3 for i in range(1, 16)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _sar_spec()
    signaled = signal_for(bars, spec)
    positions = signaled["position"].to_list()
    assert positions[5] == 1.0
    assert positions[-1] == 0.0


def test_sar_no_lookahead_planted_future_spike_is_unreachable() -> None:
    prices = [100.0] * 30 + [1000.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _sar_spec()
    signaled = signal_for(bars, spec)
    baseline_rows = [_bar_row(_SYMBOL, i, 100.0) for i in range(31)]
    baseline_signaled = signal_for(pl.DataFrame(baseline_rows), spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    baseline_positions_before_plant = baseline_signaled["position"].to_list()[:-1]
    assert positions_before_plant == baseline_positions_before_plant


def test_keltner_never_breaking_out_never_trades() -> None:
    bars = _flat_bars(40)
    spec = _keltner_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_keltner_enters_long_on_a_real_breakout_and_persists() -> None:
    prices = [100.0] * 25 + [150.0] + [150.0] * 14
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _keltner_spec(lookback=20, multiplier=1.5)
    signaled = signal_for(bars, spec)
    positions = signaled["position"].to_list()
    assert sum(positions) > 0.0
    assert positions[-1] == 1.0


def test_keltner_exits_on_a_real_breakdown() -> None:
    prices = [100.0] * 25 + [150.0] * 15 + [50.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _keltner_spec(lookback=20, multiplier=1.5)
    signaled = signal_for(bars, spec)
    assert signaled["position"].to_list()[-1] == 0.0


def test_keltner_no_lookahead_planted_future_breakout_is_unreachable() -> None:
    prices = [100.0] * 30 + [1000.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _keltner_spec(lookback=20, multiplier=1.5)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_williams_r_never_dipping_never_trades() -> None:
    bars = _flat_bars(40)
    spec = _williams_r_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_williams_r_enters_long_on_a_real_dip() -> None:
    prices = [100.0] * 15 + [80.0] * 5 + [100.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _williams_r_spec(lookback=14, oversold=-80.0)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_williams_r_no_lookahead_planted_future_dip_is_unreachable() -> None:
    prices = [100.0] * 30 + [1.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _williams_r_spec(lookback=14, oversold=-80.0)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_cci_never_dipping_never_trades() -> None:
    bars = _flat_bars(40)
    spec = _cci_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_cci_enters_long_on_a_real_dip() -> None:
    prices = [100.0] * 25 + [70.0] * 5 + [100.0] * 15
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _cci_spec(lookback=20, oversold=-100.0)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_cci_no_lookahead_planted_future_dip_is_unreachable() -> None:
    prices = [100.0] * 35 + [1.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _cci_spec(lookback=20, oversold=-100.0)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_awesome_oscillator_flat_prices_never_trades() -> None:
    bars = _flat_bars(60)
    spec = _ao_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_awesome_oscillator_enters_long_on_a_sustained_uptrend() -> None:
    prices = [100.0 + i * 2 for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _ao_spec(fast=5, slow=34)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_awesome_oscillator_no_lookahead_planted_future_spike_is_unreachable() -> None:
    prices = [100.0] * 60 + [1000.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _ao_spec(fast=5, slow=34)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_supertrend_starts_long_and_flips_on_a_real_breakdown() -> None:
    prices = [100.0 + i for i in range(20)] + [120.0 - i * 3 for i in range(1, 16)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _supertrend_spec()
    signaled = signal_for(bars, spec)
    positions = signaled["position"].to_list()
    assert positions[15] == 1.0
    assert positions[-1] == 0.0


def test_supertrend_no_lookahead_planted_future_spike_is_unreachable() -> None:
    prices = [100.0] * 30 + [1000.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _supertrend_spec()
    baseline_rows = [_bar_row(_SYMBOL, i, 100.0) for i in range(31)]
    signaled = signal_for(bars, spec)
    baseline_signaled = signal_for(pl.DataFrame(baseline_rows), spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    baseline_positions_before_plant = baseline_signaled["position"].to_list()[:-1]
    assert positions_before_plant == baseline_positions_before_plant


def test_trix_flat_prices_never_trades() -> None:
    bars = _flat_bars(60)
    spec = _trix_spec()
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0


def test_trix_enters_long_on_a_sustained_uptrend() -> None:
    prices = [100.0 + i * 2 for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _trix_spec(lookback=15)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, rows[-1]["available_at"])
    assert result.turnover > 0.0


def test_trix_no_lookahead_planted_future_spike_is_unreachable() -> None:
    prices = [100.0] * 60 + [1000.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    spec = _trix_spec(lookback=15)
    signaled = signal_for(bars, spec)
    positions_before_plant = signaled["position"].to_list()[:-1]
    assert all(p == 0.0 for p in positions_before_plant)


def test_engine_agrees_with_signal_for_across_all_thirteen_families() -> None:
    """run_backtest's own turnover must equal the sum of |position
    changes| in signal_for()'s own output -- a real end-to-end
    consistency check that the engine trades exactly the position series
    the signal generator reports, for every family, not just MOMENTUM."""
    prices = [100.0 + (i % 7) for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    pit = PointInTimeFrame(bars)
    for spec in (
        _bollinger_spec(), _breakout_spec(), _rsi_spec(), _macd_spec(),
        _stochastic_spec(), _sar_spec(), _keltner_spec(),
        _williams_r_spec(), _cci_spec(), _ao_spec(), _supertrend_spec(), _trix_spec(),
    ):
        result = run_backtest(pit, spec, rows[-1]["available_at"])
        positions = signal_for(bars, spec)["position"].to_list()
        expected_turnover = sum(
            abs(positions[i] - positions[i - 1]) for i in range(1, len(positions))
        )
        assert result.turnover == expected_turnover

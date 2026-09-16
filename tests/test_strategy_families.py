"""backtest/engine.py's BOLLINGER and VOL_BREAKOUT signal generators
(PROMPT 6's two new classic templates). Real synthetic price paths, same
_bar_row pattern tests/test_null_strategies.py already establishes."""
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


def test_engine_agrees_with_signal_for_across_all_three_families() -> None:
    """run_backtest's own turnover must equal the sum of |position
    changes| in signal_for()'s own output -- a real end-to-end
    consistency check that the engine trades exactly the position series
    the signal generator reports, for every family, not just MOMENTUM."""
    prices = [100.0 + (i % 7) for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    pit = PointInTimeFrame(bars)
    for spec in (_bollinger_spec(), _breakout_spec()):
        result = run_backtest(pit, spec, rows[-1]["available_at"])
        positions = signal_for(bars, spec)["position"].to_list()
        expected_turnover = sum(
            abs(positions[i] - positions[i - 1]) for i in range(1, len(positions))
        )
        assert result.turnover == expected_turnover

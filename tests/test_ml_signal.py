"""prometheus/backtest/ml_signal.py's random_forest_signal -- the
RANDOM_FOREST family's walk-forward-retrained signal. Real synthetic
price paths, same _bar_row pattern tests/test_null_strategies.py
already establishes."""
from __future__ import annotations

import polars as pl

from prometheus.backtest.engine import run_backtest, signal_for
from prometheus.backtest.ml_signal import random_forest_signal
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec
from tests.test_null_strategies import _bar_row

_SYMBOL = "BTC/USDT"


def _rf_spec(train_window: int = 40, retrain_interval: int = 10, threshold: float = 0.5) -> StrategySpec:
    return StrategySpec(
        family="RANDOM_FOREST", symbol=_SYMBOL, timeframe="1d",
        rf_train_window=train_window, rf_retrain_interval=retrain_interval,
        rf_predict_threshold=threshold, expected_horizon=1,
    )


def _sawtooth_bars(n: int) -> pl.DataFrame:
    """A perfectly alternating up/down series -- f_ret1's own sign is a
    trivially perfect (if trivial) predictor of the next bar's
    direction, giving the model something real to learn without needing
    hundreds of rows."""
    prices = []
    price = 100.0
    for i in range(n):
        price = price + 1.0 if i % 2 == 0 else price - 1.0
        prices.append(price)
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    return pl.DataFrame(rows)


def test_flat_before_first_checkpoint_never_trades() -> None:
    bars = _sawtooth_bars(30)  # shorter than train_window -- no checkpoint reached
    spec = _rf_spec(train_window=40, retrain_interval=10)
    signaled = signal_for(bars, spec)
    assert all(p == 0.0 for p in signaled["position"].to_list())


def test_produces_real_trades_once_trained() -> None:
    bars = _sawtooth_bars(90)
    spec = _rf_spec(train_window=40, retrain_interval=10)
    pit = PointInTimeFrame(bars)
    result = run_backtest(pit, spec, bars["available_at"][-1])
    assert result.turnover > 0.0


def test_no_lookahead_planted_future_spike_is_unreachable() -> None:
    """A dip planted only in the LAST bar must not affect any position
    held before that bar -- same convention every other family's signal
    is tested against, now exercised through the walk-forward loop."""
    n = 90
    baseline_prices = []
    price = 100.0
    for i in range(n):
        price = price + 1.0 if i % 2 == 0 else price - 1.0
        baseline_prices.append(price)
    spiked_prices = list(baseline_prices)
    spiked_prices[-1] = 1.0  # extreme dip only on the final bar

    baseline_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(baseline_prices)]
    spiked_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(spiked_prices)]
    baseline_signaled = signal_for(pl.DataFrame(baseline_rows), _rf_spec(train_window=40, retrain_interval=10))
    spiked_signaled = signal_for(pl.DataFrame(spiked_rows), _rf_spec(train_window=40, retrain_interval=10))
    positions_before_plant = spiked_signaled["position"].to_list()[:-1]
    baseline_positions_before_plant = baseline_signaled["position"].to_list()[:-1]
    assert positions_before_plant == baseline_positions_before_plant


def test_engine_dispatches_to_random_forest_signal() -> None:
    bars = _sawtooth_bars(90)
    spec = _rf_spec(train_window=40, retrain_interval=10)
    direct = random_forest_signal(bars, 40, 10, 0.5)["position"].to_list()
    via_engine = signal_for(bars, spec)["position"].to_list()
    assert direct == via_engine


def test_direction_never_predicted_falls_back_to_flat() -> None:
    """A strictly monotonic decline never gives the model a real up
    example to learn from -- model.classes_ never contains 1.0 for any
    checkpoint, and the loop must not crash on that, staying flat
    instead."""
    prices = [100.0 - i for i in range(60)]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    signaled = random_forest_signal(bars, 30, 10, 0.5)
    assert all(p == 0.0 for p in signaled["position"].to_list())

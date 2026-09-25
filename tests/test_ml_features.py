"""prometheus/backtest/ml_features.py's build_feature_frame -- the
RANDOM_FOREST family's feature engineering. Real synthetic price paths,
same _bar_row pattern tests/test_null_strategies.py already
establishes."""
from __future__ import annotations

import polars as pl

from prometheus.backtest.ml_features import FEATURE_COLUMNS, build_feature_frame
from tests.test_null_strategies import _bar_row

_SYMBOL = "BTC/USDT"


def test_feature_columns_are_produced() -> None:
    rows = [_bar_row(_SYMBOL, i, 100.0 + i) for i in range(40)]
    bars = pl.DataFrame(rows)
    frame = build_feature_frame(bars)
    for column in FEATURE_COLUMNS:
        assert column in frame.columns
    assert "label" in frame.columns


def test_label_is_shifted_forward_and_null_on_the_final_row() -> None:
    prices = [100.0, 105.0, 103.0, 110.0]
    rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(prices)]
    bars = pl.DataFrame(rows)
    frame = build_feature_frame(bars)
    labels = frame["label"].to_list()
    # bar 0 -> 1 rises (100 -> 105): label 1.0
    # bar 1 -> 2 falls (105 -> 103): label 0.0
    # bar 2 -> 3 rises (103 -> 110): label 1.0
    # bar 3: no next bar -- label must be null, never fabricated
    assert labels[0] == 1.0
    assert labels[1] == 0.0
    assert labels[2] == 1.0
    assert labels[3] is None


def test_features_have_no_lookahead_planted_future_spike_is_unreachable() -> None:
    """A dip planted only in the LAST bar must not affect any FEATURE
    value at any earlier bar -- same no-lookahead convention every other
    family's signal function is tested against. (label is exempt: it is
    training-only and legitimately looks one bar forward by
    construction, but is never itself a feature.)"""
    import math
    baseline_prices = [100.0] * 30
    spiked_prices = [100.0] * 29 + [1.0]
    baseline_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(baseline_prices)]
    spiked_rows = [_bar_row(_SYMBOL, i, p) for i, p in enumerate(spiked_prices)]
    baseline_frame = build_feature_frame(pl.DataFrame(baseline_rows))
    spiked_frame = build_feature_frame(pl.DataFrame(spiked_rows))
    for column in FEATURE_COLUMNS:
        baseline_values = baseline_frame[column].to_list()[:-1]
        spiked_values = spiked_frame[column].to_list()[:-1]
        # Compare element-wise, handling NaN properly (NaN == NaN should be True)
        for i, (b, s) in enumerate(zip(baseline_values, spiked_values, strict=False)):
            b_nan = isinstance(b, float) and math.isnan(b)
            s_nan = isinstance(s, float) and math.isnan(s)
            if b_nan and s_nan:
                continue
            elif b_nan or s_nan:
                raise AssertionError(f"{column}[{i}] leaked the future spike")
            else:
                assert b == s, f"{column}[{i}] leaked the future spike"

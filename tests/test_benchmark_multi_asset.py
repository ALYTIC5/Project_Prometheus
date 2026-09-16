"""backtest/benchmark.py's compute_benchmark_curve -- Law 8's "equal-weight
for multi-asset, 100% for single-asset" is one formula, not two code
paths; these tests prove the len==1 case is unchanged and the multi-asset
case actually splits capital evenly. Pure polars/synthetic data, no DB,
same style as tests/laws/test_no_lookahead.py.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.benchmark import STARTING_CAPITAL, compute_benchmark_curve
from prometheus.backtest.costs import apply_cost
from prometheus.data.schema import PointInTimeFrame

_START = datetime(2023, 1, 1, tzinfo=UTC)


def _flat_bars(symbol: str, n: int, price: float) -> list[dict]:
    rows = []
    for i in range(n):
        event_time = _START + timedelta(days=i)
        rows.append(
            {
                "symbol": symbol,
                "timeframe": "1d",
                "event_time": event_time,
                "available_at": event_time + timedelta(minutes=5),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1000.0,
            }
        )
    return rows


def test_single_symbol_matches_100_percent_allocation() -> None:
    """len(symbols)==1 must be bit-identical to a single asset getting the
    full STARTING_CAPITAL -- the len==1 collapse of the equal-weight
    formula, not a separate branch that could drift from it."""
    rows = _flat_bars("BTC/USDT", 10, 100.0)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    cutoff = rows[-1]["available_at"]

    result = compute_benchmark_curve(pit, ["BTC/USDT"], cutoff)

    expected_equity = STARTING_CAPITAL - apply_cost(STARTING_CAPITAL)
    assert all(equity == expected_equity for _, equity in result.equity_curve)
    assert result.final_value == expected_equity
    assert result.max_drawdown_pct == 0.0


def test_two_symbols_split_capital_equally() -> None:
    rows = _flat_bars("BTC/USDT", 5, 100.0) + _flat_bars("ETH/USDT", 5, 50.0)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    cutoff = _START + timedelta(days=4, minutes=5)

    result = compute_benchmark_curve(pit, ["BTC/USDT", "ETH/USDT"], cutoff)

    per_symbol_share = STARTING_CAPITAL / 2
    expected_leg = per_symbol_share - apply_cost(per_symbol_share)
    # Flat prices on both legs -- the combined curve should be constant at
    # exactly the sum of the two legs' post-entry-cost values, every tick.
    assert all(equity == pytest.approx(expected_leg * 2) for _, equity in result.equity_curve)
    assert result.final_value == pytest.approx(expected_leg * 2)
    assert result.max_drawdown_pct == pytest.approx(0.0)


def test_two_symbols_combined_curve_sums_both_legs_at_a_shared_timestamp() -> None:
    """Not just flat-price sanity -- with real price movement, the
    combined equity at every timestamp must equal exactly the sum of each
    symbol's own contribution. A linear cost_model (proportional to
    notional, like apply_cost) means halving the capital allocated to a
    symbol exactly halves its equity at every point -- that's what lets an
    independently-computed full-capital run stand in for "this symbol's
    half-share leg" once divided by two.
    """
    btc_rows = _flat_bars("BTC/USDT", 5, 100.0)
    for i, row in enumerate(btc_rows):
        row["close"] = row["open"] = row["high"] = row["low"] = 100.0 * (1 + 0.01 * i)
    eth_rows = _flat_bars("ETH/USDT", 5, 50.0)
    for i, row in enumerate(eth_rows):
        row["close"] = row["open"] = row["high"] = row["low"] = 50.0 * (1 - 0.02 * i)

    pit = PointInTimeFrame(pl.DataFrame(btc_rows + eth_rows))
    cutoff = _START + timedelta(days=4, minutes=5)

    def linear_cost_model(notional: float) -> float:
        return notional * 0.001

    btc_full = compute_benchmark_curve(pit, ["BTC/USDT"], cutoff, cost_model=linear_cost_model)
    eth_full = compute_benchmark_curve(pit, ["ETH/USDT"], cutoff, cost_model=linear_cost_model)
    combined = compute_benchmark_curve(
        pit, ["BTC/USDT", "ETH/USDT"], cutoff, cost_model=linear_cost_model
    )

    btc_half = {day: equity / 2 for day, equity in btc_full.equity_curve}
    eth_half = {day: equity / 2 for day, equity in eth_full.equity_curve}

    assert combined.equity_curve  # non-empty, or the comparison below is vacuous
    for day, equity in combined.equity_curve:
        expected = btc_half.get(day, 0.0) + eth_half.get(day, 0.0)
        assert equity == pytest.approx(expected)


def test_a_symbol_with_no_data_yet_is_excluded_not_fatal() -> None:
    """A symbol with zero bars as-of the cutoff (newly listed, no history
    yet) must not blow up the whole benchmark -- it's simply absent from
    the combined curve, same as compute_benchmark_curve's existing
    single-asset empty-bars behavior."""
    rows = _flat_bars("BTC/USDT", 5, 100.0)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    cutoff = rows[-1]["available_at"]

    result = compute_benchmark_curve(pit, ["BTC/USDT", "NOTLISTEDYET/USDT"], cutoff)

    # Only BTC contributed -- equity reflects BTC's own post-entry-cost
    # half-share growth, not a crash or a silently-fabricated second leg.
    assert result.equity_curve
    assert result.final_value > 0


def test_rejects_empty_symbol_list() -> None:
    rows = _flat_bars("BTC/USDT", 3, 100.0)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    with pytest.raises(ValueError, match="at least one symbol"):
        compute_benchmark_curve(pit, [], rows[-1]["available_at"])

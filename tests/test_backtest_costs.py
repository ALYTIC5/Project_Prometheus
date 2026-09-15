from __future__ import annotations

from prometheus.backtest.costs import SLIPPAGE_BPS, TAKER_FEE_BPS, TOTAL_COST_BPS, apply_cost


def test_total_cost_is_the_sum_of_fee_and_slippage() -> None:
    assert TOTAL_COST_BPS == TAKER_FEE_BPS + SLIPPAGE_BPS


def test_apply_cost_scales_linearly_with_notional() -> None:
    assert apply_cost(1000.0) == 1000.0 * (TOTAL_COST_BPS / 10_000)
    assert apply_cost(2000.0) == 2 * apply_cost(1000.0)


def test_apply_cost_of_zero_is_zero() -> None:
    assert apply_cost(0.0) == 0.0

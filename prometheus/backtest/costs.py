"""An explicit, real-world cost model -- Binance's own published spot
taker fee, not an invented validation threshold -- applied identically to
a strategy AND the buy-and-hold benchmark (Law 8's explicit requirement)
through this one function, so the two can never drift apart.
"""
from __future__ import annotations

from collections.abc import Callable

# The type any pluggable cost function must satisfy -- notional in, cost
# out, same currency units. backtest/benchmark.py's compute_benchmark_curve
# takes one of these as a parameter (defaulting to apply_cost below) so a
# real per-venue model can be swapped in later without changing its
# signature.
CostModel = Callable[[float], float]

# Binance spot taker fee schedule (binance.com/en/fee/schedule), the
# regular-tier rate with no BNB discount applied -- the conservative case,
# and a real published number, not tuned to make any strategy look better.
TAKER_FEE_BPS = 10.0

# A conservative fixed slippage estimate for the crypto-majors universe
# this project trades (config/universe.yaml) -- real-world-shaped, not a
# number chosen to flatter or penalise any particular strategy.
SLIPPAGE_BPS = 5.0

TOTAL_COST_BPS = TAKER_FEE_BPS + SLIPPAGE_BPS


def apply_cost(notional: float) -> float:
    """Cost, in the same currency units as `notional`, for one round of
    entering or exiting a position of this size."""
    return notional * (TOTAL_COST_BPS / 10_000)

"""How long a CHAMPION must paper-trade before its realized Sharpe is
statistically distinguishable from the benchmark -- PROMPTS.md's
"observation period derived from horizon and independent trade count
needed for significance," answered with Bailey & Lopez de Prado's
Minimum Track Record Length (validation/multiple_testing.py) rather than
an invented number of days.

Trade frequency is extrapolated from the champion's own historical
backtest turnover (BacktestResult.turnover -- the sum of absolute
position changes over the backtest window, PROMPTS's own accounting
already produces this, nothing new computed here) rather than assuming
a fixed cadence: a strategy that rebalances daily and one that
rebalances monthly need very different real-world observation windows
for the same required trade count.
"""
from __future__ import annotations

import math

from prometheus.validation.multiple_testing import minimum_track_record_length


def required_observation_days(
    *,
    minimum_trades: int,
    historical_turnover: float,
    historical_window_days: int,
) -> int | None:
    """Translates a required independent-trade count into a calendar
    horizon using the champion's own historical trade frequency
    (historical_turnover / historical_window_days). None if there is no
    historical trade activity to extrapolate from -- a strategy that
    never rebalanced in its backtest window gives no basis to predict
    when it next will."""
    if historical_turnover <= 0 or historical_window_days <= 0:
        return None
    trades_per_day = historical_turnover / historical_window_days
    return math.ceil(minimum_trades / trades_per_day)


def required_paper_trading_duration(
    *,
    sharpe_hat: float,
    benchmark_sharpe: float,
    skewness: float,
    kurtosis: float,
    confidence: float,
    historical_turnover: float,
    historical_window_days: int,
) -> int | None:
    """End-to-end: MinTRL's required independent-trade count, translated
    into a calendar day count via this champion's own historical trade
    frequency. None propagates from either step -- a strategy whose
    Sharpe is statistically indistinguishable from its own benchmark
    (minimum_track_record_length returns None) has no finite answer to
    fabricate."""
    n_trades = minimum_track_record_length(
        sharpe_hat=sharpe_hat,
        benchmark_sharpe=benchmark_sharpe,
        skewness=skewness,
        kurtosis=kurtosis,
        confidence=confidence,
    )
    if n_trades is None:
        return None
    return required_observation_days(
        minimum_trades=n_trades,
        historical_turnover=historical_turnover,
        historical_window_days=historical_window_days,
    )

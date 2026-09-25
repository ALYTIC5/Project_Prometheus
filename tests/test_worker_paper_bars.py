"""worker.paper_decision_bars -- the frame paper trading decides on:
pre-holdout history + holdout-period bars, in as_of() order. Pure, no DB.
(2026-09-25: a version sorting on event_time -- which as_of() never
returns -- failed every champion in production.)"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.data.ingestion import bar_available_at
from prometheus.data.schema import PointInTimeFrame
from prometheus.worker import paper_decision_bars


def _frame(days: list[datetime]) -> PointInTimeFrame:
    return PointInTimeFrame(
        pl.DataFrame(
            {
                "symbol": ["XLM/USDT"] * len(days),
                "timeframe": ["1d"] * len(days),
                "event_time": days,
                "available_at": [bar_available_at(d, "1d") for d in days],
                "revision": [1] * len(days),
                "open": [1.0] * len(days),
                "high": [1.0] * len(days),
                "low": [1.0] * len(days),
                "close": [float(i) for i in range(len(days))],
                "volume": [1.0] * len(days),
            }
        )
    )


def test_holdout_bars_extend_history_in_time_order() -> None:
    start = datetime(2026, 9, 10, tzinfo=UTC)
    history = _frame([start + timedelta(days=i) for i in range(6)])  # 09-10..09-15
    forward = _frame([start + timedelta(days=i) for i in range(6, 9)])  # 09-16..09-18
    bars = paper_decision_bars(history, forward, datetime(2026, 9, 25, tzinfo=UTC))
    assert bars.height == 9
    assert bars["available_at"].is_sorted()
    assert bars["available_at"][-1] == bar_available_at(start + timedelta(days=8), "1d")


def test_cutoff_still_hides_bars_not_yet_available() -> None:
    start = datetime(2026, 9, 16, tzinfo=UTC)
    history = _frame([start - timedelta(days=1)])
    forward = _frame([start, start + timedelta(days=1)])
    bars = paper_decision_bars(history, forward, bar_available_at(start, "1d"))
    assert bars.height == 2

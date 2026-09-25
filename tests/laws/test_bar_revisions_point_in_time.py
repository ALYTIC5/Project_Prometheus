"""LAW 1: a strategy sees only data whose availability is at or before the
decision time -- including CORRECTIONS to data.

Found 2026-09-25: ingestion stored the current, still-open daily candle and
`ON CONFLICT DO NOTHING` froze it forever (e.g. BTC 2026-09-24 stored close
84,430.46 vs the real 84,411.53), and available_at was the candle's OPEN
time + lag, so a bar looked knowable ~24h before its close existed.

The fix is bitemporal: unclosed candles are never stored, available_at is
the candle's close + lag, and a changed candle gets a NEW revision whose
available_at is when the correction became known. `as_of(cutoff)` returns,
per bar, the latest revision visible at the cutoff -- so a backtest "as of"
a past moment sees exactly what was known then, never a later correction.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.data.ingestion import bar_available_at, plan_bar_writes
from prometheus.data.schema import PointInTimeFrame

_DAY = datetime(2026, 9, 24, tzinfo=UTC)


def _row(revision: int, close: float, available_at: datetime) -> dict[str, object]:
    return {
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "event_time": _DAY,
        "available_at": available_at,
        "revision": revision,
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": close,
        "volume": 1.0,
    }


def test_as_of_before_a_correction_sees_the_original_revision() -> None:
    corrected_at = _DAY + timedelta(days=3)
    pit = PointInTimeFrame(
        pl.DataFrame([_row(1, 101.0, _DAY + timedelta(days=1)), _row(2, 105.0, corrected_at)])
    )
    before = pit.as_of(corrected_at - timedelta(seconds=1))
    assert before.height == 1
    assert before["close"][0] == 101.0


def test_as_of_after_a_correction_sees_only_the_correction() -> None:
    corrected_at = _DAY + timedelta(days=3)
    pit = PointInTimeFrame(
        pl.DataFrame([_row(1, 101.0, _DAY + timedelta(days=1)), _row(2, 105.0, corrected_at)])
    )
    after = pit.as_of(corrected_at)
    assert after.height == 1
    assert after["close"][0] == 105.0


def test_a_daily_bar_is_not_available_until_its_candle_has_closed() -> None:
    close_time = _DAY + timedelta(days=1)
    assert bar_available_at(_DAY, "1d") > close_time


def test_unclosed_candle_is_never_planned_for_storage() -> None:
    bar = {"event_time": _DAY, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}
    mid_candle = _DAY + timedelta(hours=12)
    assert plan_bar_writes([bar], existing={}, now=mid_candle, timeframe="1d") == []


def test_closed_candle_differing_from_stored_gets_a_new_revision_known_now() -> None:
    now = _DAY + timedelta(days=2)
    bar = {"event_time": _DAY, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    stored = {_DAY: (1, (1.0, 2.0, 0.5, 1.2, 9.0))}
    [write] = plan_bar_writes([bar], existing=stored, now=now, timeframe="1d")
    assert write["revision"] == 2
    assert write["available_at"] >= now


def test_identical_closed_candle_is_not_rewritten() -> None:
    now = _DAY + timedelta(days=2)
    bar = {"event_time": _DAY, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    stored = {_DAY: (1, (1.0, 2.0, 0.5, 1.5, 9.0))}
    assert plan_bar_writes([bar], existing=stored, now=now, timeframe="1d") == []

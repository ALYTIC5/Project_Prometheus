"""Quality checks are pure functions over a Polars DataFrame — no DB
needed, fully testable offline.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.data.quality import run_quality_checks

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bar(symbol: str, hour: int, o: float, h: float, low: float, c: float, v: float) -> dict:
    event_time = _T0 + timedelta(hours=hour)
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "event_time": event_time,
        "available_at": event_time + timedelta(minutes=5),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": v,
    }


def test_clean_data_passes() -> None:
    rows = [_bar("BTC/USDT", i, 100 + i, 101 + i, 99 + i, 100.5 + i, 1000.0) for i in range(20)]
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert report.passed
    assert report.issues == []


def test_negative_price_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows[2]["close"] = -1.0
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("non-positive price" in issue for issue in report.issues)


def test_impossible_ohlc_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows[2]["high"] = 90.0  # high below low/open/close
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("impossible OHLC" in issue for issue in report.issues)


def test_duplicate_timestamp_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows.append(dict(rows[2]))  # exact duplicate
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("duplicate rows" in issue for issue in report.issues)


def test_gap_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(5)]
    rows.append(_bar("BTC/USDT", 20, 100, 101, 99, 100, 1000.0))  # big jump from hour 4 to 20
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("gap" in issue for issue in report.issues)


def test_volume_spike_flagged() -> None:
    rows = [_bar("BTC/USDT", i, 100, 101, 99, 100, 1000.0) for i in range(30)]
    rows[15]["volume"] = 10_000_000.0  # wildly beyond 20 sigma of a flat series
    report = run_quality_checks(pl.DataFrame(rows), "1h")
    assert not report.passed
    assert any("volume spike" in issue for issue in report.issues)

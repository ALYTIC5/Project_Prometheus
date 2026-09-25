"""prometheus/data/providers/yahoo.py's parse_chart -- pure, no network."""
from __future__ import annotations

from datetime import UTC, datetime

from prometheus.data.providers.yahoo import YahooChartProvider, parse_chart

# 2024-01-02 / 01-03 / 01-04 14:30 UTC (US open) timestamps.
_T1, _T2, _T3 = 1704205800, 1704292200, 1704378600


def _body(splits: dict[str, dict[str, int]] | None = None) -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [_T1, _T2, _T3],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, None, 12.0],
                                "high": [11.0, 11.5, 13.0],
                                "low": [9.0, 10.0, 11.0],
                                "close": [10.5, 11.0, 12.5],
                                "volume": [1000, 1100, 1200],
                            }
                        ]
                    },
                    "events": {"splits": splits} if splits else {},
                }
            ]
        }
    }


def test_null_session_is_skipped_not_filled() -> None:
    bars = parse_chart("SPY", _body())
    assert [b.close for b in bars] == [10.5, 12.5]


def test_event_time_is_session_date_at_midnight_utc() -> None:
    bars = parse_chart("SPY", _body())
    assert bars[0].event_time == datetime(2024, 1, 2, tzinfo=UTC)


def test_splits_after_a_bar_are_reversed_to_the_price_actually_traded() -> None:
    # 2-for-1 split effective between bar 1 and bar 3: Yahoo shows bar 1
    # already halved; the raw price that traded was double, volume half.
    split = {str(_T2 + 1): {"date": _T2 + 1, "numerator": 2, "denominator": 1}}
    bars = parse_chart("SPY", _body(split))
    assert bars[0].close == 21.0
    assert bars[0].volume == 500.0
    assert bars[1].close == 12.5  # after the split: unchanged


def test_capabilities_are_honest_about_survivorship() -> None:
    caps = YahooChartProvider().capabilities()
    assert caps["survivorship_safe"] is False
    assert caps["point_in_time"] is True

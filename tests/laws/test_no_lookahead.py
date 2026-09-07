"""Law 1: no look-ahead. A strategy sees only data whose available_at is
at or before the decision timestamp. PointInTimeFrame.as_of() is the
mechanism; these tests prove it holds under adversarial and randomised
conditions, not just on a hand-picked example. No DB needed — pure
Polars, synthetic data, runs everywhere.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import polars as pl

from prometheus.data.schema import PointInTimeFrame

_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
_N_BARS = 500


def _synthetic_frame(planted_future_marker: float | None = None) -> pl.DataFrame:
    rows = []
    rng = random.Random(1)
    for symbol in _SYMBOLS:
        price = 100.0
        for i in range(_N_BARS):
            event_time = _START + timedelta(hours=i)
            available_at = event_time + timedelta(minutes=5)  # realistic ingestion lag
            price *= 1 + rng.uniform(-0.01, 0.01)
            close = price
            if planted_future_marker is not None and i == _N_BARS - 1:
                close = planted_future_marker
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": "1h",
                    "event_time": event_time,
                    "available_at": available_at,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(rows)


def test_planted_future_value_is_unreachable() -> None:
    marker = 999_999.0
    frame = _synthetic_frame(planted_future_marker=marker)
    pit = PointInTimeFrame(frame)
    cutoff = _START + timedelta(hours=_N_BARS - 10)  # well before the planted bar

    visible = pit.as_of(cutoff)

    assert "event_time" not in visible.columns
    assert marker not in visible["close"].to_list()
    assert (visible["available_at"] <= cutoff).all()


def _rolling_mean_feature(df: pl.DataFrame, window: int = 10) -> pl.DataFrame:
    """A representative feature: trailing rolling mean of close, grouped
    per symbol. Uses Polars' trailing (not centred) rolling_mean, which
    only looks backward — the thing a leaky implementation would get wrong.
    """
    return df.sort(["symbol", "available_at"]).with_columns(
        pl.col("close").rolling_mean(window).over("symbol").alias("feature")
    )


def test_truncation_proof_across_random_sample() -> None:
    """For 200 random (symbol, cutoff) pairs, features computed via
    as_of(cutoff) on the full dataset must be identical to features
    computed on a dataset physically truncated at cutoff before feature
    computation. Any difference means data from beyond the cutoff
    reached the feature — the single most valuable test in this repo.
    """
    frame = _synthetic_frame()
    pit = PointInTimeFrame(frame)
    rng = random.Random(20260906)

    samples = [
        (rng.choice(_SYMBOLS), _START + timedelta(hours=rng.randint(50, _N_BARS - 1)))
        for _ in range(200)
    ]

    for symbol, cutoff in samples:
        visible_via_accessor = pit.as_of(cutoff).filter(pl.col("symbol") == symbol)
        features_from_accessor = _rolling_mean_feature(visible_via_accessor)

        # Ground truth: filter the SOURCE frame (still has event_time, no
        # accessor involved) to what a physically truncated dataset would
        # contain, independent of PointInTimeFrame's own logic.
        truncated_source = (
            frame.filter((pl.col("symbol") == symbol) & (pl.col("available_at") <= cutoff))
            .select(list(pit.visible_columns))
            .sort(["symbol", "available_at"])
        )
        features_from_truncated = _rolling_mean_feature(truncated_source)

        assert features_from_accessor.equals(features_from_truncated), (
            f"feature mismatch for {symbol} at cutoff={cutoff}: as_of() leaked "
            f"or dropped data relative to a physically truncated dataset"
        )

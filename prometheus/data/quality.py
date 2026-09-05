"""Quality checks run on every ingest: gaps, duplicate timestamps,
non-positive prices, impossible OHLC relationships, volume spikes,
stale bars. Failures quarantine the batch; they never silently pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

_BAR_HOURS = {"1h": 1, "4h": 4, "1d": 24}


@dataclass
class QualityReport:
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


def _expected_bar_hours(timeframe: str) -> int:
    if timeframe not in _BAR_HOURS:
        raise ValueError(f"unknown timeframe: {timeframe!r}")
    return _BAR_HOURS[timeframe]


def check_gaps(frame: pl.DataFrame, timeframe: str) -> list[str]:
    expected_hours = _expected_bar_hours(timeframe)
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol).sort("event_time")
        deltas = sub["event_time"].diff().drop_nulls()
        gap_count = (deltas.dt.total_hours() > expected_hours).sum()
        if gap_count:
            issues.append(f"{symbol}: {gap_count} gap(s) larger than one {timeframe} bar")
    return issues


def check_duplicate_timestamps(frame: pl.DataFrame) -> list[str]:
    dupes = (
        frame.group_by(["symbol", "timeframe", "event_time"])
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
    )
    return [
        f"{row['symbol']} {row['timeframe']} {row['event_time']}: {row['n']} duplicate rows"
        for row in dupes.iter_rows(named=True)
    ]


def check_price_validity(frame: pl.DataFrame) -> list[str]:
    bad = frame.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
    )
    return [
        f"{row['symbol']} {row['event_time']}: non-positive price"
        for row in bad.iter_rows(named=True)
    ]


def check_ohlc_relationships(frame: pl.DataFrame) -> list[str]:
    bad = frame.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
    )
    return [
        f"{row['symbol']} {row['event_time']}: impossible OHLC relationship "
        f"(O={row['open']} H={row['high']} L={row['low']} C={row['close']})"
        for row in bad.iter_rows(named=True)
    ]


def check_volume_spikes(frame: pl.DataFrame, threshold: float = 20.0) -> list[str]:
    """Flag volumes far from the group's typical scale.

    A naive mean/std z-score is self-masking here: a single huge outlier
    drags the mean and inflates the std enough to hide itself (checked
    numerically — a 10,000x spike among 29 flat bars does not clear 20
    sigma of the *contaminated* std). Mean absolute deviation from the
    median is used instead: the median resists a single outlier, so the
    spike still reads as far from typical even though it also pulls the
    mean absolute deviation up somewhat.

    Deliberately NOT the median absolute deviation (MAD): for data shaped
    like this (29 identical values + 1 outlier), the *median* of the
    absolute deviations is 0 (29 of 30 deviations are 0), which would trip
    the zero-guard below and let the spike through undetected. Do not
    "fix" this to `.median()` — that reintroduces the exact bug this
    function was written to avoid.
    """
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol)
        median = sub["volume"].median()
        abs_dev = (sub["volume"] - median).abs()
        mean_abs_dev = abs_dev.mean()
        if median is None or mean_abs_dev is None or mean_abs_dev == 0:
            continue
        spikes = sub.filter(((pl.col("volume") - median).abs() / mean_abs_dev) > threshold)
        if spikes.height:
            issues.append(
                f"{symbol}: {spikes.height} volume spike(s) beyond "
                f"{threshold}x mean absolute deviation from median"
            )
    return issues


def check_stale_bars(frame: pl.DataFrame) -> list[str]:
    issues = []
    for symbol in frame["symbol"].unique().sort().to_list():
        sub = frame.filter(pl.col("symbol") == symbol)
        stale = sub.filter(
            (pl.col("open") == pl.col("close"))
            & (pl.col("high") == pl.col("low"))
            & (pl.col("open") == pl.col("high"))
        )
        if stale.height > 1:
            issues.append(f"{symbol}: {stale.height} stale (zero-range) bar(s)")
    return issues


def run_quality_checks(frame: pl.DataFrame, timeframe: str) -> QualityReport:
    issues: list[str] = []
    issues += check_gaps(frame, timeframe)
    issues += check_duplicate_timestamps(frame)
    issues += check_price_validity(frame)
    issues += check_ohlc_relationships(frame)
    issues += check_volume_spikes(frame)
    issues += check_stale_bars(frame)
    return QualityReport(issues=issues)

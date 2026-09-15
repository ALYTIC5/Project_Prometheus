from __future__ import annotations

from datetime import UTC, datetime

from prometheus.core.clock import FixedClock, SystemClock


def test_fixed_clock_always_returns_the_same_instant() -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FixedClock(fixed)
    assert clock.now() == fixed
    assert clock.now() == clock.now()


def test_system_clock_returns_a_timezone_aware_utc_datetime() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None

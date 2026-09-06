"""compute_content_hash is a pure function — testable offline.
record_data_version needs a session; tested here with a fake session (no
real DB) exposing only `.add()` and `.flush()`, matching the
`_fake_session()` pattern in tests/test_research_policy.py.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from prometheus.data.versioning import compute_content_hash, record_data_version


def _fake_session() -> MagicMock:
    """A stand-in for AsyncSession exposing only `.add()` and `.flush()`,
    matching tests/test_research_policy.py's `_fake_session()`: `.add()` is
    sync (MagicMock default), only `.flush()` is async.
    """
    session = MagicMock()
    session.flush = AsyncMock()
    return session


def _frame(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["BTC/USDT"] * len(closes),
            "timeframe": ["1h"] * len(closes),
            "event_time": [datetime(2024, 1, 1, tzinfo=UTC)] * len(closes),
            "available_at": [datetime(2024, 1, 1, 0, 1, tzinfo=UTC)] * len(closes),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100.0] * len(closes),
        }
    )


def test_content_hash_deterministic() -> None:
    left = compute_content_hash(_frame([1.0, 2.0, 3.0]))
    right = compute_content_hash(_frame([1.0, 2.0, 3.0]))
    assert left == right


def test_content_hash_sensitive_to_content() -> None:
    left = compute_content_hash(_frame([1.0, 2.0, 3.0]))
    right = compute_content_hash(_frame([1.0, 2.0, 3.1]))
    assert left != right


def test_content_hash_is_sha256_hex() -> None:
    h = compute_content_hash(_frame([1.0]))
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex


@pytest.mark.asyncio
async def test_record_data_version_adds_and_flushes() -> None:
    session = _fake_session()
    version = await record_data_version(
        session,
        _frame([1.0, 2.0, 3.0]),
        date_range_start=date(2024, 1, 1),
        date_range_end=date(2024, 1, 2),
        source_versions={"binance": "spot-v3"},
    )
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert version.row_count == 3
    assert version.date_range_start == date(2024, 1, 1)

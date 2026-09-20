"""backfill_etf() against a real Postgres with a fake provider (never
live Alpaca) -- proves it writes through the *existing* quality/
versioning pipeline unchanged, the same convention test_population.py/
test_queue_semantics.py already use for db-marked tests.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from prometheus.data.ingest_etf import backfill_etf
from prometheus.data.providers.base import MarketDataProvider, ProviderCapabilities, RawBar

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0014 applied)",
    ),
]


class _FakeProvider(MarketDataProvider):
    """Returns realistic weekday-only daily bars (skips Saturdays and
    Sundays, like real equity/ETF trading) for one symbol -- the whole
    point of this fake is to include REAL weekend gaps, proving
    backfill_etf() tolerates them (via check_gaps' max_gap_hours
    override) instead of quarantining on them. A fake that generated one
    bar per calendar day (no gaps at all) would pass regardless of
    whether that override actually worked -- this one wouldn't."""

    def capabilities(self) -> ProviderCapabilities:
        return {
            "asset_classes": ["etf"],
            "intervals": ["1d"],
            "survivorship_safe": True,
            "point_in_time": True,
            "rate_limit": "n/a -- test fake",
        }

    async def fetch_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str
    ) -> list[RawBar]:
        bars = []
        price = 400.0
        for symbol in symbols:
            current = start
            while current <= end:
                if current.weekday() < 5:  # Mon-Fri only
                    bars.append(
                        RawBar(
                            symbol=symbol,
                            event_time=current,
                            open=price,
                            high=price + 1,
                            low=price - 1,
                            close=price,
                            volume=1_000_000.0,
                        )
                    )
                current += timedelta(days=1)
        return bars


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


async def test_backfill_etf_writes_real_bars_through_the_existing_pipeline(
    engine: AsyncEngine,
) -> None:
    # end is fixed well before config/holdout.yaml's real holdout_start
    # (2026-09-16) -- this test's job is ingestion/quality/versioning
    # mechanics, not holdout-splitting (already covered by
    # tests/laws/test_holdout_sacred.py), and it must never write fake
    # test bars into the shared Law-3-protected holdout schema.
    await backfill_etf(
        days=200, symbols=["SPY"], provider=_FakeProvider(), end=datetime(2026, 6, 1, tzinfo=UTC)
    )

    factory = async_sessionmaker(engine)
    async with factory() as session:
        status = (
            await session.execute(
                text(
                    "SELECT status FROM raw_ingest WHERE symbol = 'SPY' AND source = 'alpaca' "
                    "ORDER BY id DESC LIMIT 1"
                )
            )
        ).scalar_one()
    # The real point of this test: realistic weekend-gapped data must
    # NOT be quarantined -- proving the max_gap_hours override actually
    # took effect, not just that some data landed somewhere.
    assert status == "normalized"

    async with factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM ohlcv_bars WHERE symbol = 'SPY' AND source = 'alpaca'")
            )
        ).scalar_one()
    # ~5/7 of 200 calendar days, give or take boundary effects -- a loose
    # bound proving substantial real weekday data landed, not lost.
    assert 135 <= count <= 145

    async with factory() as session:
        version_count = (
            await session.execute(
                text("SELECT count(*) FROM data_versions WHERE source_versions ? 'alpaca'")
            )
        ).scalar_one()
    assert version_count >= 1

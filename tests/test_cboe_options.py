"""CBOE option-chain snapshots: OCC parsing, per-expiry aggregation, the
after-close window, and the append-only, deduplicated options_daily store."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.providers.cboe_options import aggregate, parse_chain, parse_occ
from prometheus.worker import _options_window_open, _run_options


def _contract(option: str, **fields: float) -> dict[str, Any]:
    base = {"bid": 0.0, "ask": 0.0, "volume": 0.0, "open_interest": 0.0, "iv": 0.0}
    return {"option": option, **base, **fields}


def _body(ticker: str = "XLK") -> dict[str, Any]:
    return {
        "timestamp": "2026-09-28 21:20:00",
        "data": {
            "current_price": 101.0,
            "last_trade_time": "2026-09-28T15:59:58",
            "options": [
                _contract(
                    f"{ticker}{tail}", bid=bid, ask=ask, volume=vol, open_interest=oi, iv=iv
                )
                for tail, bid, ask, vol, oi, iv in (
                    ("261002C00095000", 6.0, 6.2, 10, 100, 0.2),
                    ("261002C00100000", 2.0, 2.2, 50, 500, 0.18),
                    ("261002P00100000", 1.0, 1.2, 30, 300, 0.21),
                    ("261002P00105000", 4.0, 4.4, 5, 50, 0.0),
                    ("261016C00100000", 3.0, 3.4, 7, 70, 0.0),
                )
            ],
        },
    }


def test_parse_occ() -> None:
    assert parse_occ("SPY260928C00550000") == (date(2026, 9, 28), True, 550.0)
    assert parse_occ("XLRE261016P00041500") == (date(2026, 10, 16), False, 41.5)
    # An adjusted-contract root that itself ends in a digit.
    assert parse_occ("SPY1261002P00100500") == (date(2026, 10, 2), False, 100.5)
    with pytest.raises(ValueError, match="OCC"):
        parse_occ("SPY")


def test_parse_chain_uses_the_session_date_and_utc_timestamp() -> None:
    chain = parse_chain("XLK", _body())
    assert chain.session_date == date(2026, 9, 28)
    assert chain.source_timestamp == datetime(2026, 9, 28, 21, 20, tzinfo=UTC)
    assert chain.spot == 101.0
    assert len(chain.contracts) == 5


def test_aggregate_per_expiry() -> None:
    first, second = aggregate(parse_chain("XLK", _body()))
    assert first.expiry == date(2026, 10, 2) and second.expiry == date(2026, 10, 16)
    assert (first.call_volume, first.put_volume) == (60, 35)
    assert (first.call_oi, first.put_oi) == (600, 350)
    assert first.call_premium == pytest.approx(10 * 6.1 * 100 + 50 * 2.1 * 100)
    assert first.put_premium == pytest.approx(30 * 1.1 * 100 + 5 * 4.2 * 100)
    # Strike nearest spot (101) is 100; both sides quoted there.
    assert first.atm_strike == 100.0
    assert (first.atm_call_iv, first.atm_put_iv) == (0.18, 0.21)
    assert first.n_contracts == 4
    # IV 0.0 is CBOE's "not computed" placeholder, never a real IV.
    assert second.atm_call_iv is None and second.atm_put_iv is None


@pytest.mark.parametrize(
    ("hour", "minute", "open_"),
    [(20, 30, False), (21, 14, False), (21, 15, True), (23, 59, True), (0, 5, False)],
)
def test_options_window_is_after_the_close(hour: int, minute: int, open_: bool) -> None:
    assert _options_window_open(datetime(2026, 9, 28, hour, minute, tzinfo=UTC)) is open_


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)


@_needs_db
@pytest.mark.db
async def test_snapshot_is_stored_once_per_session_and_append_only(
    db_session: AsyncSession,
) -> None:
    ticker = f"T{uuid.uuid4().hex[:8].upper()}"
    fetch = AsyncMock(side_effect=lambda _client, t: parse_chain(t, _body(t)))
    with (
        patch("prometheus.worker.OPTIONS_TICKERS", (ticker,)),
        patch("prometheus.worker.fetch_chain", new=fetch),
    ):
        first = await _run_options()
        again = await _run_options()  # same session date -> deduplicated
    assert (first, again) == (2, 0)

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM options_daily WHERE underlying = :u"), {"u": ticker}
        )
    ).scalar_one()
    assert count == 2
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE options_daily SET spot = 0 WHERE underlying = :u"), {"u": ticker}
            )


@_needs_db
@pytest.mark.db
async def test_one_failing_ticker_does_not_fail_the_snapshot() -> None:
    good = f"T{uuid.uuid4().hex[:8].upper()}"

    async def fetch(_client: object, ticker: str) -> Any:
        if ticker == "BROKEN":
            raise RuntimeError("feed down")
        return parse_chain(ticker, _body(ticker))

    with (
        patch("prometheus.worker.OPTIONS_TICKERS", ("BROKEN", good)),
        patch("prometheus.worker.fetch_chain", new=fetch),
    ):
        assert await _run_options() == 2

    with (
        patch("prometheus.worker.OPTIONS_TICKERS", ("BROKEN",)),
        patch("prometheus.worker.fetch_chain", new=fetch),
        pytest.raises(RuntimeError, match="every ticker failed"),
    ):
        await _run_options()

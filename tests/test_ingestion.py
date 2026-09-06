"""Ingestion logic is tested via a fake exchange client (the
ExchangeClient Protocol ccxt's real Exchange also satisfies) — no
network needed. DB-touching behavior (idempotency via the unique
constraint, actual inserts) needs a live Postgres and is out of scope
for this offline suite; the pure parsing/format logic below is not.
"""
from __future__ import annotations

from datetime import UTC, datetime

from prometheus.data.ingestion import ccxt_rows_to_bars, load_universe_symbols


def test_load_universe_symbols_excludes_delisted() -> None:
    symbols = load_universe_symbols("config/universe.yaml")
    assert "BTC/USDT" in symbols
    assert "BCHSV/USDT" not in symbols  # delisted, excluded from the active backfill list
    assert len(symbols) >= 15


def test_ccxt_rows_to_bars_shapes_and_lags_correctly() -> None:
    ts_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    raw_rows = [[ts_ms, 100.0, 101.0, 99.0, 100.5, 1234.0]]

    bars = ccxt_rows_to_bars(raw_rows, "BTC/USDT", "1h", "binance")

    assert len(bars) == 1
    bar = bars[0]
    assert bar["symbol"] == "BTC/USDT"
    assert bar["timeframe"] == "1h"
    assert bar["source"] == "binance"
    assert bar["revision"] == 1
    assert bar["event_time"] == datetime(2024, 1, 1, tzinfo=UTC)
    assert bar["available_at"] > bar["event_time"]  # ingestion lag applied
    assert bar["open"] == 100.0 and bar["close"] == 100.5

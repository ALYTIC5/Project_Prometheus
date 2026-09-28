"""CBOE delayed option-chain snapshots -> daily per-expiry aggregates.

Source: https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json
-- CBOE's public delayed-quote feed (15-minute delay, no key). One call
returns the whole chain for an underlying: every contract's bid/ask,
volume, open interest, IV and greeks, plus the underlying's own quote.

There is no free HISTORICAL options source, so this is recorded forward
from the day it starts: the "follow the options money" idea can only be
backtested once enough days exist, and only on dates after recording began
(Law 1: available_at is the fetch time, never back-dated).

Aggregates only (user decision 2026-09-28): per (underlying, session date,
expiry) -- call/put volume, open interest, premium traded (volume x mid x
100) and the at-the-money IV (the listed strike nearest spot). Per-expiry
rows so no maturity bucket has to be invented now; features are derived
later from these rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; prometheus-research/1.0)"}
_CONTRACT_MULTIPLIER = 100

# The 11 SPDR sector ETFs plus the two broad benchmarks (user decision
# 2026-09-28): "where is the money flowing, sector by sector".
OPTIONS_TICKERS = (
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
    "SPY", "QQQ",
)

# OCC option symbol: root (1-6 chars), YYMMDD expiry, C/P, strike x 1000
# (8 digits). The root can itself contain digits (adjusted contracts), so
# the fixed-width tail is matched from the right.
_OCC = re.compile(r"^(?P<root>.+?)(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class Contract:
    expiry: date
    is_call: bool
    strike: float
    bid: float
    ask: float
    volume: float
    open_interest: float
    iv: float


@dataclass(frozen=True)
class Chain:
    underlying: str
    session_date: date
    spot: float
    source_timestamp: datetime
    contracts: list[Contract]


@dataclass(frozen=True)
class ExpiryAggregate:
    expiry: date
    call_volume: float
    put_volume: float
    call_oi: float
    put_oi: float
    call_premium: float
    put_premium: float
    atm_strike: float | None
    atm_call_iv: float | None
    atm_put_iv: float | None
    n_contracts: int


def parse_occ(symbol: str) -> tuple[date, bool, float]:
    match = _OCC.match(symbol)
    if match is None:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    yymmdd = match["yymmdd"]
    expiry = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:]))
    return expiry, match["cp"] == "C", int(match["strike"]) / 1000.0


def parse_chain(ticker: str, body: dict[str, Any]) -> Chain:
    data = body["data"]
    # The underlying's last trade time is exchange-local; its date is the
    # session the chain belongs to (a weekend fetch still reports Friday,
    # so the (underlying, session_date, expiry) key dedupes it).
    session_date = datetime.fromisoformat(str(data["last_trade_time"])).date()
    source_timestamp = datetime.fromisoformat(str(body["timestamp"])).replace(tzinfo=UTC)
    contracts = []
    for raw in data["options"]:
        expiry, is_call, strike = parse_occ(str(raw["option"]))
        contracts.append(
            Contract(
                expiry=expiry,
                is_call=is_call,
                strike=strike,
                bid=float(raw.get("bid") or 0.0),
                ask=float(raw.get("ask") or 0.0),
                volume=float(raw.get("volume") or 0.0),
                open_interest=float(raw.get("open_interest") or 0.0),
                iv=float(raw.get("iv") or 0.0),
            )
        )
    return Chain(
        underlying=ticker,
        session_date=session_date,
        spot=float(data["current_price"]),
        source_timestamp=source_timestamp,
        contracts=contracts,
    )


def _atm_iv(contracts: list[Contract], strike: float, *, is_call: bool) -> float | None:
    """IV of the contract at `strike`; None when the feed reports none
    (0.0 is CBOE's placeholder for 'not computed', not a real IV)."""
    for c in contracts:
        if c.is_call == is_call and c.strike == strike and c.iv > 0:
            return c.iv
    return None


def aggregate(chain: Chain) -> list[ExpiryAggregate]:
    by_expiry: dict[date, list[Contract]] = {}
    for contract in chain.contracts:
        by_expiry.setdefault(contract.expiry, []).append(contract)

    aggregates = []
    for expiry in sorted(by_expiry):
        contracts = by_expiry[expiry]
        calls = [c for c in contracts if c.is_call]
        puts = [c for c in contracts if not c.is_call]

        def premium(side: list[Contract]) -> float:
            return sum(c.volume * (c.bid + c.ask) / 2 * _CONTRACT_MULTIPLIER for c in side)

        strikes = sorted({c.strike for c in contracts})
        atm = min(strikes, key=lambda s: (abs(s - chain.spot), s)) if strikes else None
        aggregates.append(
            ExpiryAggregate(
                expiry=expiry,
                call_volume=sum(c.volume for c in calls),
                put_volume=sum(c.volume for c in puts),
                call_oi=sum(c.open_interest for c in calls),
                put_oi=sum(c.open_interest for c in puts),
                call_premium=premium(calls),
                put_premium=premium(puts),
                atm_strike=atm,
                atm_call_iv=_atm_iv(contracts, atm, is_call=True) if atm is not None else None,
                atm_put_iv=_atm_iv(contracts, atm, is_call=False) if atm is not None else None,
                n_contracts=len(contracts),
            )
        )
    return aggregates


async def fetch_chain(client: httpx.AsyncClient, ticker: str) -> Chain:
    response = await client.get(CHAIN_URL.format(ticker=ticker))
    response.raise_for_status()
    return parse_chain(ticker, response.json())


def http_client() -> httpx.AsyncClient:
    # cdn.cboe.com answers some tickers with a 307 to cdn-api.cboe.com (seen
    # 2026-09-28 for XLB); httpx does not follow redirects unless told to.
    return httpx.AsyncClient(headers=_HEADERS, timeout=60.0, follow_redirects=True)

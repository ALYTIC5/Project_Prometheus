"""Universe reconstruction — Law 2. Membership as of a date comes ONLY
from universe_membership's listed_at/delisted_at, never from today's
exchange listing. asset_class is required on every call -- a caller
that forgot to specify one would otherwise silently see both crypto and
ETF symbols mixed in one list.
"""
from __future__ import annotations

from datetime import date

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.models import UniverseMembership

_DEFAULT_UNIVERSE_YAML = "config/universe.yaml"

_UPSERT_MEMBERSHIP = text(
    """
    INSERT INTO universe_membership (symbol, exchange, asset_class, listed_at, delisted_at)
    VALUES (:symbol, :exchange, :asset_class, :listed_at, :delisted_at)
    ON CONFLICT ON CONSTRAINT uq_universe_membership_symbol_exchange_listed_at
    DO UPDATE SET delisted_at = EXCLUDED.delisted_at, asset_class = EXCLUDED.asset_class
    """
)


async def as_of(session: AsyncSession, as_of_date: date, asset_class: str) -> list[str]:
    stmt = select(UniverseMembership.symbol).where(
        UniverseMembership.asset_class == asset_class,
        UniverseMembership.listed_at <= as_of_date,
        (UniverseMembership.delisted_at.is_(None)) | (UniverseMembership.delisted_at > as_of_date),
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def membership_windows(
    session: AsyncSession, asset_class: str, symbols: list[str]
) -> dict[str, tuple[date, date | None]]:
    """One (listed_at, delisted_at) window per symbol under
    `asset_class`, fetched once so a caller doing point-in-time universe
    reconstruction across many dates (run_portfolio_backtest's many
    rebalance dates) does one query, not one per date. A symbol with no
    matching row is absent from the result -- it was never part of this
    asset class's universe at all, under any date."""
    stmt = select(
        UniverseMembership.symbol, UniverseMembership.listed_at, UniverseMembership.delisted_at
    ).where(
        UniverseMembership.asset_class == asset_class,
        UniverseMembership.symbol.in_(symbols),
    )
    result = await session.execute(stmt)
    return {row.symbol: (row.listed_at, row.delisted_at) for row in result.all()}


async def sync_from_yaml(
    session: AsyncSession, path: str = _DEFAULT_UNIVERSE_YAML, *, asset_class: str
) -> int:
    """Upserts every symbol in `path` (delisted ones included -- as_of()
    needs those too, unlike ingestion.load_universe_symbols()'s current-
    ingest-list filter) into universe_membership, keyed on (symbol,
    exchange, listed_at). Idempotent: re-running against an unchanged file
    touches every row but changes nothing. Returns the number of rows
    upserted."""
    with open(path, encoding="utf-8") as f:
        rows = yaml.safe_load(f)["symbols"]
    for row in rows:
        await session.execute(
            _UPSERT_MEMBERSHIP,
            {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "asset_class": asset_class,
                "listed_at": row["listed_at"],
                "delisted_at": row.get("delisted_at"),
            },
        )
    return len(rows)


async def load_universe_symbols_for_asset_class(
    session: AsyncSession, asset_class: str
) -> list[str]:
    """Currently-active symbols for one asset class, from
    universe_membership (not the YAML directly) -- the same
    delisted_at-aware filter as_of() uses, evaluated at today's date."""
    return await as_of(session, date.today(), asset_class)

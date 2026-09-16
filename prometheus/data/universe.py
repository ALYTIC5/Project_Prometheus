"""Universe reconstruction — Law 2. Membership as of a date comes ONLY
from universe_membership's listed_at/delisted_at, never from today's
exchange listing.
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
    INSERT INTO universe_membership (symbol, exchange, listed_at, delisted_at)
    VALUES (:symbol, :exchange, :listed_at, :delisted_at)
    ON CONFLICT ON CONSTRAINT uq_universe_membership_symbol_exchange_listed_at
    DO UPDATE SET delisted_at = EXCLUDED.delisted_at
    """
)


async def as_of(session: AsyncSession, as_of_date: date) -> list[str]:
    stmt = select(UniverseMembership.symbol).where(
        UniverseMembership.listed_at <= as_of_date,
        (UniverseMembership.delisted_at.is_(None)) | (UniverseMembership.delisted_at > as_of_date),
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def sync_from_yaml(session: AsyncSession, path: str = _DEFAULT_UNIVERSE_YAML) -> int:
    """Upserts every symbol in `path` (delisted ones included -- as_of()
    needs those too, unlike ingestion.load_universe_symbols()'s current-
    ingest-list filter) into universe_membership, keyed on (symbol,
    exchange, listed_at). Idempotent: re-running against an unchanged file
    touches every row but changes nothing. If a symbol's delisted_at
    changes (it gets delisted, or a correction), this UPDATEs the existing
    row rather than inserting a second one for the same listing -- the
    migration 0009 unique constraint is what makes that ON CONFLICT target
    real. Returns the number of rows upserted.
    """
    with open(path, encoding="utf-8") as f:
        rows = yaml.safe_load(f)["symbols"]
    for row in rows:
        await session.execute(
            _UPSERT_MEMBERSHIP,
            {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "listed_at": row["listed_at"],
                "delisted_at": row.get("delisted_at"),
            },
        )
    return len(rows)

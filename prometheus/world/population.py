"""prometheus/world/population.py -- real per-family status counts for the
world projection (District.population_by_status). Read-only; moved out of
research/population.py because it reads the raw strategies table, which
research code may not (Law 9)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.strategy.spec import FAMILIES

_POPULATION_SUMMARY = text(
    "SELECT family, status, COUNT(*) AS n FROM strategies GROUP BY family, status"
)


async def population_summary(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Keys are lower-cased to match District.population_by_status."""
    rows = (await session.execute(_POPULATION_SUMMARY)).fetchall()
    summary: dict[str, dict[str, int]] = {family: {} for family in FAMILIES}
    for row in rows:
        summary.setdefault(row.family, {})[row.status.lower()] = int(row.n)
    return summary

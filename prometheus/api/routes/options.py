"""Options snapshot visibility -- how much options history has been
recorded per underlying (data/providers/cboe_options.py). Recording only:
nothing trades on these rows until enough sessions exist to test on."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/options", tags=["options"])

_SUMMARY = text(
    """
    WITH per_day AS (
        SELECT underlying, quote_date,
               sum(put_volume) AS put_volume, sum(call_volume) AS call_volume,
               sum(put_oi) AS put_oi, sum(call_oi) AS call_oi
          FROM options_daily
         GROUP BY underlying, quote_date
    ), latest AS (
        SELECT DISTINCT ON (underlying) * FROM per_day ORDER BY underlying, quote_date DESC
    )
    SELECT d.underlying,
           count(*) AS sessions,
           min(d.quote_date) AS first_session,
           max(d.quote_date) AS latest_session,
           l.put_volume, l.call_volume, l.put_oi, l.call_oi
      FROM per_day d
      JOIN latest l ON l.underlying = d.underlying
     GROUP BY d.underlying, l.put_volume, l.call_volume, l.put_oi, l.call_oi
     ORDER BY d.underlying
    """
)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


@router.get("/summary")
async def summary() -> dict[str, Any]:
    async with get_session_factory()() as session:
        rows = (await session.execute(_SUMMARY)).all()
    return {
        "underlyings": [
            {
                "underlying": row.underlying,
                "sessions_recorded": int(row.sessions),
                "first_session": row.first_session.isoformat(),
                "latest_session": row.latest_session.isoformat(),
                "latest_put_call_volume_ratio": _ratio(row.put_volume, row.call_volume),
                "latest_put_call_oi_ratio": _ratio(row.put_oi, row.call_oi),
            }
            for row in rows
        ]
    }

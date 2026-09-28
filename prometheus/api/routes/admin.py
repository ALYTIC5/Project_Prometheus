"""Operator-only endpoints. Disabled unless ADMIN_TOKEN is set; every call
must carry it in the X-Admin-Token header.

POST /admin/worker/force makes named worker concerns due immediately by
back-dating their worker_cadence rows (mutable scheduling state, not a
history table). It does not start the worker -- tools/ops/worker_now.py
pairs it with Railway's "run now" for the cron service.
"""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from prometheus.core.cadence import CONCERN_INTERVALS
from prometheus.core.db import get_session_factory

router = APIRouter(prefix="/admin", tags=["admin"])

# Longer than any concern's interval, so is_due() is true on the next run.
_BACKDATE = text(
    """
    INSERT INTO worker_cadence (concern, last_run_at)
    VALUES (:concern, now() - interval '30 days')
    ON CONFLICT (concern) DO UPDATE SET last_run_at = now() - interval '30 days'
    """
)


class ForceRequest(BaseModel):
    concerns: list[str]


def _check_token(token: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="admin endpoints are disabled")
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="bad admin token")


@router.post("/worker/force")
async def force_concerns(
    body: ForceRequest, x_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _check_token(x_admin_token)
    unknown = sorted(set(body.concerns) - set(CONCERN_INTERVALS))
    if unknown or not body.concerns:
        raise HTTPException(
            status_code=422,
            detail=f"unknown or empty concerns {unknown}; valid: {sorted(CONCERN_INTERVALS)}",
        )
    async with get_session_factory()() as session:
        for concern in body.concerns:
            await session.execute(_BACKDATE, {"concern": concern})
        await session.commit()
    return {"due_now": sorted(set(body.concerns))}

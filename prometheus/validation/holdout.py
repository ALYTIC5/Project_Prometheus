"""Law 3: "the holdout is sacred." The final test slice is physically
separated (migration 0010's `holdout` Postgres schema), every read is
audited (`holdout_access_log`), and a strategy may touch it exactly once --
a second attempt is a hard error, not a warning.

Two sessions are involved on purpose, and the distinction matters:

- `session` -- the caller's normal (app-role) session. Used ONLY to
  check/write `holdout_access_log`, which lives in the main schema so the
  audit trail is queryable by ordinary code without that code being able
  to read the vault itself.
- the holdout data is read through `core.db.get_holdout_session()`, bound
  to HOLDOUT_DATABASE_URL -- a genuinely separate, non-superuser Postgres
  role (migration 0010) with SELECT-only on the `holdout` schema. This
  function is the only place in the codebase that should ever open that
  connection. See migration 0010's docstring for the real caveat: Railway
  provisions the app's OWN database user as a superuser, so this
  restricted role protects against anything authenticating as itself, not
  against a hypothetical different code path using the superuser app
  credential to query holdout.ohlcv_bars directly. docs/DEFERRED.md tracks
  what closing that residual gap would take.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.data.loaders import POINT_IN_TIME_FRAME_SCHEMA
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

DEFAULT_HOLDOUT_CONFIG_PATH = "config/holdout.yaml"


class HoldoutConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    holdout_start: date
    declared_reason: str


def _content_hash(raw_yaml: str) -> str:
    return hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def load_holdout_config(path: str = DEFAULT_HOLDOUT_CONFIG_PATH) -> tuple[HoldoutConfig, str]:
    """Returns (config, content_hash) -- same pattern as
    backtest.costs.load_cost_config. The hash is what
    experiments.violations.record_config_snapshot stamps, so a change to
    holdout_start is itself an auditable event."""
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return HoldoutConfig(**data), _content_hash(raw)


class HoldoutAccessDenied(Exception):
    """Raised on a second access attempt for the same strategy fingerprint.
    Law 3: "a strategy may touch it once. Second access = automatic
    REJECT, no exceptions." There is no retry, no override."""


_SELECT_PRIOR_GRANTED_ACCESS = text(
    "SELECT 1 FROM holdout_access_log WHERE strategy_fingerprint = :fp AND granted = true LIMIT 1"
)

_INSERT_ACCESS_LOG = text(
    """
    INSERT INTO holdout_access_log (experiment_id, strategy_fingerprint, granted, detail)
    VALUES (:experiment_id, :strategy_fingerprint, :granted, :detail)
    """
).bindparams(bindparam("detail", type_=JSONB))

_SELECT_HOLDOUT_BARS = text(
    """
    SELECT symbol, timeframe, event_time, available_at, open, high, low, close, volume
    FROM holdout.ohlcv_bars
    WHERE symbol = :symbol AND timeframe = :timeframe
    ORDER BY event_time
    """
)


async def access_holdout(
    session: AsyncSession,
    spec: StrategySpec,
    experiment_id: str | None,
) -> PointInTimeFrame:
    """The only code path to holdout data. Checks/records the access in
    the SAME transaction as the caller (`session`) so the audit row is
    never silently lost to a later rollback, then opens a fresh, separate
    holdout-role connection to actually read the bars. Raises
    HoldoutAccessDenied on a second access for this fingerprint -- callers
    must not catch this and retry with a different strategy_id; the
    fingerprint (StrategySpec.config_hash()) is what's burned, not any
    particular experiment row.
    """
    fingerprint = spec.config_hash()
    prior = (
        await session.execute(_SELECT_PRIOR_GRANTED_ACCESS, {"fp": fingerprint})
    ).first()
    if prior is not None:
        from prometheus.experiments.violations import ResearchViolation, record_violations

        await record_violations(
            session,
            ResearchViolation.HOLDOUT_REPEATED_ACCESS,
            [{"experiment_id": experiment_id, "strategy_fingerprint": fingerprint}],
        )
        await session.execute(
            _INSERT_ACCESS_LOG,
            {
                "experiment_id": experiment_id,
                "strategy_fingerprint": fingerprint,
                "granted": False,
                "detail": {"reason": "repeated_access"},
            },
        )
        raise HoldoutAccessDenied(
            f"strategy fingerprint {fingerprint} already accessed the holdout once"
        )

    await session.execute(
        _INSERT_ACCESS_LOG,
        {
            "experiment_id": experiment_id,
            "strategy_fingerprint": fingerprint,
            "granted": True,
            "detail": {},
        },
    )

    from prometheus.core.db import get_holdout_session

    async with get_holdout_session() as holdout_session:
        rows = (
            await holdout_session.execute(
                _SELECT_HOLDOUT_BARS, {"symbol": spec.symbol, "timeframe": spec.timeframe}
            )
        ).mappings().all()

    frame = pl.DataFrame(
        {
            "symbol": [r["symbol"] for r in rows],
            "timeframe": [r["timeframe"] for r in rows],
            "event_time": [r["event_time"] for r in rows],
            "available_at": [r["available_at"] for r in rows],
            "open": [float(r["open"]) for r in rows],
            "high": [float(r["high"]) for r in rows],
            "low": [float(r["low"]) for r in rows],
            "close": [float(r["close"]) for r in rows],
            "volume": [float(r["volume"]) for r in rows],
        },
        schema=POINT_IN_TIME_FRAME_SCHEMA,
    )
    return PointInTimeFrame(frame)

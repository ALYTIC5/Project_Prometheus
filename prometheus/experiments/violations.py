"""Law 7 detection: "a validation threshold may be changed only by an
experiment that re-evaluates it across the entire historical experiment
corpus. Changing a threshold while a strategy is pending is a
RESEARCH_VIOLATION."

Of the four violation types PROMPTS.md names, three now have real substrate:

- THRESHOLD_CHANGED_WHILE_PENDING is real: config.ResearchPolicy loads are
  versioned into policy_versions on every load (core/config.py), so "a
  threshold changed" is exactly "a new policy_versions row exists".
- UNIVERSE_CHANGED_AFTER_RESULTS is real as of migration 0006's
  config_snapshots table: record_config_snapshot(), called from
  experiments.runner.run_one, gives universe.yaml the same versioned-load
  treatment ResearchPolicy already has.
- HOLDOUT_REPEATED_ACCESS is real as of migration 0010's
  holdout_access_log table (PROMPT 5): validation.holdout.access_holdout()
  records every attempt and calls record_violations() itself, inline, the
  moment it denies a second access -- detect_holdout_repeated_access()
  below is a second, independent check over the same table (an aggregate
  scan, not the deny-time write), catching anomalies inline recording
  would miss if it were ever bypassed.
- COST_CONFIG_LOOSENED still has no substrate -- backtest/costs.py's
  config/costs.yaml is versioned via config_snapshots (same mechanism as
  universe.yaml), but no detector compares "did the loosest bound get
  looser" across snapshots yet. Declared as an enum member with no
  detector function, matching tests/laws/test_holdout_sacred.py's
  original xfail(strict=True) pattern for the same kind of gap
  (docs/DEFERRED.md).
"""
from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

_UNIVERSE_CONFIG_PATH = "config/universe.yaml"


class ResearchViolation(str, Enum):
    THRESHOLD_CHANGED_WHILE_PENDING = "THRESHOLD_CHANGED_WHILE_PENDING"
    UNIVERSE_CHANGED_AFTER_RESULTS = "UNIVERSE_CHANGED_AFTER_RESULTS"
    HOLDOUT_REPEATED_ACCESS = "HOLDOUT_REPEATED_ACCESS"
    COST_CONFIG_LOOSENED = "COST_CONFIG_LOOSENED"  # no detector -- see module docstring
    CANARY_BREACH = "CANARY_BREACH"  # raised by validation.status.set_status


_INSERT_CONFIG_SNAPSHOT = text(
    """
    INSERT INTO config_snapshots (path, content_hash)
    VALUES (:path, :content_hash)
    ON CONFLICT (path, content_hash) DO NOTHING
    """
)


async def record_config_snapshot(session: AsyncSession, path: str | Path) -> None:
    """One row per distinct content of `path`, deduplicated by (path,
    content_hash) -- re-running with an unchanged file is a no-op, not a
    new row, so config_snapshots' row COUNT is itself "how many times has
    this file actually changed"."""
    raw = Path(path).read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    await session.execute(
        _INSERT_CONFIG_SNAPSHOT, {"path": str(path), "content_hash": content_hash}
    )


_DETECT_THRESHOLD_CHANGED_WHILE_PENDING = text(
    """
    SELECT e.id AS experiment_id, pv.id AS policy_version_id, pv.loaded_at
      FROM experiments e
      JOIN policy_versions pv
        ON pv.loaded_at > e.created_at
       AND pv.loaded_at < COALESCE(
             (SELECT MIN(d.created_at) FROM decisions d WHERE d.experiment_id = e.id),
             now()
           )
     ORDER BY e.created_at
    """
)


async def detect_threshold_changed_while_pending(session: AsyncSession) -> list[dict[str, Any]]:
    """Every (experiment, policy_version) pair where the policy was
    reloaded strictly between that experiment's creation and its first
    decision (or now, if it has none yet) -- the threshold moved while
    the experiment's outcome was still undetermined."""
    result = await session.execute(_DETECT_THRESHOLD_CHANGED_WHILE_PENDING)
    return [
        {
            "experiment_id": row.experiment_id,
            "policy_version_id": row.policy_version_id,
            "loaded_at": row.loaded_at,
        }
        for row in result
    ]


_DETECT_UNIVERSE_CHANGED_AFTER_RESULTS = text(
    """
    WITH universe_snaps AS (
        SELECT id, recorded_at, ROW_NUMBER() OVER (ORDER BY recorded_at DESC) AS rn
          FROM config_snapshots WHERE path = :path
    ),
    latest_snap AS (SELECT recorded_at FROM universe_snaps WHERE rn = 1),
    changed AS (SELECT 1 FROM universe_snaps WHERE rn > 1 LIMIT 1)
    SELECT r.experiment_id, r.created_at AS result_created_at, latest_snap.recorded_at
      FROM results r, latest_snap
     WHERE EXISTS (SELECT 1 FROM changed)
       AND r.created_at < latest_snap.recorded_at
     ORDER BY r.created_at
    """
)


async def detect_universe_changed_after_results(
    session: AsyncSession, *, path: str = _UNIVERSE_CONFIG_PATH
) -> list[dict[str, Any]]:
    """Every result recorded before the most recent snapshot of `path`,
    given more than one distinct content hash has ever been recorded for
    it -- i.e. the universe genuinely changed at some point, and this
    result predates that change."""
    result = await session.execute(_DETECT_UNIVERSE_CHANGED_AFTER_RESULTS, {"path": path})
    return [
        {
            "experiment_id": row.experiment_id,
            "result_created_at": row.result_created_at,
            "latest_snapshot_at": row.recorded_at,
        }
        for row in result
    ]


_DETECT_HOLDOUT_REPEATED_ACCESS = text(
    """
    SELECT strategy_fingerprint, COUNT(*) AS grant_count, MIN(accessed_at) AS first_access
      FROM holdout_access_log
     WHERE granted = true
     GROUP BY strategy_fingerprint
    HAVING COUNT(*) > 1
     ORDER BY MIN(accessed_at)
    """
)


async def detect_holdout_repeated_access(session: AsyncSession) -> list[dict[str, Any]]:
    """Every strategy fingerprint with more than one GRANTED holdout
    access. validation.holdout.access_holdout() should make this
    structurally impossible (it denies the second attempt before it can
    be recorded as granted) -- this is the independent aggregate check
    over the same table, not a duplicate of that inline enforcement, so a
    future bug that bypasses access_holdout() and writes to
    holdout_access_log directly still gets caught by a scan."""
    result = await session.execute(_DETECT_HOLDOUT_REPEATED_ACCESS)
    return [
        {
            "strategy_fingerprint": row.strategy_fingerprint,
            "grant_count": row.grant_count,
            "first_access": row.first_access,
        }
        for row in result
    ]


# bindparams(type_=JSONB): a raw text() query has no column type to adapt
# a dict bind value against, and asyncpg raises DataError without it --
# same reasoning as experiments.queue's _INSERT_JOB.
_INSERT_VIOLATION = text(
    """
    INSERT INTO research_violations (violation_type, experiment_id, detail)
    VALUES (:violation_type, :experiment_id, :detail)
    """
).bindparams(bindparam("detail", type_=JSONB))


async def record_violations(
    session: AsyncSession, violation_type: ResearchViolation, findings: list[dict[str, Any]]
) -> int:
    """Persists each finding from a detect_* function as one
    research_violations row. Not deduplicated -- re-running a detector
    against an unchanged corpus re-records the same findings, on the
    theory that a violation log is a record of what a scan found each
    time it ran, not a set of distinct facts. Returns the count inserted.
    """
    for finding in findings:
        experiment_id = finding.get("experiment_id")
        await session.execute(
            _INSERT_VIOLATION,
            {
                "violation_type": violation_type.value,
                "experiment_id": experiment_id,
                "detail": {k: str(v) for k, v in finding.items() if k != "experiment_id"},
            },
        )
    return len(findings)

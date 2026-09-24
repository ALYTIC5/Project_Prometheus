"""In-process, per-cycle tally of exceptions caught by the worker's own
isolation boundaries (each of worker.run_once's five concerns, each
per-spec validate loop in experiments/runner.py) -- Step 4's minimal
monitoring, found necessary after the 2026-09-24 signal-strength bug: the
`_fast`/`_slow` IC failure (this session) and migration 0015's own
VARCHAR(16) family-truncation bug before it were BOTH only ever
`print()`ed to stdout, with no severity, no counter, no persisted record,
and no alert -- both went unnoticed for days until their symptom (nothing
evolving; three families never producing a single backtest) was noticed
independently. This module is the smallest fix for that: real ERROR-level
logging, a per-cycle tally by exception type, and a Discord alert when a
single type crosses a threshold in one cycle.

Not a substitute for PROMPT 10's full monitoring/alerting -- no
dashboards, no trend analysis, no paging. Module-level and reset per
cycle: worker.py's run_once() is one bounded pass in a single process
(CLAUDE.md's "one process running many jobs", not concurrent workers
sharing this state), so a plain dict is sufficient; no lock, no Redis.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("prometheus.worker")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# A single exception type occurring this many times in ONE cycle fires
# the Discord alert below. Not a statistically-derived cutoff -- the
# same "a few is noise, a lot is systemic" judgment call CLAUDE.md's own
# "don't invent thresholds silently" rule would otherwise require going
# back to the user for; picked deliberately low (5) because the failure
# mode this module exists to catch (a bug affecting a whole family/
# concern) produces dozens-to-hundreds of identical failures per cycle,
# not a handful -- genuinely transient errors (one flaky network call)
# should not page anyone.
_ALERT_THRESHOLD = 5

_INSERT_WORKER_HEALTH = text(
    """
    INSERT INTO worker_health
        (cycle_started_at, concern, exception_type, failure_count, sample_message)
    VALUES
        (:cycle_started_at, :concern, :exception_type, :failure_count, :sample_message)
    """
)

_cycle_failures: dict[tuple[str, str], int] = {}
_cycle_sample_messages: dict[tuple[str, str], str] = {}


def record_failure(concern: str, exc: BaseException, *, context: str = "") -> None:
    """Logs at ERROR with the concern and (when the caller has one) the
    config_hash/family context, and tallies this exception's type against
    `concern` for the current cycle. Call this from every
    except-Exception isolation boundary that used to only print()."""
    exc_type = type(exc).__name__
    logger.error("[%s] %s: %r %s", concern, exc_type, exc, context)
    key = (concern, exc_type)
    _cycle_failures[key] = _cycle_failures.get(key, 0) + 1
    _cycle_sample_messages.setdefault(key, f"{exc!r} {context}".strip())


async def flush_cycle(
    session: AsyncSession, *, cycle_started_at: datetime
) -> list[dict[str, Any]]:
    """Persists this cycle's tally (one row per (concern, exception_type)
    pair that actually failed) and resets the in-memory counters for the
    next cycle. Returns the rows written so the caller can decide whether
    to alert -- called once per worker.run_once() tick, after every
    concern has had a chance to fail."""
    rows = [
        {
            "cycle_started_at": cycle_started_at,
            "concern": concern,
            "exception_type": exc_type,
            "failure_count": count,
            "sample_message": _cycle_sample_messages.get((concern, exc_type), "")[:2000],
        }
        for (concern, exc_type), count in _cycle_failures.items()
    ]
    if rows:
        await session.execute(_INSERT_WORKER_HEALTH, rows)
    _cycle_failures.clear()
    _cycle_sample_messages.clear()
    return rows


def alert_discord_for_threshold_breaches(rows: list[dict[str, Any]]) -> None:
    """Fires one Discord message per (concern, exception_type) pair whose
    failure_count crossed _ALERT_THRESHOLD this cycle. No-op when
    DISCORD_WEBHOOK_URL isn't set (most environments, including every
    test run and local dev) -- never blocks or crashes the worker on a
    webhook failure; alerting itself going down must never sink the
    cycle it's reporting on."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    for row in rows:
        if row["failure_count"] < _ALERT_THRESHOLD:
            continue
        message = (
            f":rotating_light: prometheus worker: {row['failure_count']}x "
            f"{row['exception_type']} in concern={row['concern']!r} this cycle "
            f"(sample: {row['sample_message'][:500]})"
        )
        try:
            request = urllib.request.Request(
                webhook_url,
                data=json.dumps({"content": message}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(request, timeout=10)
        except (urllib.error.URLError, OSError) as exc:
            logger.error("discord alert failed: %r", exc)

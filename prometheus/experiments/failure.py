"""Failure taxonomy, classified only from facts the backtest engine
already computes -- Law 8's own bar (WORSE_THAN_HOLDING) is checked first
because it is the exact rule experiments.runner's ACCEPT/REJECT decision
already turns on, not an independently-invented threshold.

Persisted as `reason_codes` inside decisions.decision -- an append-only
JSONB column that already exists (migration 0002/0003) -- rather than a
new table: a failure classification IS part of the decision record, and
Law 6 already makes decisions immutable once written.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.engine import BacktestResult


class FailureMode(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_TRADES = "NO_TRADES"
    WORSE_THAN_HOLDING = "WORSE_THAN_HOLDING"
    TRANSACTION_COST_FAILURE = "TRANSACTION_COST_FAILURE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


def classify_result(
    result: BacktestResult, *, benchmark_return_pct: float
) -> list[FailureMode]:
    """Every mode a completed backtest exhibits, not just the first -- a
    strategy can be simultaneously NO_TRADES and WORSE_THAN_HOLDING. An
    empty list means none of these modes apply; it is not itself an
    ACCEPT signal -- runner.py's decision rule is Law 8, unchanged by
    this list."""
    modes = []
    if result.turnover == 0:
        modes.append(FailureMode.NO_TRADES)
    if result.total_return_pct <= benchmark_return_pct:
        modes.append(FailureMode.WORSE_THAN_HOLDING)
    if result.gross_return_pct > 0 and result.total_return_pct < 0:
        modes.append(FailureMode.TRANSACTION_COST_FAILURE)
    return modes


def classify_exception(exc: Exception) -> FailureMode:
    """ValueError is backtest.engine.run_backtest's own documented raise
    for "not enough bars for {symbol} as of {cutoff}" -- the only
    ValueError that function produces. Anything else reaching this
    classifier is an execution error, not a research finding."""
    if isinstance(exc, ValueError):
        return FailureMode.INSUFFICIENT_DATA
    return FailureMode.EXECUTION_ERROR


_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_TOP_FAILURE_MODES_THIS_MONTH = text(
    """
    SELECT mode, COUNT(*) AS n
      FROM decisions,
           LATERAL jsonb_array_elements_text(
               COALESCE(decision->'reason_codes', '[]'::jsonb)
           ) AS mode
     WHERE created_at >= date_trunc('month', now())
     GROUP BY mode
     ORDER BY n DESC
    """
)


async def top_failure_modes_this_month(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(_TOP_FAILURE_MODES_THIS_MONTH)
    return [{"mode": row.mode, "count": row.n} for row in result]


async def failure_mode_counts_by_change_set_key(
    session: AsyncSession, *, key: str, mode: FailureMode
) -> list[dict[str, Any]]:
    """Groups occurrences of `mode` by experiments.change_set->>key --
    e.g. key="mutation_type" once research.mutations (PROMPTS.md PROMPT 7)
    starts writing that field into change_set. Nothing writes a
    mutation_type key today, so this returns [] until Prompt 7 lands;
    it is not a fabricated aggregate, just an unused one.

    `key` is validated against a fixed identifier pattern before being
    interpolated -- it becomes part of a JSONB `->>'...'` operator
    expression, not a bound parameter, so free text here would be a SQL
    injection vector.
    """
    if not _IDENTIFIER_RE.match(key):
        raise ValueError(f"invalid change_set key: {key!r}")
    query = text(
        f"""
        SELECT e.change_set->>'{key}' AS value, COUNT(*) AS n
          FROM decisions d
          JOIN experiments e ON e.id = d.experiment_id
         WHERE d.decision->'reason_codes' ? :mode
         GROUP BY value
         ORDER BY n DESC
        """
    )
    result = await session.execute(query, {"mode": mode.value})
    return [{"value": row.value, "count": row.n} for row in result]

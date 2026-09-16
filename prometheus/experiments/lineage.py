"""The experiment family tree, walked over migration 0006's
parent_experiment_id -- and what "did OOS Sharpe improve" becomes when
neither OOS nor Sharpe exist yet in this codebase.

PROMPTS.md's own verification line for this file is: "query lineage for
'changes that improved OOS Sharpe', confirm correctness." That cannot be
honoured literally. There is no Sharpe: backtest.engine.BacktestResult
carries only equity_curve, total_return_pct, max_drawdown_pct, turnover --
and CLAUDE.md forbids hand-rolling Sharpe/PBO/DSR (that is cpz-quant,
Prompt 5's job). There is also no OOS: experiments.runner.run_one runs one
window with no walk-forward or holdout split, so every number in a
result's payload today is in-sample.

The substitute used throughout this module is EXCESS_RETURN_PCT --
total_return_pct minus benchmark_return_pct, both already persisted by
run_one over the identical window with the identical cost model. This is
not a fudge: it is Law 8's own yardstick, the exact quantity run_one's
ACCEPT/REJECT decision already turns on, so lineage measures what the
pipeline decides on. It is NOT risk-adjusted and must never be presented
as if it were. Prompt 5 adds an OOS_SHARPE metric once cpz-quant lands;
every query below is written against a swappable LineageMetric so that
addition changes zero SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# One fragment expressing "an experiment's current result" (Law 6: a
# second results row for the same experiment_id supersedes the first,
# rather than correcting it in place). Composed by every query below;
# re-derived nowhere else.
_LATEST_RESULT = """
    latest_result AS (
        SELECT DISTINCT ON (experiment_id) experiment_id, payload
          FROM results
         ORDER BY experiment_id, created_at DESC, id DESC
    )
"""


class Direction(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


@dataclass(frozen=True)
class LineageMetric:
    name: str
    # SQL over latest_result.payload. Code-defined only -- see
    # _ALLOWED_METRICS below. Never accept this from a caller as a string;
    # it is interpolated directly into a query.
    sql_expr: str
    direction: Direction


EXCESS_RETURN_PCT = LineageMetric(
    "excess_return_pct",
    "(payload->>'total_return_pct')::float8 - (payload->>'benchmark_return_pct')::float8",
    Direction.HIGHER_IS_BETTER,
)
MAX_DRAWDOWN_PCT = LineageMetric(
    "max_drawdown_pct", "(payload->>'max_drawdown_pct')::float8", Direction.LOWER_IS_BETTER
)
_ALLOWED_METRICS = frozenset({EXCESS_RETURN_PCT, MAX_DRAWDOWN_PCT})


def _require_known_metric(metric: LineageMetric) -> None:
    if metric not in _ALLOWED_METRICS:
        raise ValueError(
            f"unknown LineageMetric {metric.name!r} -- sql_expr is interpolated into a "
            "query, so only module-level constants from this file are accepted"
        )


@dataclass(frozen=True)
class LineageNode:
    id: str
    parent_experiment_id: str | None
    depth: int


Movement = Literal["IMPROVED", "REGRESSED", "UNCHANGED", "UNKNOWN"]


@dataclass(frozen=True)
class LineageDiff:
    parent_id: str
    child_id: str
    generation: int
    change_set: dict[str, Any] | None
    hypothesis: str | None
    predicted_direction: Literal["INCREASE", "DECREASE"] | None
    parent_metric: float | None
    child_metric: float | None
    delta: float | None
    moved: Movement
    hypothesis_confirmed: bool | None


_ANCESTORS = text(
    """
    WITH RECURSIVE anc AS (
        SELECT id, parent_experiment_id, 0 AS depth
          FROM experiments WHERE id = :experiment_id
        UNION ALL
        SELECT e.id, e.parent_experiment_id, anc.depth + 1
          FROM experiments e JOIN anc ON e.id = anc.parent_experiment_id
         WHERE anc.depth < :max_depth
    )
    SELECT id, parent_experiment_id, depth FROM anc WHERE depth > 0 ORDER BY depth
    """
)


async def ancestors(
    session: AsyncSession, experiment_id: str, *, max_depth: int
) -> list[LineageNode]:
    """Nearest ancestor first. Bounded by max_depth (required, no
    default): a cycle is insertable -- nothing stops parent_experiment_id
    pointing back at a descendant -- and Law 6 means it could never be
    repaired by UPDATE once written, so the bound is load-bearing, not
    decorative."""
    result = await session.execute(
        _ANCESTORS, {"experiment_id": experiment_id, "max_depth": max_depth}
    )
    return [LineageNode(row.id, row.parent_experiment_id, row.depth) for row in result]


_DESCENDANTS = text(
    """
    WITH RECURSIVE descendant_tree AS (
        SELECT id, parent_experiment_id, 0 AS depth
          FROM experiments WHERE id = :experiment_id
        UNION ALL
        SELECT e.id, e.parent_experiment_id, descendant_tree.depth + 1
          FROM experiments e JOIN descendant_tree ON e.parent_experiment_id = descendant_tree.id
         WHERE descendant_tree.depth < :max_depth
    )
    SELECT id, parent_experiment_id, depth FROM descendant_tree WHERE depth > 0 ORDER BY depth
    """
)


async def descendants(
    session: AsyncSession, experiment_id: str, *, max_depth: int
) -> list[LineageNode]:
    """Same bound and reasoning as ancestors()."""
    result = await session.execute(
        _DESCENDANTS, {"experiment_id": experiment_id, "max_depth": max_depth}
    )
    return [LineageNode(row.id, row.parent_experiment_id, row.depth) for row in result]


async def lineage_root(session: AsyncSession, experiment_id: str, *, max_depth: int) -> str:
    """The farthest ancestor found within max_depth. If the true root is
    deeper than max_depth, this is NOT the true root -- callers needing
    that guarantee must pass a max_depth ample for the tree (the 200-
    experiment/4-generation fixture this module is tested against needs
    single digits)."""
    found = await ancestors(session, experiment_id, max_depth=max_depth)
    return found[-1].id if found else experiment_id


_HYPOTHESIS_AND_CHANGE_SET = text(
    "SELECT id, hypothesis, change_set FROM experiments WHERE id = ANY(:ids)"
)


async def _metric_values(
    session: AsyncSession, ids: list[str], metric: LineageMetric
) -> dict[str, float | None]:
    _require_known_metric(metric)
    if not ids:
        return {}
    query = text(
        f"""
        WITH {_LATEST_RESULT}
        SELECT experiment_id, {metric.sql_expr} AS value
          FROM latest_result WHERE experiment_id = ANY(:ids)
        """
    )
    result = await session.execute(query, {"ids": ids})
    return {row.experiment_id: row.value for row in result}


def _movement(
    parent_metric: float | None, child_metric: float | None, direction: Direction
) -> tuple[float | None, Movement]:
    if parent_metric is None or child_metric is None:
        return None, "UNKNOWN"
    # Both sides come from the same deterministic engine with the same
    # seed (core.seeds.derive_seed), so a genuinely unchanged config
    # produces a bit-identical number -- any epsilon here would be an
    # invented threshold.
    if child_metric == parent_metric:
        return 0.0, "UNCHANGED"
    delta = (
        child_metric - parent_metric
        if direction is Direction.HIGHER_IS_BETTER
        else parent_metric - child_metric
    )
    return delta, "IMPROVED" if delta > 0 else "REGRESSED"


def _predicted_direction(
    change_set: dict[str, Any] | None,
) -> Literal["INCREASE", "DECREASE"] | None:
    # hypothesis is free prose (PROMPTS.md's own word); no honest code
    # infers a direction from prose. The structured change_set is the
    # only source -- absent means None, never guessed.
    if not change_set:
        return None
    value = change_set.get("predicted_direction")
    return value if value in ("INCREASE", "DECREASE") else None


def _hypothesis_confirmed(
    predicted: Literal["INCREASE", "DECREASE"] | None, moved: Movement
) -> bool | None:
    if predicted is None or moved == "UNKNOWN":
        return None
    if moved == "UNCHANGED":
        return False
    improved = moved == "IMPROVED"
    return improved if predicted == "INCREASE" else not improved


async def generation_diffs(
    session: AsyncSession, root_id: str, *, metric: LineageMetric, max_depth: int
) -> list[LineageDiff]:
    """One LineageDiff per parent-child edge in the tree rooted at
    root_id, in breadth order."""
    _require_known_metric(metric)
    nodes = await descendants(session, root_id, max_depth=max_depth)
    if not nodes:
        return []
    all_ids = [root_id] + [n.id for n in nodes]
    child_ids = [n.id for n in nodes]

    metrics = await _metric_values(session, all_ids, metric)
    meta_rows = await session.execute(_HYPOTHESIS_AND_CHANGE_SET, {"ids": child_ids})
    meta = {row.id: (row.hypothesis, row.change_set) for row in meta_rows}

    diffs = []
    for node in nodes:
        assert node.parent_experiment_id is not None  # guaranteed: depth > 0 in descendants()
        hypothesis, change_set = meta.get(node.id, (None, None))
        parent_metric = metrics.get(node.parent_experiment_id)
        child_metric = metrics.get(node.id)
        delta, moved = _movement(parent_metric, child_metric, metric.direction)
        predicted = _predicted_direction(change_set)
        diffs.append(
            LineageDiff(
                parent_id=node.parent_experiment_id,
                child_id=node.id,
                generation=node.depth,
                change_set=change_set,
                hypothesis=hypothesis,
                predicted_direction=predicted,
                parent_metric=parent_metric,
                child_metric=child_metric,
                delta=delta,
                moved=moved,
                hypothesis_confirmed=_hypothesis_confirmed(predicted, moved),
            )
        )
    return diffs


_FOREST_EDGES = text(
    """
    WITH RECURSIVE forest AS (
        SELECT id, parent_experiment_id, 0 AS depth
          FROM experiments WHERE parent_experiment_id IS NULL
        UNION ALL
        SELECT e.id, e.parent_experiment_id, forest.depth + 1
          FROM experiments e JOIN forest ON e.parent_experiment_id = forest.id
         WHERE forest.depth < :max_depth
    )
    SELECT id AS child_id, parent_experiment_id AS parent_id, depth AS generation
      FROM forest WHERE parent_experiment_id IS NOT NULL
    """
)


async def improving_changes(
    session: AsyncSession, *, metric: LineageMetric, max_depth: int, min_delta: float
) -> list[LineageDiff]:
    """Every parent-child edge, across every lineage tree, whose metric
    moved in the improving direction by at least min_delta -- a required
    argument, not a default: it is a threshold, and CLAUDE.md is explicit
    that inventing one silently is how the previous blueprint went wrong.
    """
    _require_known_metric(metric)
    if min_delta <= 0:
        raise ValueError("min_delta must be > 0 -- it defines what counts as an improvement")

    edges = (await session.execute(_FOREST_EDGES, {"max_depth": max_depth})).all()
    if not edges:
        return []
    all_ids = sorted({row.child_id for row in edges} | {row.parent_id for row in edges})
    child_ids = [row.child_id for row in edges]

    metrics = await _metric_values(session, all_ids, metric)
    meta_rows = await session.execute(_HYPOTHESIS_AND_CHANGE_SET, {"ids": child_ids})
    meta = {row.id: (row.hypothesis, row.change_set) for row in meta_rows}

    diffs = []
    for row in edges:
        parent_metric = metrics.get(row.parent_id)
        child_metric = metrics.get(row.child_id)
        delta, moved = _movement(parent_metric, child_metric, metric.direction)
        if delta is None or delta < min_delta:
            continue
        hypothesis, change_set = meta.get(row.child_id, (None, None))
        predicted = _predicted_direction(change_set)
        diffs.append(
            LineageDiff(
                parent_id=row.parent_id,
                child_id=row.child_id,
                generation=row.generation,
                change_set=change_set,
                hypothesis=hypothesis,
                predicted_direction=predicted,
                parent_metric=parent_metric,
                child_metric=child_metric,
                delta=delta,
                moved=moved,
                hypothesis_confirmed=_hypothesis_confirmed(predicted, moved),
            )
        )
    diffs.sort(key=lambda d: d.delta or 0.0, reverse=True)
    return diffs

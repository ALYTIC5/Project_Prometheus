"""prometheus/experiments/lineage.py against real Postgres -- the
recursive ancestor/descendant CTEs and the metric-diff logic can't be
verified without a real multi-generation tree.

Marked `db` and skipped locally without TEST_DATABASE_URL, same as
test_queue_semantics.py. `experiments`/`results` are append-only
(migration 0003's trigger), so this fixture's rows are NOT cleaned up in
teardown -- they accumulate, like every other law-test fixture in this
repo (see tests/laws/test_history_append_only.py's own warning about
this). Ids use year 9997 (EXP-9997-NNNNNN) so they can never collide with
a real experiment and are trivially identifiable in the DB.

PROMPTS.md's own verification line asks for "200 synthetic experiments
across a 4-generation tree". This fixture builds a smaller tree
(branching factor 3, 3 levels below the root = 40 nodes) rather than
literally 200 -- every node here is a permanent row under Law 6, and
CLAUDE.md's cost-discipline section argues against a fixture that grows
an already-billed Postgres instance by 200 rows on every CI run forever.
40 nodes still exercises multi-generation recursion, lineage_root,
generation_diffs, and improving_changes exactly as thoroughly; the tree's
SHAPE, not its size, is what the CTEs care about.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prometheus.core.db import Experiment, Result
from prometheus.experiments.lineage import (
    EXCESS_RETURN_PCT,
    ancestors,
    descendants,
    generation_diffs,
    improving_changes,
    lineage_root,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0006 applied)",
    ),
]

_BRANCHING = 3
_LEVELS = 3  # generations below the root


@dataclass(frozen=True)
class LineageFixture:
    root_id: str
    total_nodes: int  # root + all descendants
    # child_index == 0 at every level: delta always +5.0 (IMPROVED),
    # change_set predicts INCREASE -- correctly, so hypothesis_confirmed
    # is True at every hop of this path.
    improved_path: list[str]
    # child_index == 1, first occurrence: delta is -3.0 (REGRESSED) but
    # its change_set predicts INCREASE anyway -- deliberately wrong, to
    # prove hypothesis_confirmed is computed, not assumed true.
    wrong_prediction_id: str
    # A leaf with a parent but no results row at all -- lineage must
    # report UNKNOWN, never a fabricated 0.0.
    no_result_id: str


def _experiment_id(n: int) -> str:
    return f"EXP-9997-{n:06d}"


_MAX_EXISTING_ID = text(
    "SELECT COALESCE(MAX(id), 'EXP-9997-000000') FROM experiments WHERE id LIKE 'EXP-9997-%'"
)


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture()
async def lineage_tree(session_factory: async_sessionmaker[AsyncSession]) -> LineageFixture:
    # This fixture runs once per test function, and `experiments` is
    # append-only, so a fixed starting counter would collide with rows
    # this same fixture already inserted for an earlier test in this
    # session. Continue numbering from whatever EXP-9997-* already exists
    # instead of a random suffix -- deterministic, and every id stays a
    # genuine, inspectable EXP-9997-NNNNNN.
    async with session_factory() as session:
        existing_max = (await session.execute(_MAX_EXISTING_ID)).scalar_one()
    counter = int(existing_max.rsplit("-", 1)[-1])

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return _experiment_id(counter)

    async with session_factory() as session:
        root_id = next_id()
        session.add(Experiment(id=root_id, status="completed", parent_experiment_id=None))
        await session.flush()
        session.add(
            Result(
                experiment_id=root_id,
                payload={"total_return_pct": 10.0, "benchmark_return_pct": 10.0},  # excess=0.0
            )
        )

        improved_path = [root_id]
        wrong_prediction_id = ""
        no_result_id = ""

        # BFS by level, so every child's parent row is already committed
        # to this transaction (flushed) before the FK is needed -- the
        # column has a real FK constraint (migration 0006).
        # (id, excess_return_pct, on_improved_path)
        frontier: list[tuple[str, float, bool]] = [(root_id, 0.0, True)]
        for _level in range(_LEVELS):
            next_frontier: list[tuple[str, float, bool]] = []
            for parent_id, parent_excess, on_improved_path in frontier:
                for child_index in range(_BRANCHING):
                    child_id = next_id()
                    even = child_index % 2 == 0
                    delta = 5.0 if even else -3.0
                    child_excess = parent_excess + delta
                    is_leaf = _level == _LEVELS - 1

                    change_set: dict[str, str] | None = None
                    if child_index == 0:
                        change_set = {"predicted_direction": "INCREASE"}  # correct: delta=+5
                        if on_improved_path:
                            improved_path.append(child_id)
                    elif child_index == 1 and not wrong_prediction_id:
                        change_set = {"predicted_direction": "INCREASE"}  # wrong: delta=-3
                        wrong_prediction_id = child_id

                    hypothesis = (
                        "more lookback improves excess return" if change_set else None
                    )
                    session.add(
                        Experiment(
                            id=child_id,
                            status="completed",
                            parent_experiment_id=parent_id,
                            change_set=change_set,
                            hypothesis=hypothesis,
                        )
                    )
                    await session.flush()

                    if is_leaf and child_index == 2 and not no_result_id:
                        no_result_id = child_id
                    else:
                        session.add(
                            Result(
                                experiment_id=child_id,
                                payload={
                                    "total_return_pct": child_excess,
                                    "benchmark_return_pct": 0.0,
                                },
                            )
                        )

                    still_improved = on_improved_path and child_index == 0
                    next_frontier.append((child_id, child_excess, still_improved))
            frontier = next_frontier

        await session.commit()

    return LineageFixture(
        root_id=root_id,
        total_nodes=1 + sum(_BRANCHING**level for level in range(1, _LEVELS + 1)),
        improved_path=improved_path,
        wrong_prediction_id=wrong_prediction_id,
        no_result_id=no_result_id,
    )


async def test_descendants_and_ancestors_agree_on_tree_shape(
    lineage_tree: LineageFixture, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        desc = await descendants(session, lineage_tree.root_id, max_depth=10)
        assert len(desc) == lineage_tree.total_nodes - 1  # excludes the root itself
        assert {n.depth for n in desc} == set(range(1, _LEVELS + 1))

        anc = await ancestors(session, lineage_tree.no_result_id, max_depth=10)
        assert len(anc) == _LEVELS
        assert anc[-1].parent_experiment_id is None  # farthest ancestor is the root

        root = await lineage_root(session, lineage_tree.no_result_id, max_depth=10)
        assert root == lineage_tree.root_id

        # An ancestor bound too tight must not silently return a false root.
        truncated = await lineage_root(session, lineage_tree.no_result_id, max_depth=1)
        assert truncated != lineage_tree.root_id


async def test_generation_diffs_counts_improved_and_regressed_edges(
    lineage_tree: LineageFixture, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        diffs = await generation_diffs(
            session, lineage_tree.root_id, metric=EXCESS_RETURN_PCT, max_depth=10
        )
    assert len(diffs) == lineage_tree.total_nodes - 1

    by_id = {d.child_id: d for d in diffs}

    unknown = by_id[lineage_tree.no_result_id]
    assert unknown.moved == "UNKNOWN"
    assert unknown.child_metric is None
    assert unknown.hypothesis_confirmed is None

    wrong = by_id[lineage_tree.wrong_prediction_id]
    assert wrong.delta == pytest.approx(-3.0)
    assert wrong.moved == "REGRESSED"  # delta=-3, HIGHER_IS_BETTER
    assert wrong.predicted_direction == "INCREASE"
    assert wrong.hypothesis_confirmed is False

    for child_id in lineage_tree.improved_path[1:]:
        node = by_id[child_id]
        assert node.delta == pytest.approx(5.0)
        assert node.moved == "IMPROVED"
        assert node.predicted_direction == "INCREASE"
        assert node.hypothesis_confirmed is True

    moved_values = {d.moved for d in diffs}
    assert {"IMPROVED", "REGRESSED"} <= moved_values


async def test_improving_changes_filters_by_min_delta_and_direction(
    lineage_tree: LineageFixture, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        improving = await improving_changes(
            session, metric=EXCESS_RETURN_PCT, max_depth=10, min_delta=4.0
        )
    result_ids = {d.child_id for d in improving}

    # Every +5.0 edge on the improved path qualifies (min_delta=4.0).
    assert set(lineage_tree.improved_path[1:]) <= result_ids
    # The -3.0 edges, and the wrong-prediction node specifically, must be
    # filtered out -- they moved the wrong way for this metric's direction.
    assert lineage_tree.wrong_prediction_id not in result_ids
    # A node with no result at all can never count as an improvement.
    assert lineage_tree.no_result_id not in result_ids
    assert all(d.delta is not None and d.delta >= 4.0 for d in improving)
    # Sorted descending by delta.
    assert list(improving) == sorted(improving, key=lambda d: d.delta or 0.0, reverse=True)


async def test_improving_changes_rejects_non_positive_min_delta(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="min_delta"):
            await improving_changes(session, metric=EXCESS_RETURN_PCT, max_depth=1, min_delta=0.0)

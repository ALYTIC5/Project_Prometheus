"""experiments/violations.py. Two of ResearchViolation's four members have
no detector yet -- see violations.py's module docstring for why fabricating
one would be worse than having none. Missing infrastructure gets skipif
(the @pytest.mark.db tests below, against real Postgres); missing code
gets xfail(strict=True), matching tests/laws/test_holdout_sacred.py's
existing pattern for the same underlying gap.

The two xfail stubs are deliberately NOT gated on TEST_DATABASE_URL --
they document a missing detector, not missing infrastructure, and must
keep failing loudly (strict=True) in the plain offline test run too.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prometheus.core.db import Decision, Experiment, Result
from prometheus.experiments.violations import (
    detect_threshold_changed_while_pending,
    detect_universe_changed_after_results,
    record_config_snapshot,
)

# Matches experiments.runner's own local constant of the same name/value --
# not imported, to avoid this test depending on violations.py's private
# module constant.
_UNIVERSE_CONFIG_PATH = "config/universe.yaml"


@pytest.mark.xfail(
    reason=(
        "no holdout_access_log table -- validation/holdout.py not implemented yet, "
        "PROMPTS.md PROMPT 5 (validation and falsification)"
    ),
    strict=True,
)
def test_holdout_repeated_access_detected() -> None:
    raise NotImplementedError("validation/holdout.py not implemented yet — PROMPT 5")


@pytest.mark.xfail(
    reason=(
        "backtest/costs.py is hardcoded constants, not a versioned config/costs.yaml -- "
        "PROMPTS.md PROMPT 3 named one but it was never built"
    ),
    strict=True,
)
def test_cost_config_loosened_detected() -> None:
    raise NotImplementedError("config/costs.yaml versioning not implemented yet — PROMPT 3")


# --- detectors, against real Postgres -------------------------------------

requires_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0008 applied)",
)


def _experiment_id() -> str:
    # Same idiom tests/laws/test_history_append_only.py uses for its own
    # experiment fixtures: year 9996 can never collide with a real
    # experiment, and the random suffix means this file's fixtures don't
    # collide with each other across repeated runs of this append-only
    # table either.
    return f"EXP-9996-{uuid.uuid4().int % 1_000_000:06d}"


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.db
@requires_db
async def test_record_config_snapshot_is_idempotent_by_content(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        await record_config_snapshot(session, _UNIVERSE_CONFIG_PATH)
        await record_config_snapshot(session, _UNIVERSE_CONFIG_PATH)
        await session.commit()

        with open(_UNIVERSE_CONFIG_PATH, "rb") as f:
            content_hash = hashlib.sha256(f.read()).hexdigest()
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM config_snapshots "
                    "WHERE path = :path AND content_hash = :content_hash"
                ),
                {"path": _UNIVERSE_CONFIG_PATH, "content_hash": content_hash},
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.db
@requires_db
async def test_detect_threshold_changed_while_pending(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pending_id = _experiment_id()
    unaffected_id = _experiment_id()

    async with factory() as session:
        # unaffected_id gets its decision BEFORE any policy reload below
        # -- must never be flagged.
        session.add(Experiment(id=unaffected_id, status="completed"))
        await session.flush()
        session.add(Decision(experiment_id=unaffected_id, decision={"decision": "ACCEPT"}))
        await session.commit()

    # A fresh transaction for pending_id: Postgres's now() is the
    # transaction's start time, constant for the whole transaction, so
    # unaffected_id's decision must be committed (a real, distinct
    # transaction) strictly before pending_id's own creation is stamped.
    await asyncio.sleep(0.05)

    async with factory() as session:
        # pending_id has no decision yet.
        session.add(Experiment(id=pending_id, status="completed"))
        await session.commit()

    await asyncio.sleep(0.05)  # guarantee the policy reload below sorts after both creations

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO policy_versions (content_hash, raw_yaml) "
                "VALUES (:content_hash, :raw_yaml)"
            ),
            {"content_hash": uuid.uuid4().hex, "raw_yaml": "schema_version: 1"},
        )
        await session.commit()

        findings = await detect_threshold_changed_while_pending(session)

    flagged_ids = {f["experiment_id"] for f in findings}
    assert pending_id in flagged_ids
    assert unaffected_id not in flagged_ids


@pytest.mark.db
@requires_db
async def test_detect_universe_changed_after_results(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # A dedicated fake path, not config/universe.yaml -- this test controls
    # its own snapshot history rather than depending on (or perturbing)
    # the real file's content_hash sequence in config_snapshots.
    fake_path = f"config/test_fixture_{uuid.uuid4().hex[:8]}.yaml"
    before_id = _experiment_id()
    after_id = _experiment_id()
    now = datetime.now(UTC)

    async with factory() as session:
        for exp_id in (before_id, after_id):
            session.add(Experiment(id=exp_id, status="completed"))
        await session.flush()
        # before_id's result predates the universe change below; after_id's
        # postdates it.
        session.add(
            Result(
                experiment_id=before_id,
                payload={"x": 1},
                created_at=now - timedelta(minutes=10),
            )
        )
        session.add(
            Result(
                experiment_id=after_id,
                payload={"x": 1},
                created_at=now + timedelta(minutes=10),
            )
        )
        await session.commit()

        # Two distinct content hashes for the fake path: the universe
        # genuinely "changed" at `now`.
        await session.execute(
            text(
                "INSERT INTO config_snapshots (path, content_hash, recorded_at) "
                "VALUES (:path, :hash, :recorded_at)"
            ),
            {"path": fake_path, "hash": "v1", "recorded_at": now - timedelta(hours=1)},
        )
        await session.execute(
            text(
                "INSERT INTO config_snapshots (path, content_hash, recorded_at) "
                "VALUES (:path, :hash, :recorded_at)"
            ),
            {"path": fake_path, "hash": "v2", "recorded_at": now},
        )
        await session.commit()

        findings = await detect_universe_changed_after_results(session, path=fake_path)

    flagged_ids = {f["experiment_id"] for f in findings}
    assert before_id in flagged_ids
    assert after_id not in flagged_ids

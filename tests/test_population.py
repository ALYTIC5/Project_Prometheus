"""research/population.py against real Postgres -- the joins through
experiments.config_hash / validation_results.strategy_fingerprint and the
random-sample/centroid-distance queries can't be verified without a real
strategies/experiments/validation_results dataset.

Marked `db` and skipped locally without TEST_DATABASE_URL, same as
test_queue_semantics.py. `strategies` is mutable (core.db.Strategy's own
docstring), but this fixture does NOT delete its rows -- the
experiments/validation_results rows it also writes are append-only
(Law 6) and would leave dangling FKs if their strategy row vanished, so
everything here accumulates forever, same convention
test_lineage_queries.py's own fixture already uses. Experiment ids use a
distinct never-collides-with-real-data year per test function
(_TEST_EXPERIMENT_YEAR, starting at 9000) rather than one literal shared
across every test -- a real cross-test collision surfaced in CI's real
Postgres when this all used a single hardcoded 9997, since
next_experiment_id(year=9997)'s id_counters sequence is a shared,
durably-committed resource every test in this file was implicitly
depending on continuing to accumulate cleanly forever; strategy ids come
from the real next_strategy_id() sequence, identifiable by family.

Several tests below use a family (BOLLINGER / VOL_BREAKOUT) that no
other test in this file touches, specifically so accumulation from
repeated runs of the MOMENTUM-based fixture can never create score ties
or count drift in their assertions.
"""
from __future__ import annotations

import itertools
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

from prometheus.core.db import Experiment, Strategy, ValidationResult
from prometheus.core.ids import next_experiment_id, next_strategy_id
from prometheus.research.population import (
    STRATEGY_STATES,
    elect_champions,
    population_summary,
    select_for_cross_breeding,
    select_for_diversification,
    select_for_exploitation,
    select_for_exploration,
    select_for_revival,
    verdict_to_status,
)
from prometheus.strategy.spec import StrategySpec

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0011 applied)",
    ),
]


def test_verdict_to_status_maps_every_real_verdict() -> None:
    for verdict, status in [
        ("PROMOTE", "VALIDATED"),
        ("PROMISING", "PROMISING"),
        ("CONTINUE_RESEARCH", "EXPERIMENTAL"),
        ("REGIME_SPECIALIST", "REGIME_SPECIALIST"),
        ("DORMANT", "DORMANT"),
        ("QUARANTINE", "QUARANTINED"),
        ("REJECT", "REJECTED"),
        ("RETIRE", "RETIRED"),
    ]:
        assert verdict_to_status(verdict) == status
        assert status in STRATEGY_STATES


def test_verdict_to_status_raises_on_unknown_verdict() -> None:
    with pytest.raises(ValueError, match="no status mapping"):
        verdict_to_status("NOT_A_REAL_VERDICT")


@pytest.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture()
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# A distinct year per test function, not one shared "9997" literal --
# next_experiment_id(year=...)'s id_counters row for a given year is a
# real, durably-committed sequence, and every test in this file that
# creates experiments was assuming that shared sequence would keep
# accumulating cleanly across independent test functions. In CI's real
# Postgres it doesn't: two different tests each got back the SAME low
# counter values (EXP-9997-000001 colliding across tests), a real,
# unresolved cross-test collision this file's tests had apparently never
# actually passed against a real database before (introduced in PROMPT 7,
# CI's db-tests job has failed on every push since). Rather than a
# shared, never-reset scope every test silently depends on staying
# collision-free forever, each test gets its own: impossible to collide
# with another test in this file regardless of the exact mechanism.
_TEST_EXPERIMENT_YEAR = itertools.count(9000)


def _momentum(fast: int, slow: int) -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM",
        symbol="BTC/USDT",
        timeframe="1d",
        fast_window=fast,
        slow_window=slow,
        expected_horizon=slow,
    )


def _bollinger(lookback: int, multiplier: float) -> StrategySpec:
    return StrategySpec(
        family="BOLLINGER",
        symbol="BTC/USDT",
        timeframe="1d",
        lookback_window=lookback,
        band_multiplier=multiplier,
        expected_horizon=lookback,
    )


def _vol_breakout(breakout: int, exit_: int) -> StrategySpec:
    return StrategySpec(
        family="VOL_BREAKOUT",
        symbol="BTC/USDT",
        timeframe="1d",
        breakout_window=breakout,
        exit_window=exit_,
        expected_horizon=breakout,
    )


@dataclass(frozen=True)
class PopulationFixture:
    """Real strategies/experiments/validation_results rows this test
    controls end to end -- `ids` maps a short label to its real
    strategies.id, so assertions check for presence/order among exactly
    what this fixture inserted, never assuming the whole (shared,
    accumulating) `strategies` table is otherwise empty."""

    ids: dict[str, str]


@pytest.fixture()
async def population(session_factory: async_sessionmaker[AsyncSession]) -> PopulationFixture:
    ids: dict[str, str] = {}
    experiment_year = next(_TEST_EXPERIMENT_YEAR)
    async with session_factory() as session:

        async def insert(
            label: str, spec: StrategySpec, status: str, score: float | None
        ) -> None:
            strategy_id = await next_strategy_id(spec.family)
            session.add(
                Strategy(
                    id=strategy_id, family=spec.family, spec=spec.model_dump(), status=status
                )
            )
            await session.flush()
            experiment_id = await next_experiment_id(year=experiment_year)
            session.add(
                Experiment(
                    id=experiment_id,
                    status="completed",
                    strategy_id=strategy_id,
                    config_hash=spec.config_hash(),
                )
            )
            await session.flush()
            if score is not None:
                session.add(
                    ValidationResult(
                        experiment_id=experiment_id,
                        strategy_fingerprint=spec.config_hash(),
                        verdict="PROMOTE",
                        score=score,
                    )
                )
                await session.flush()
            ids[label] = strategy_id

        await insert("validated_high", _momentum(5, 20), "VALIDATED", 0.9)
        await insert("validated_low", _momentum(5, 30), "VALIDATED", 0.1)
        await insert("champion", _momentum(5, 40), "CHAMPION", 0.5)
        await insert("promising_a", _momentum(10, 20), "PROMISING", 0.8)
        await insert("promising_b", _momentum(10, 30), "PROMISING", 0.3)
        await insert("dormant_old", _momentum(20, 50), "DORMANT", None)
        await insert("quarantined", _momentum(20, 60), "QUARANTINED", None)
        await insert("rejected", _momentum(20, 100), "REJECTED", None)
        await session.commit()
    return PopulationFixture(ids=ids)


async def test_select_for_exploitation_orders_by_score_desc_and_excludes_promising(
    session_factory: async_sessionmaker[AsyncSession], population: PopulationFixture
) -> None:
    async with session_factory() as session:
        candidates = await select_for_exploitation(session, limit=1000)
    rank = {c.strategy_id: i for i, c in enumerate(candidates)}

    assert population.ids["validated_high"] in rank
    assert population.ids["champion"] in rank
    assert population.ids["validated_low"] in rank
    assert population.ids["promising_a"] not in rank  # PROMISING isn't VALIDATED/CHAMPION
    assert (
        rank[population.ids["validated_high"]]
        < rank[population.ids["champion"]]
        < rank[population.ids["validated_low"]]
    )


async def test_select_for_revival_returns_dormant_and_quarantined_only(
    session_factory: async_sessionmaker[AsyncSession], population: PopulationFixture
) -> None:
    async with session_factory() as session:
        candidates = await select_for_revival(session, limit=1000)
    ids = {c.strategy_id for c in candidates}
    assert population.ids["dormant_old"] in ids
    assert population.ids["quarantined"] in ids
    assert population.ids["rejected"] not in ids
    assert population.ids["validated_high"] not in ids


async def test_select_for_cross_breeding_returns_two_best_scoring_same_family(
    session_factory: async_sessionmaker[AsyncSession], population: PopulationFixture
) -> None:
    async with session_factory() as session:
        pair = await select_for_cross_breeding(session, family="MOMENTUM")
    assert pair is not None
    a, b = pair
    assert a.family == b.family == "MOMENTUM"
    # Eligible pool is VALIDATED/CHAMPION/PROMISING: validated_high=0.9,
    # promising_a=0.8, champion=0.5, promising_b=0.3, validated_low=0.1 --
    # the top 2 by score.
    assert a.strategy_id == population.ids["validated_high"]
    assert b.strategy_id == population.ids["promising_a"]


async def test_select_for_cross_breeding_returns_none_for_an_unpopulated_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        pair = await select_for_cross_breeding(session, family="BOLLINGER")
    assert pair is None


async def test_select_for_exploration_respects_limit(
    session_factory: async_sessionmaker[AsyncSession], population: PopulationFixture
) -> None:
    async with session_factory() as session:
        candidates = await select_for_exploration(session, limit=3)
    assert len(candidates) <= 3


async def test_select_for_diversification_returns_only_the_requested_shape(
    session_factory: async_sessionmaker[AsyncSession], population: PopulationFixture
) -> None:
    # Runs before the BOLLINGER/VOL_BREAKOUT-inserting tests below (pytest
    # executes a module's tests in definition order), so every row in
    # `strategies` at this point is a real MOMENTUM spec from this file's
    # own `population` fixture -- a real, non-vacuous check that the
    # result is confined to one family's real parameter space.
    async with session_factory() as session:
        candidates = await select_for_diversification(session, limit=5)
    assert len(candidates) <= 5
    assert len(candidates) > 0
    assert all(c.family == "MOMENTUM" for c in candidates)


async def test_elect_champions_promotes_best_and_demotes_stale_champion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        stale_spec = _bollinger(10, 1.5)
        stale_id = await next_strategy_id("BOLLINGER")
        session.add(
            Strategy(
                id=stale_id, family="BOLLINGER", spec=stale_spec.model_dump(), status="CHAMPION"
            )
        )

        better_spec = _bollinger(20, 2.0)
        better_id = await next_strategy_id("BOLLINGER")
        session.add(
            Strategy(
                id=better_id,
                family="BOLLINGER",
                spec=better_spec.model_dump(),
                status="VALIDATED",
            )
        )
        await session.flush()

        experiment_id = await next_experiment_id(year=next(_TEST_EXPERIMENT_YEAR))
        session.add(
            Experiment(
                id=experiment_id,
                status="completed",
                strategy_id=better_id,
                config_hash=better_spec.config_hash(),
            )
        )
        await session.flush()
        session.add(
            ValidationResult(
                experiment_id=experiment_id,
                strategy_fingerprint=better_spec.config_hash(),
                verdict="PROMOTE",
                score=0.99,
            )
        )
        await session.commit()

        best_ids = await elect_champions(session)
        await session.commit()

        assert better_id in best_ids
        stale_status = (
            await session.execute(
                text("SELECT status FROM strategies WHERE id = :id"), {"id": stale_id}
            )
        ).scalar_one()
        assert stale_status == "VALIDATED"  # demoted, not rejected/retired
        better_status = (
            await session.execute(
                text("SELECT status FROM strategies WHERE id = :id"), {"id": better_id}
            )
        ).scalar_one()
        assert better_status == "CHAMPION"


async def test_population_summary_reflects_real_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = _vol_breakout(30, 15)
    async with session_factory() as session:
        for status in ("VALIDATED", "VALIDATED", "PROMISING", "REJECTED"):
            strategy_id = await next_strategy_id("VOL_BREAKOUT")
            session.add(
                Strategy(
                    id=strategy_id, family="VOL_BREAKOUT", spec=spec.model_dump(), status=status
                )
            )
        await session.commit()

        summary = await population_summary(session)

    assert summary["VOL_BREAKOUT"]["validated"] == 2
    assert summary["VOL_BREAKOUT"]["promising"] == 1
    assert summary["VOL_BREAKOUT"]["rejected"] == 1

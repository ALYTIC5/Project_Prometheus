"""PROMPT 6's own explicit acceptance bar: "run a placebo component
(changes only the seed). Must return NEUTRAL with CI straddling zero. If
a placebo shows improvement, the harness is broken."

Real end-to-end run against real Postgres: real synthetic bars inserted
into ohlcv_bars, real StrategySpec grid, real run_ablation, real
component_registry row read back -- not a mocked verdict.

Multiple INDEPENDENT synthetic symbols, not one symbol's grid repeated
across many parameter values: an earlier version of this test used one
price history with only the momentum grid (8 trials) and was genuinely
flaky -- different (fast, slow) specs on the SAME underlying price path
produce correlated, not independent, paired diffs, understating the true
variance and occasionally producing a spuriously significant HARMFUL/
VALUABLE verdict purely by chance even though the true effect is zero.
Real 95%-CI test batches DO fail ~5% of the time under a true null by
construction; the fix is more genuinely independent trials (a real
statistical concern, not just test flakiness), not a p-hacked seed.
"""
from __future__ import annotations

import os
import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prometheus.data.models import OhlcvBar as OhlcvBarModel
from prometheus.experiments.ablation import placebo_component, register_baseline, run_ablation
from prometheus.research.generate import generate_baseline_grid

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0011 applied)",
    ),
]

_N_BARS = 200
_N_SYMBOLS = 6


@pytest.fixture()
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _insert_synthetic_bars(session: AsyncSession, symbol: str, seed: int) -> None:
    # Symmetric bounds -- TRUE zero expected drift, same convention
    # tests/test_null_strategies.py's own _random_walk_bars already
    # establishes. An earlier version of this fixture used asymmetric
    # bounds (-0.02, 0.022), a real confound found by actually running
    # this test: on an asset with genuine positive drift, ANY component
    # that changes average time-in-market (more or less exposure) has a
    # real, nonzero, systematic effect on returns, independent of
    # whether the component is otherwise "fair" -- placebo_component's
    # turnover-preserving redistribution does shift average exposure
    # relative to a baseline whose own long/flat balance is skewed
    # (e.g. VOL_BREAKOUT genuinely spends most bars flat), so it
    # registered as VALUABLE or HARMFUL depending on the drift's sign,
    # not because the placebo or the harness was broken -- because the
    # test data secretly rewarded more time in the market. Zero true
    # drift removes that confound: exposure-timing changes then have no
    # expected effect on returns, regardless of exposure fraction.
    rng = random.Random(seed)
    price = 100.0
    start = datetime(2023, 1, 1, tzinfo=UTC)
    for i in range(_N_BARS):
        price *= 1 + rng.uniform(-0.02, 0.02)
        event_time = start + timedelta(days=i)
        session.add(
            OhlcvBarModel(
                symbol=symbol,
                timeframe="1d",
                event_time=event_time,
                available_at=event_time + timedelta(minutes=5),
                source="test-fixture",
                revision=1,
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0,
            )
        )
    await session.commit()


async def test_placebo_registers_as_neutral_with_ci_straddling_zero(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # Unique per test invocation -- ohlcv_bars' (symbol, timeframe,
    # event_time, revision) uniqueness means re-running this test against
    # a persistent (not freshly-recreated) database with fixed symbol
    # names collides on the second run; a random suffix keeps this test
    # safe to re-run locally without requiring a DB reset each time, same
    # precedent tests/laws/test_holdout_sacred.py's _spec() already uses.
    run_id = uuid.uuid4().hex[:8]
    component = f"test-placebo-acceptance-{run_id}"
    symbols = [f"PLACEBO{run_id}-{i}/USDT" for i in range(_N_SYMBOLS)]

    async with factory() as session:
        specs = []
        for i, symbol in enumerate(symbols):
            await _insert_synthetic_bars(session, symbol, seed=100 + i)
            specs.extend(generate_baseline_grid(symbol, "1d"))
        assert len(specs) >= 50  # a real batch across independent price paths

        end = datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=_N_BARS)
        start = end - timedelta(days=_N_BARS)

        result = await run_ablation(
            session,
            component=component,
            version="v1",
            families_affected=["MOMENTUM", "BOLLINGER", "VOL_BREAKOUT"],
            specs=specs,
            start=start,
            end=end,
            component_fn=placebo_component,
        )

        print(
            f"\nplacebo acceptance: n={result.n_experiments} metric={result.metric} "
            f"mean={result.mean_improvement} ci=({result.ci_low}, {result.ci_high}) "
            f"verdict={result.verdict}"
        )

        assert result.n_experiments >= 50
        assert result.verdict == "NEUTRAL", (
            f"placebo (changes only the seed) registered as {result.verdict}, not NEUTRAL -- "
            f"if a placebo shows improvement or harm, the harness itself is broken"
        )
        assert result.ci_low is not None and result.ci_high is not None
        assert result.ci_low <= 0.0 <= result.ci_high
        assert result.disabled is False

        # Read back the real, persisted registry row -- not just the
        # in-memory BatchResult.
        row = (
            await session.execute(
                text(
                    "SELECT verdict, ci_low, ci_high, n_experiments FROM component_registry "
                    "WHERE component = :component AND version = 'v1'"
                ),
                {"component": component},
            )
        ).mappings().first()
        assert row is not None
        assert row["verdict"] == "NEUTRAL"
        assert row["ci_low"] <= 0.0 <= row["ci_high"]


async def test_register_baseline_actually_persists(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """register_baseline() is not called from within run_ablation()'s own
    commit path -- it originally returned _recompute_registry's result
    without ever committing the session, so the write was silently lost
    the moment the caller's `async with` block closed. Caught by actually
    reading the row back in a FRESH session (not the one register_baseline
    itself used), which is exactly what a real caller across two separate
    requests would do."""
    version = "v-persist-check"
    async with factory() as session:
        result = await register_baseline(
            session, version=version, families_affected=["MOMENTUM"]
        )
        assert result.verdict == "UNPROVEN"

    async with factory() as fresh_session:
        row = (
            await fresh_session.execute(
                text(
                    "SELECT verdict FROM component_registry "
                    "WHERE component = 'deterministic_grid_baseline' AND version = :version"
                ),
                {"version": version},
            )
        ).mappings().first()
        assert row is not None, "register_baseline's write did not persist"
        assert row["verdict"] == "UNPROVEN"

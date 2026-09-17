"""Scheduled worker entrypoint. PROMPTS.md PROMPT 7's "THE WORKER": wakes
on a cron schedule (Railway), does one bounded pass, exits -- not an
always-on process. CLAUDE.md's cost discipline: two always-on services
(api, postgres) plus one scheduled worker, not a third always-on process.

Each cycle: (1) an idempotent ingestion catch-up for a short recent
window, (2) enqueues the deterministic grid for every symbol in the real
universe (idempotent by config_hash+days -- a symbol's grid runs ONCE,
not every cycle, see experiments.runner.enqueue_grid), (3) drains
whatever's pending, (4) re-validates every symbol's grid against real
PBO/DSR/decay/regime evidence (PROMPT 5's Oracle) -- unlike (2), this
step is NOT idempotent-by-design: it deliberately re-scores existing
experiments every cycle, since more accumulated data and a larger
cumulative trial count (validation.multiple_testing.trials_to_date) can
change a verdict even when nothing about the strategy itself changed,
(5) PROMPT 7: one bounded evolution step -- mutates/crosses over a small,
fixed number of real, currently-scored strategies and enqueues the
children through the SAME queue.enqueue() every grid job goes through,
so they are claimed and run by next cycle's drain_queue via the
identical "run_backtest" path, not a second execution path.

Three separate Railway Cron services (one per cadence PROMPTS.md
originally suggests) would violate CLAUDE.md's literal "one scheduled
worker, not seven" -- this single 30-minute cycle already does all of
the above.
"""
from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import get_session
from prometheus.core.seeds import derive_seed, rng_for
from prometheus.data.ingestion import backfill, load_universe_symbols
from prometheus.experiments.queue import enqueue, get_queue_settings, reap_stale_claims
from prometheus.experiments.runner import (
    drain_queue,
    enqueue_grid,
    latest_experiment_id_for_spec,
    validate_grid,
)
from prometheus.research.crossover import crossover
from prometheus.research.mutations import parameter_tune, swap_family
from prometheus.research.population import (
    select_for_cross_breeding,
    select_for_exploitation,
    select_for_exploration,
)
from prometheus.research.prioritisation import ParentContext, expected_information_value
from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.spec import FAMILIES, StrategySpec

# Same window as the grid's own lookback, not a short "catch-up" one --
# ingestion.ingest_symbol makes exactly ONE fetch_ohlcv(..., limit=1000)
# call per symbol/timeframe regardless of how far back `since` points, so
# a wider window costs nothing extra (same one API call either way) and
# a narrow one would leave a fresh database without enough bars for the
# grid's slow_window=100 spec (needs >100 bars) to ever run successfully.
# ohlcv_bars' unique constraint already makes re-ingesting known bars a
# no-op, so this is safe to repeat every cycle regardless of DB state.
_INGEST_CATCHUP_DAYS = 800
_GRID_LOOKBACK_DAYS = 800
_TIMEFRAME = "1d"
_FAMILY = "MOMENTUM"
_RUN_BACKTEST_KIND = "run_backtest"

# A bounded compute budget for this cycle's evolution step -- the same
# kind of operational, engineering-cost choice as _GRID_LOOKBACK_DAYS
# above (how much work one 30-minute cycle should take on), not a
# statistical threshold. One exploitation pick (refine what's already
# scoring well) plus one exploration pick (keep covering the space) per
# cycle, matching population.py's own two real selection modes for
# single-parent mutation.
_EVOLUTION_EXPLOITATION_PARENTS = 1
_EVOLUTION_EXPLORATION_PARENTS = 1


async def _enqueue_child(
    session: AsyncSession,
    *,
    child: StrategySpec,
    parent_experiment_id: str | None,
    hypothesis: str,
    change_set: dict[str, object],
    expected_information_value_: float,
) -> str:
    idempotency_key = hashlib.sha256(
        f"{_RUN_BACKTEST_KIND}|{child.config_hash()}|{_GRID_LOOKBACK_DAYS}".encode()
    ).hexdigest()
    return await enqueue(
        session,
        kind=_RUN_BACKTEST_KIND,
        payload={
            "spec": child.model_dump(),
            "days": _GRID_LOOKBACK_DAYS,
            "parent_experiment_id": parent_experiment_id,
            "hypothesis": hypothesis,
            "change_set": change_set,
        },
        idempotency_key=idempotency_key,
        priority=0,
        expected_information_value=expected_information_value_,
        estimated_cost=0.0,
        max_attempts=3,
        agent_role="engineer",
        current_stage="forge",
        next_stage="arena",
    )


async def _run_evolution_step(session: AsyncSession) -> list[str]:
    """One bounded PROMPT 7 evolution pass: a small, fixed number of real
    parents (exploitation + exploration, population.py's own selection
    functions) each produce at most one mutation child
    (parameter_tune, falling back to swap_family when no valid tune is
    found), and each real family with >=2 scored candidates produces at
    most one crossover child. Every child is enqueued through the
    SAME queue.enqueue() a grid job uses -- claimed and run by a future
    drain_queue call, no second execution path. Returns the new job ids
    (not experiment ids -- these haven't run yet)."""
    templates = seed_specs_by_family()
    job_ids: list[str] = []

    exploitation = await select_for_exploitation(session, limit=_EVOLUTION_EXPLOITATION_PARENTS)
    exploration = await select_for_exploration(session, limit=_EVOLUTION_EXPLORATION_PARENTS)
    for candidate, mode in [(c, "exploitation") for c in exploitation] + [
        (c, "exploration") for c in exploration
    ]:
        rng = rng_for(derive_seed("worker_evolution_mutation", candidate.spec.config_hash()))
        mutation = parameter_tune(candidate.spec, rng) or swap_family(
            candidate.spec, rng, seed_specs_by_family=templates
        )
        if mutation is None:
            continue
        parent_experiment_id = await latest_experiment_id_for_spec(
            session, candidate.spec.config_hash()
        )
        eiv = expected_information_value(
            mutation.child, ParentContext(parent_status=candidate.status, mode=mode)
        )
        job_ids.append(
            await _enqueue_child(
                session,
                child=mutation.child,
                parent_experiment_id=parent_experiment_id,
                hypothesis=mutation.hypothesis,
                change_set=mutation.change_set,
                expected_information_value_=eiv,
            )
        )

    for family in FAMILIES:
        pair = await select_for_cross_breeding(session, family=family)
        if pair is None:
            continue
        candidate_a, candidate_b = pair
        rng = rng_for(derive_seed("worker_evolution_crossover", family))
        result = crossover(
            candidate_a.spec, candidate_a.score, candidate_b.spec, candidate_b.score, rng
        )
        if result is None or result.child.parent_id is None:
            continue
        fitter_status = (
            candidate_a.status
            if candidate_a.spec.config_hash() == result.child.parent_id
            else candidate_b.status
        )
        parent_experiment_id = await latest_experiment_id_for_spec(session, result.child.parent_id)
        eiv = expected_information_value(
            result.child, ParentContext(parent_status=fitter_status, mode="cross_breeding")
        )
        job_ids.append(
            await _enqueue_child(
                session,
                child=result.child,
                parent_experiment_id=parent_experiment_id,
                hypothesis=result.hypothesis,
                change_set=result.change_set,
                expected_information_value_=eiv,
            )
        )

    return job_ids


async def run_once() -> list[str]:
    # A prior cycle that crashed mid-job (or was killed by Railway between
    # heartbeats) leaves its claim stale forever unless something reclaims
    # it -- nothing else calls reap_stale_claims(), so this scheduled
    # worker is the only thing that ever will. Runs before draining so a
    # reclaimed job is immediately eligible this cycle, not next.
    settings = get_queue_settings()
    async with get_session() as session:
        reaped = await reap_stale_claims(
            session, stale_after_seconds=settings.JOB_HEARTBEAT_TIMEOUT_SECONDS
        )
        await session.commit()
    if reaped:
        print(f"worker: reclaimed {len(reaped)} stale claim(s): {reaped}")

    await backfill(_INGEST_CATCHUP_DAYS)

    symbols = load_universe_symbols()
    for symbol in symbols:
        await enqueue_grid(
            symbol,
            _TIMEFRAME,
            _FAMILY,
            _GRID_LOOKBACK_DAYS,
            priority=0,
            expected_information_value=0.0,
            estimated_cost=0.0,
            max_attempts=3,
        )

    ran = await drain_queue()

    # The Oracle (PROMPTS.md PROMPT 5): re-scores every symbol's grid
    # against real PBO/DSR/decay/regime evidence and writes
    # validation_results -- the table that flips the Oracle from
    # SCAFFOLDING to ACTIVE. Runs after drain_queue so a symbol's grid
    # introduced THIS cycle already has real `experiments` rows to attach
    # a verdict to, not just on the cycle after.
    validated: list[str] = []
    async with get_session() as session:
        for symbol in symbols:
            validated.extend(
                await validate_grid(session, symbol, _TIMEFRAME, _FAMILY, _GRID_LOOKBACK_DAYS)
            )

    # PROMPT 7: one bounded evolution step, after validate_grid so this
    # cycle's mutation/crossover parents are selected using freshly
    # re-scored statuses, not last cycle's. Children are enqueued for a
    # FUTURE drain_queue call, not drained this cycle -- keeps this
    # cycle's own runtime bounded, matching _GRID_LOOKBACK_DAYS's own
    # "one symbol's grid runs once" bounding rather than growing this
    # cycle's work by however many children get produced.
    async with get_session() as session:
        evolved_job_ids = await _run_evolution_step(session)
        await session.commit()
    if evolved_job_ids:
        print(f"worker: enqueued {len(evolved_job_ids)} evolved candidate(s): {evolved_job_ids}")

    return ran + validated


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained/validated {len(ran)} experiment(s): {ran}")


if __name__ == "__main__":
    main()

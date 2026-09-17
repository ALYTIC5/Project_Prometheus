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

Now three concerns run at three different rates from this ONE entrypoint,
gated by worker_cadence (is_due/mark_run below): ingest hourly, research
(today's grid/validate/evolve pipeline, unchanged logic) every 30
minutes, paper trading every tick. The Railway cron interval itself
tightens from */30 to */15 (the finest of the three rates) so the paper
concern's tick actually happens on schedule -- still one scheduled
worker, not a second service.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import polars as pl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import get_session
from prometheus.core.seeds import derive_seed, rng_for
from prometheus.data.ingestion import backfill, load_universe_symbols
from prometheus.data.loaders import load_point_in_time
from prometheus.experiments.queue import enqueue, get_queue_settings, reap_stale_claims
from prometheus.experiments.runner import (
    drain_queue,
    enqueue_grid,
    latest_experiment_id_for_spec,
    validate_grid,
)
from prometheus.paper.broker import PaperBroker
from prometheus.paper.divergence import check_divergence
from prometheus.paper.execution import decide_and_submit, poll_fills
from prometheus.paper.reconciliation import (
    check_worse_than_holding,
    compute_paper_equity_curve,
    reconcile_order,
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

_INGEST_INTERVAL_SECONDS = 3600.0  # hourly
_RESEARCH_INTERVAL_SECONDS = 1800.0  # 30 min
_PAPER_INTERVAL_SECONDS = 900.0  # 15 min -- also the new cron tick itself

_SELECT_CADENCE = text("SELECT last_run_at FROM worker_cadence WHERE concern = :concern")
_UPSERT_CADENCE = text(
    """
    INSERT INTO worker_cadence (concern, last_run_at) VALUES (:concern, now())
    ON CONFLICT (concern) DO UPDATE SET last_run_at = now()
    """
)


async def is_due(session: AsyncSession, *, concern: str, interval_seconds: float) -> bool:
    """True if `concern` has never run, or last ran more than
    interval_seconds ago. Each concern gates itself independently so one
    tightened */15 cron can serve three different cadences (PROMPTS.md's
    own schedule: ingest hourly / research 30min / paper 15min) without a
    second scheduled service."""
    row = (await session.execute(_SELECT_CADENCE, {"concern": concern})).first()
    if row is None:
        return True
    elapsed = (datetime.now(UTC) - row.last_run_at).total_seconds()
    return bool(elapsed >= interval_seconds)


async def mark_run(session: AsyncSession, *, concern: str) -> None:
    """Called only after a concern completes successfully -- a crashed
    tick leaves last_run_at unchanged, so that concern is re-attempted
    next wake rather than silently skipped."""
    await session.execute(_UPSERT_CADENCE, {"concern": concern})
    await session.commit()


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


async def _run_ingest() -> None:
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


async def _run_research() -> list[str]:
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


async def _run_paper() -> None:
    """Every champion, every tick: poll fills, reconcile, check
    divergence. Trading decisions (decide_and_submit) only actually
    submit when a new 1d bar makes the target position differ from the
    current one -- see paper/execution.py's own idempotency, not a
    separate "is a new bar due" check here."""
    broker = PaperBroker()
    as_of_cutoff = datetime.now(UTC)

    async with get_session() as session:
        champions = (
            await session.execute(
                text("SELECT id, family, spec FROM strategies WHERE status = 'CHAMPION'")
            )
        ).fetchall()

    for row in champions:
        spec = StrategySpec.model_validate(row.spec)
        async with get_session() as session:
            pit, _data_version_hash = await load_point_in_time(
                session,
                [spec.symbol],
                spec.timeframe,
                as_of_cutoff - timedelta(days=_GRID_LOOKBACK_DAYS),
                as_of_cutoff,
            )
            bars = pit.as_of(as_of_cutoff).filter(pl.col("symbol") == spec.symbol).sort(
                "available_at"
            )
            if bars.height == 0:
                continue

            await decide_and_submit(session, broker, strategy_id=row.id, spec=spec, bars=bars)
            filled_ids = await poll_fills(session, broker, symbol=spec.symbol)

            deltas = []
            for order_id in filled_ids:
                delta = await reconcile_order(session, order_id=order_id)
                if delta is not None:
                    deltas.append(delta)
            if deltas:
                await check_divergence(session, strategy_id=row.id, reconciliation_deltas=deltas)

            current_price = float(bars.tail(1)["close"][0])
            paper_curve = await compute_paper_equity_curve(
                session, strategy_id=row.id, current_price=current_price
            )
            if paper_curve:
                await check_worse_than_holding(
                    session,
                    strategy_id=row.id,
                    symbol=spec.symbol,
                    paper_equity_curve=paper_curve,
                    as_of_cutoff=as_of_cutoff,
                )


async def run_once() -> list[str]:
    ran: list[str] = []
    async with get_session() as session:
        ingest_due = await is_due(
            session, concern="ingest", interval_seconds=_INGEST_INTERVAL_SECONDS
        )
        research_due = await is_due(
            session, concern="research", interval_seconds=_RESEARCH_INTERVAL_SECONDS
        )
        paper_due = await is_due(
            session, concern="paper", interval_seconds=_PAPER_INTERVAL_SECONDS
        )

    if ingest_due:
        await _run_ingest()
        async with get_session() as session:
            await mark_run(session, concern="ingest")

    if research_due:
        ran = await _run_research()
        async with get_session() as session:
            await mark_run(session, concern="research")

    if paper_due:
        await _run_paper()
        async with get_session() as session:
            await mark_run(session, concern="paper")

    return ran


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained/validated {len(ran)} experiment(s): {ran}")


if __name__ == "__main__":
    main()

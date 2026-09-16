"""One StrategySpec -> one Experiment -> one Result -> one Decision.

INSERT-only against experiments/results/decisions (migration 0003's
trigger forbids anything else) -- `experiments.status` is set once, at
creation, to its final value; it is never UPDATEd afterwards.

The decision rule is Law 8's own text, not an invented threshold: ACCEPT
only if the strategy's net return beats the benchmark's net return over
the identical window with the identical cost model. Zero margin, no
tuning -- "if a strategy cannot beat this after costs, it is not an edge."
There is no PBO/DSR validation here (the Oracle, Prompt 5); a strategy
that clears this bar is PROMISING, not VALIDATED -- exactly the distinction
frontend/src/mapping/stateToVisual.ts's StrategyState already encodes.

migration 0006's reproducibility columns (data_version_hash, code_sha,
config_hash, seed, compute_cost) are populated on every Experiment here,
not left for a later backfill -- Law 6 means they never could be
backfilled. compute_cost is wall-clock seconds spent inside run_backtest,
a real measured quantity; there is no dollar-cost meter wired up yet
(that is infra/LLM cost tracking, out of this prompt's scope), so this
column is honest about being a time proxy, not a fabricated currency
figure.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.benchmark import compute_benchmark_curve, record_benchmark_curve
from prometheus.backtest.engine import run_backtest
from prometheus.core.db import Decision, Experiment, Result, Strategy, get_session
from prometheus.core.ids import next_experiment_id, next_strategy_id
from prometheus.core.provenance import code_sha
from prometheus.core.seeds import derive_seed
from prometheus.data.loaders import load_point_in_time
from prometheus.experiments.failure import classify_exception, classify_result
from prometheus.experiments.queue import Job, claim, enqueue, fail, succeed
from prometheus.experiments.violations import record_config_snapshot
from prometheus.research.generate import generate_grid
from prometheus.strategy.spec import StrategySpec

_UPDATE_STRATEGY_STATUS = text("UPDATE strategies SET status = :status WHERE id = :id")
_UNIVERSE_CONFIG_PATH = "config/universe.yaml"


def _build_experiment(
    *,
    experiment_id: str,
    strategy_id: str,
    spec: StrategySpec,
    seed: int,
    resolved_code_sha: str,
    data_version_hash: str,
    compute_cost: float,
    parent_experiment_id: str | None,
    hypothesis: str | None,
    change_set: dict[str, Any] | None,
) -> Experiment:
    return Experiment(
        id=experiment_id,
        status="completed",
        payload={"strategy_id": strategy_id, "config_hash": spec.config_hash(), "seed": seed},
        parent_experiment_id=parent_experiment_id,
        strategy_id=strategy_id,
        data_version_hash=data_version_hash,
        code_sha=resolved_code_sha,
        config_hash=spec.config_hash(),
        seed=seed,
        compute_cost=compute_cost,
        hypothesis=hypothesis,
        change_set=change_set,
    )


async def run_one(
    session: AsyncSession,
    spec: StrategySpec,
    start: datetime,
    end: datetime,
    *,
    parent_experiment_id: str | None = None,
    hypothesis: str | None = None,
    change_set: dict[str, Any] | None = None,
) -> str:
    """Runs one strategy through the full pipeline against real data in
    [start, end]. Returns the experiment id. `parent_experiment_id`/
    `hypothesis`/`change_set` are optional -- omitted, an experiment is a
    lineage root, same as every experiment written before migration 0006
    existed.

    Raises (never fabricates a result) if there isn't enough real data;
    the failure is still recorded, classified INSUFFICIENT_DATA, before
    re-raising -- see the except block below."""
    # Substrate for violations.detect_universe_changed_after_results --
    # a no-op row if the file's content hash was already recorded.
    await record_config_snapshot(session, _UNIVERSE_CONFIG_PATH)

    pit, data_version_hash = await load_point_in_time(
        session, [spec.symbol], spec.timeframe, start, end
    )
    seed = derive_seed(spec.symbol, spec.timeframe, spec.config_hash())
    resolved_code_sha = code_sha()

    strategy_id = await next_strategy_id(spec.family)
    session.add(
        Strategy(id=strategy_id, family=spec.family, spec=spec.model_dump(), status="pending")
    )
    await session.flush()

    experiment_id = await next_experiment_id()
    started = time.perf_counter()
    try:
        strategy_result = run_backtest(pit, spec, end)
    except ValueError as exc:
        session.add(
            _build_experiment(
                experiment_id=experiment_id,
                strategy_id=strategy_id,
                spec=spec,
                seed=seed,
                resolved_code_sha=resolved_code_sha,
                data_version_hash=data_version_hash,
                compute_cost=time.perf_counter() - started,
                parent_experiment_id=parent_experiment_id,
                hypothesis=hypothesis,
                change_set=change_set,
            )
        )
        session.add(
            Decision(
                experiment_id=experiment_id,
                decision={
                    "decision": "REJECT",
                    "reason": "insufficient_data",
                    "reason_codes": [classify_exception(exc).value],
                },
            )
        )
        await session.execute(
            _UPDATE_STRATEGY_STATUS, {"status": "REJECTED", "id": strategy_id}
        )
        await session.commit()
        raise
    compute_cost = time.perf_counter() - started

    benchmark_result = compute_benchmark_curve(pit, [spec.symbol], end)
    await record_benchmark_curve(session, benchmark_result.equity_curve)
    benchmark_curve = benchmark_result.equity_curve
    benchmark_return_pct = (
        (benchmark_curve[-1][1] - benchmark_curve[0][1]) / benchmark_curve[0][1] * 100
        if len(benchmark_curve) >= 2
        else 0.0
    )
    beats_benchmark = strategy_result.total_return_pct > benchmark_return_pct
    reason_codes = classify_result(strategy_result, benchmark_return_pct=benchmark_return_pct)

    session.add(
        _build_experiment(
            experiment_id=experiment_id,
            strategy_id=strategy_id,
            spec=spec,
            seed=seed,
            resolved_code_sha=resolved_code_sha,
            data_version_hash=data_version_hash,
            compute_cost=compute_cost,
            parent_experiment_id=parent_experiment_id,
            hypothesis=hypothesis,
            change_set=change_set,
        )
    )
    await session.flush()

    session.add(
        Result(
            experiment_id=experiment_id,
            payload={
                "total_return_pct": strategy_result.total_return_pct,
                "max_drawdown_pct": strategy_result.max_drawdown_pct,
                "turnover": strategy_result.turnover,
                "gross_return_pct": strategy_result.gross_return_pct,
                "total_costs": strategy_result.total_costs,
                "benchmark_return_pct": benchmark_return_pct,
            },
        )
    )
    session.add(
        Decision(
            experiment_id=experiment_id,
            decision={
                "decision": "ACCEPT" if beats_benchmark else "REJECT",
                "reason": (
                    "beats_benchmark_net_of_costs"
                    if beats_benchmark
                    else "does_not_beat_benchmark_net_of_costs"
                ),
                "reason_codes": [mode.value for mode in reason_codes],
            },
        )
    )

    await session.execute(
        _UPDATE_STRATEGY_STATUS,
        {"status": "PROMISING" if beats_benchmark else "REJECTED", "id": strategy_id},
    )
    await session.commit()
    return experiment_id


_RUN_BACKTEST_KIND = "run_backtest"


async def enqueue_grid(
    symbol: str,
    timeframe: str,
    family: str,
    days: int,
    *,
    priority: int,
    expected_information_value: float,
    estimated_cost: float,
    max_attempts: int,
) -> list[str]:
    """Enqueues one job per StrategySpec in the deterministic grid.
    idempotency_key = sha256(kind, spec.config_hash(), days) -- re-running
    enqueue_grid for an unchanged grid re-enqueues nothing (queue.enqueue's
    ON CONFLICT DO NOTHING), rather than duplicating work already queued
    or already run."""
    specs = generate_grid(symbol, timeframe, family)
    job_ids = []
    async with get_session() as session:
        for spec in specs:
            idempotency_key = hashlib.sha256(
                f"{_RUN_BACKTEST_KIND}|{spec.config_hash()}|{days}".encode()
            ).hexdigest()
            job_ids.append(
                await enqueue(
                    session,
                    kind=_RUN_BACKTEST_KIND,
                    payload={"spec": spec.model_dump(), "days": days},
                    idempotency_key=idempotency_key,
                    priority=priority,
                    expected_information_value=expected_information_value,
                    estimated_cost=estimated_cost,
                    max_attempts=max_attempts,
                    agent_role="engineer",
                    current_stage="forge",
                    next_stage="arena",
                )
            )
        await session.commit()
    return job_ids


async def _run_job(job: Job) -> str:
    """Executes one claimed job's payload against real data -- the only
    kind this worker understands is run_backtest. A separate session from
    the one claim() used: see queue.claim's docstring on why the claiming
    transaction must already be committed before work starts."""
    if job.kind != _RUN_BACKTEST_KIND:
        raise ValueError(f"unknown job kind: {job.kind!r}")
    spec = StrategySpec.model_validate(job.payload["spec"])
    days = job.payload["days"]
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    async with get_session() as session:
        return await run_one(session, spec, start, end)


async def drain_queue(*, worker_id: str | None = None, max_jobs: int | None = None) -> list[str]:
    """Claims and runs jobs until the queue has none runnable or max_jobs
    is reached (None = drain fully -- the scheduled-worker cron use case,
    PROMPTS.md PROMPT 7 adds the schedule that calls this). Each claim is
    committed in its own transaction before _run_job does any work, per
    queue.claim's documented rule."""
    resolved_worker_id = worker_id or f"runner-{uuid.uuid4().hex[:12]}"
    experiment_ids: list[str] = []
    ran = 0
    while max_jobs is None or ran < max_jobs:
        async with get_session() as session:
            job = await claim(session, worker_id=resolved_worker_id)
            await session.commit()
        if job is None:
            break
        ran += 1
        try:
            experiment_id = await _run_job(job)
        except Exception as exc:
            async with get_session() as session:
                await fail(session, job_id=job.id, worker_id=resolved_worker_id, error=str(exc))
                await session.commit()
            continue
        async with get_session() as session:
            await succeed(
                session,
                job_id=job.id,
                worker_id=resolved_worker_id,
                experiment_id=experiment_id,
            )
            await session.commit()
        experiment_ids.append(experiment_id)
    return experiment_ids


async def _run_grid(
    symbol: str,
    timeframe: str,
    family: str,
    days: int,
    *,
    priority: int,
    expected_information_value: float,
    estimated_cost: float,
    max_attempts: int,
) -> list[str]:
    """Enqueue-then-drain: the same end-to-end effect the old direct-call
    version had, now going through the queue so an interrupted run leaves
    real, resumable jobs instead of silently losing whatever hadn't run
    yet."""
    await enqueue_grid(
        symbol,
        timeframe,
        family,
        days,
        priority=priority,
        expected_information_value=expected_information_value,
        estimated_cost=estimated_cost,
        max_attempts=max_attempts,
    )
    return await drain_queue()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic strategy grid and backtest each against real data."
    )
    parser.add_argument(
        "--generate", action="store_true", help="run the full generate+backtest pipeline"
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--family", default="MOMENTUM")
    parser.add_argument("--days", type=int, default=800)
    # Queue bookkeeping for this CLI's own jobs, not validation thresholds --
    # with one job kind in the system there is nothing yet to prioritise
    # these against. max_attempts=3 matches nothing external; it is simply
    # this command's own choice of how many times to retry itself.
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--expected-information-value", type=float, default=0.0)
    parser.add_argument("--estimated-cost", type=float, default=0.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.generate:
        ids = asyncio.run(
            _run_grid(
                args.symbol,
                args.timeframe,
                args.family,
                args.days,
                priority=args.priority,
                expected_information_value=args.expected_information_value,
                estimated_cost=args.estimated_cost,
                max_attempts=args.max_attempts,
            )
        )
        print(f"ran {len(ids)} experiments: {ids}")
    else:
        raise SystemExit("nothing to do — pass --generate")


if __name__ == "__main__":
    main()

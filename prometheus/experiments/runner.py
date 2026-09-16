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
import time
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

    benchmark_curve = compute_benchmark_curve(pit, spec.symbol, end)
    await record_benchmark_curve(session, benchmark_curve)
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


async def _run_grid(symbol: str, timeframe: str, family: str, days: int) -> list[str]:
    specs = generate_grid(symbol, timeframe, family)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    experiment_ids = []
    async with get_session() as session:
        for spec in specs:
            experiment_ids.append(await run_one(session, spec, start, end))
    return experiment_ids


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.generate:
        ids = asyncio.run(_run_grid(args.symbol, args.timeframe, args.family, args.days))
        print(f"ran {len(ids)} experiments: {ids}")
    else:
        raise SystemExit("nothing to do — pass --generate")


if __name__ == "__main__":
    main()

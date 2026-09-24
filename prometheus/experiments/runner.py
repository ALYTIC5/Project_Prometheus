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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
from cpz_quant.certification.analytics import compute_risk_analytics
from cpz_quant.certification.overfitting import probability_of_backtest_overfitting
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.benchmark import compute_benchmark_curve, record_benchmark_curve
from prometheus.backtest.costs import DEFAULT_COST_CONFIG_PATH, load_cost_config, make_cost_model
from prometheus.backtest.engine import run_backtest
from prometheus.backtest.portfolio_engine import run_portfolio_backtest
from prometheus.core.db import Decision, Experiment, Result, Strategy, ValidationResult, get_session
from prometheus.core.health import record_failure
from prometheus.core.ids import next_experiment_id, next_strategy_id
from prometheus.core.provenance import code_sha
from prometheus.core.seeds import derive_seed
from prometheus.data.loaders import load_point_in_time
from prometheus.data.universe import membership_windows
from prometheus.experiments.failure import classify_exception, classify_result
from prometheus.experiments.queue import Job, claim, enqueue, fail, succeed
from prometheus.experiments.violations import record_config_snapshot
from prometheus.research.clustering import cluster_by_correlation
from prometheus.research.generate import generate_baseline_grid, generate_grid
from prometheus.research.population import elect_champions, verdict_to_status
from prometheus.strategy.rotation_spec import RotationSpec
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.decay import DecayProfile, compute_decay
from prometheus.validation.decision import Evidence, decide
from prometheus.validation.metrics import ValidationMetrics, compute_metrics
from prometheus.validation.metrics import hit_rate as compute_hit_rate
from prometheus.validation.multiple_testing import deflated_sharpe_ratio, trials_to_date
from prometheus.validation.regime import classify_current_regime, regime_breakdown
from prometheus.validation.scoring import ScoreInputs

_UPDATE_STRATEGY_STATUS = text("UPDATE strategies SET status = :status WHERE id = :id")
_UNIVERSE_CONFIG_PATH = "config/universe.yaml"


def _build_experiment(
    *,
    experiment_id: str,
    strategy_id: str,
    spec: StrategySpec | RotationSpec,
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
    spec: StrategySpec | RotationSpec,
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
    # a no-op row if the file's content hash was already recorded. Same
    # treatment for costs.yaml -- substrate for a future
    # COST_CONFIG_LOOSENED detector (docs/DEFERRED.md), not implemented
    # here.
    await record_config_snapshot(session, _UNIVERSE_CONFIG_PATH)
    await record_config_snapshot(session, DEFAULT_COST_CONFIG_PATH)
    cost_config, cost_config_hash = load_cost_config()
    cost_model = make_cost_model(cost_config)

    universe_symbols = [spec.symbol] if isinstance(spec, StrategySpec) else list(spec.universe)
    pit, data_version_hash = await load_point_in_time(
        session, universe_symbols, spec.timeframe, start, end
    )
    seed = derive_seed(*sorted(universe_symbols), spec.timeframe, spec.config_hash())
    resolved_code_sha = code_sha()

    strategy_id = await next_strategy_id(spec.family)
    session.add(
        Strategy(id=strategy_id, family=spec.family, spec=spec.model_dump(), status="pending")
    )
    await session.flush()

    experiment_id = await next_experiment_id()
    started = time.perf_counter()
    # Computed before run_backtest so it can be passed in and reused --
    # run_backtest computes its own benchmark_result internally by default
    # (Law 8: every BacktestResult carries a real vs_benchmark, not just
    # usually-true-because-the-caller-remembered-to), but runner.py also
    # needs the raw curve to record for the world view, so passing it in
    # avoids computing it twice.
    benchmark_result = compute_benchmark_curve(pit, universe_symbols, end, cost_model=cost_model)
    try:
        if isinstance(spec, RotationSpec):
            membership = await membership_windows(session, "etf", list(spec.universe))
            strategy_result = run_portfolio_backtest(
                pit, spec, membership, end, cost_model=cost_model, benchmark_result=benchmark_result
            )
        else:
            strategy_result = run_backtest(
                pit, spec, end, cost_model=cost_model, benchmark_result=benchmark_result
            )
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
        # Flush before adding Decision -- matches the success path below.
        # Without this, the Experiment row isn't guaranteed visible to the
        # Decision insert's FK check within the same flush; caught for
        # real running this worker against Postgres (ForeignKeyViolation
        # on decisions.experiment_id), not by any offline test, since
        # nothing before this exercised the insufficient-data path against
        # a real database.
        await session.flush()
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
                "cost_config_hash": cost_config_hash,
                "vs_benchmark": {
                    "excess_return": strategy_result.vs_benchmark.excess_return,
                    "periods_underperforming_pct": (
                        strategy_result.vs_benchmark.periods_underperforming_pct
                    ),
                    "max_relative_drawdown": strategy_result.vs_benchmark.max_relative_drawdown,
                    "excess_sharpe": strategy_result.vs_benchmark.excess_sharpe,
                },
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


_SELECT_LATEST_EXPERIMENT_FOR_SPEC = text(
    "SELECT id, strategy_id FROM experiments WHERE config_hash = :config_hash "
    "ORDER BY created_at DESC LIMIT 1"
)


async def latest_experiment_id_for_spec(session: AsyncSession, config_hash: str) -> str | None:
    """The most recent experiment for a given spec's own config_hash --
    same lookup `validate_grid` already does per spec, exported for
    worker.py's evolution step, which needs a parent SPEC's real
    experiment id to populate a child job's `parent_experiment_id`
    payload key (see `_run_job`)."""
    row = (
        await session.execute(_SELECT_LATEST_EXPERIMENT_FOR_SPEC, {"config_hash": config_hash})
    ).first()
    return row.id if row is not None else None

_SELECT_LATEST_VERDICT_FOR_FINGERPRINT = text(
    "SELECT verdict FROM validation_results WHERE strategy_fingerprint = :fp "
    "ORDER BY created_at DESC LIMIT 1"
)


def _pbo_n_splits(t_observations: int) -> int | None:
    """Largest even split count <= cpz-quant's own default (16) such that
    T >= n_splits*2 -- probability_of_backtest_overfitting's own
    requirement, not an invented number. None when even 2 splits (the
    smallest CSCV can do anything with) don't fit T."""
    n_splits = min(16, t_observations // 2)
    if n_splits % 2 != 0:
        n_splits -= 1
    return n_splits if n_splits >= 2 else None


async def validate_specs(
    session: AsyncSession, symbol: str, timeframe: str, specs: list[StrategySpec], days: int
) -> list[str]:
    """Re-evaluates the deterministic grid's already-run specs (each has
    an `experiments` row from run_one, found by config_hash -- this
    function creates no new Experiment/Strategy, it re-scores existing
    ones as more data accumulates, matching Law 7's "evidence
    requirements tighten as count grows") against real PBO, Deflated
    Sharpe, decay, and regime evidence, and writes one validation_results
    row per spec -- the table migration 0010's manifest names as what
    flips the Oracle from SCAFFOLDING to ACTIVE.

    Equity curves are re-derived fresh via run_backtest (pure and
    deterministic -- same data/config/seed always reproduces the same
    curve) rather than read back from Result.payload, which only ever
    stored summary stats, never the per-bar curve PBO's CSCV needs.
    Specs are aligned on the most recent `min(len(curve))` bars across
    the batch -- grid entries with a larger slow_window need more warm-up
    bars and so produce a shorter curve; the common recent tail is what
    every spec in the batch can be compared over.

    Returns the list of experiment_ids that received a fresh verdict.
    """
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    cost_config, _cost_config_hash = load_cost_config()
    cost_model = make_cost_model(cost_config)
    pit, _data_version_hash = await load_point_in_time(session, [symbol], timeframe, start, end)
    benchmark_result = compute_benchmark_curve(pit, [symbol], end, cost_model=cost_model)
    bars = pit.as_of(end).filter(pl.col("symbol") == symbol).sort("available_at")

    per_spec: list[tuple[StrategySpec, Any]] = []
    for spec in specs:
        try:
            result = run_backtest(
                pit, spec, end, cost_model=cost_model, benchmark_result=benchmark_result
            )
        except ValueError:
            continue  # not enough bars yet for this spec's slow_window
        per_spec.append((spec, result))

    if not per_spec:
        return []

    # PBO is a property of the SELECTION among trials, not of any one
    # trial -- one value applies to every spec in this batch.
    min_len = min(len(result.equity_curve) for _, result in per_spec)
    n_splits = _pbo_n_splits(min_len - 1)  # -1: differencing loses one point
    pbo_value: float | None = None
    if n_splits is not None and len(per_spec) >= 2:
        returns_columns = []
        for _, result in per_spec:
            equities = [equity for _, equity in result.equity_curve[-min_len:]]
            returns_columns.append(
                [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
            )
        returns_matrix = np.array(returns_columns).T  # T x N
        pbo_result = probability_of_backtest_overfitting(returns_matrix, n_splits=n_splits)
        pbo_value = pbo_result.pbo

    # Correlation clustering (the "100 strategies" prompt's own explicit
    # reasoning): a cluster counts as ONE discovery, never several --
    # computed on this same batch's own real equity curves, surfaced per
    # spec in validation_results.metrics for the dashboard. Deliberately
    # informational only here -- NOT yet gating elect_champions()'s
    # promotion eligibility, see docs/DEFERRED.md's own entry for why
    # that specific behavior change is scoped as separate follow-up.
    clusters = cluster_by_correlation(
        [(spec, result.equity_curve) for spec, result in per_spec]
    )
    cluster_info_by_hash: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        # The representative's own config_hash is the cluster's stable,
        # globally-unique key -- NOT a sequential batch-local index. A
        # small int like 0/1/2 would collide across different symbols'
        # (or different cycles') independent validate_specs batches,
        # silently merging unrelated clusters that happen to land at the
        # same small index. config_hash() is already this codebase's own
        # convention for "the stable identity of this exact spec",
        # reused here rather than inventing a second identifier scheme.
        cluster_key = cluster.representative.config_hash()
        for member in cluster.members:
            cluster_info_by_hash[member.config_hash()] = {
                "cluster_key": cluster_key,
                "cluster_size": len(cluster.members),
                "is_representative": member.config_hash() == cluster_key,
                "mean_pairwise_correlation": cluster.mean_pairwise_correlation,
            }

    # Filtered together, not two parallel lists kept in sync by
    # convention: a metrics failure for one spec (e.g. a fold split that
    # isn't viable for its particular expected_horizon/bar-count
    # combination) must drop that spec, not silently misalign `per_spec`
    # against `per_spec_metrics` or crash the whole batch -- both are
    # real failure modes caught by actually running this against real
    # data, not by any offline test.
    trial_sharpes: list[float] = []
    validated_specs: list[tuple[StrategySpec, Any, Any]] = []
    for spec, result in per_spec:
        try:
            validation_metrics = compute_metrics(result.equity_curve, result.turnover, bars, spec)
        except Exception as exc:
            record_failure(
                "research",
                exc,
                context=f"validate_grid family={spec.family} hash={spec.config_hash()}",
            )
            continue
        validated_specs.append((spec, result, validation_metrics))
        if validation_metrics.risk is not None and validation_metrics.risk.sharpe is not None:
            trial_sharpes.append(validation_metrics.risk.sharpe)

    # >= this batch's own size: the cumulative corpus count can lag a
    # freshly-introduced symbol's own first grid (COUNT(*) over `results`
    # doesn't yet include this cycle's own in-flight specs).
    n_trials_for_deflation = max(await trials_to_date(session), len(per_spec))
    current_regime = classify_current_regime(bars)

    experiment_ids: list[str] = []
    for spec, result, validation_metrics in validated_specs:
        row = (
            await session.execute(
                _SELECT_LATEST_EXPERIMENT_FOR_SPEC, {"config_hash": spec.config_hash()}
            )
        ).first()
        if row is None:
            continue  # run_one hasn't recorded this spec yet -- next cycle
        experiment_id, strategy_id = row.id, row.strategy_id
        decay_metric_failure: str | None = None
        try:
            decay_profile = compute_decay(bars, spec)
        except Exception as exc:
            # Same independence rule compute_metrics already applies:
            # decay failing must not drop a spec that already has real
            # risk/turnover/IC evidence -- fall back to an honestly-empty
            # DecayProfile and record the failure, rather than letting it
            # propagate into the `except Exception: continue` below and
            # silently discard everything computed so far for this spec.
            decay_metric_failure = repr(exc)
            decay_profile = DecayProfile(
                ic_by_horizon={},
                claimed_horizon=spec.expected_horizon,
                claimed_horizon_ic=None,
                claimed_horizon_p_value=None,
                has_power_at_claimed_horizon=None,
            )

        metric_failures = dict(validation_metrics.metric_failures)
        if decay_metric_failure is not None:
            metric_failures["decay"] = decay_metric_failure

        try:
            await _validate_one_spec(
                session,
                spec=spec,
                result=result,
                validation_metrics=validation_metrics,
                decay_profile=decay_profile,
                metric_failures=metric_failures,
                experiment_id=experiment_id,
                strategy_id=strategy_id,
                pbo_value=pbo_value,
                trial_sharpes=trial_sharpes,
                n_trials_for_deflation=n_trials_for_deflation,
                current_regime=current_regime,
                cluster_info=cluster_info_by_hash.get(spec.config_hash()),
            )
        except Exception as exc:
            # One spec's validation failing (e.g. a degenerate fold split
            # on very short history) must not take the rest of the batch
            # down with it; the
            # worker's own drain_queue applies the identical isolation
            # rule per job via fail(), this is the same principle applied
            # per spec inside one validation pass.
            record_failure(
                "research",
                exc,
                context=f"validate_grid family={spec.family} hash={spec.config_hash()}",
            )
            continue
        experiment_ids.append(experiment_id)

    # PROMPT 7: re-elect each family's champion now that this batch's
    # verdicts (and therefore statuses) are current -- a stale CHAMPION
    # that a fresher VALIDATED strategy has since beaten must not linger.
    await elect_champions(session)

    await session.commit()
    return experiment_ids


async def validate_grid(
    session: AsyncSession, symbol: str, timeframe: str, family: str, days: int
) -> list[str]:
    """Re-evaluates `family`'s own deterministic grid against real PBO/
    Deflated Sharpe/decay/regime evidence. Unchanged signature/behavior
    -- now a thin wrapper over validate_specs; see validate_specs' own
    docstring for the full re-scoring behavior."""
    return await validate_specs(
        session, symbol, timeframe, generate_grid(symbol, timeframe, family), days
    )


async def validate_baseline_grid(
    session: AsyncSession, symbol: str, timeframe: str, days: int
) -> list[str]:
    """Every classic-template family, not just MOMENTUM -- the
    Oracle-side fix paired with enqueue_baseline_grid above.
    validate_grid's hardcoded family meant no non-MOMENTUM strategy
    could ever reach 'VALIDATED' status
    (population.verdict_to_status's only PROMOTE->VALIDATED path), and
    therefore never CHAMPION, and therefore never paper-traded."""
    return await validate_specs(
        session, symbol, timeframe, generate_baseline_grid(symbol, timeframe), days
    )


_NULL_DECAY_PROFILE_TEMPLATE: dict[str, Any] = {
    "ic_by_horizon": {},
    "claimed_horizon_ic": None,
    "claimed_horizon_p_value": None,
    "has_power_at_claimed_horizon": None,
}


def _null_decay_profile(spec: RotationSpec) -> DecayProfile:
    """RotationSpec's information_coefficient has no defined meaning --
    compute_decay calls signal_for(bars, spec), a single-symbol-signal
    concept a portfolio weight vector doesn't reduce to. Honestly None
    throughout, matching this codebase's existing 'absent beats
    fabricated' precedent (excess_sharpe below cpz-quant's 30-observation
    floor), not a silently-invented translation. Documented as a known
    gap in docs/DEFERRED.md."""
    return DecayProfile(claimed_horizon=spec.expected_horizon, **_NULL_DECAY_PROFILE_TEMPLATE)


async def validate_rotation_specs(
    session: AsyncSession, specs: list[RotationSpec], days: int
) -> list[str]:
    """Same re-scoring shape as validate_specs (PBO across the batch,
    correlation clustering, per-spec scoring/decision), but for
    RotationSpec: no top-level symbol/timeframe (each spec carries its
    own universe), and information_coefficient/icir/decay honestly None
    -- see _null_decay_profile. Like validate_specs, this function
    creates no new Experiment/Strategy rows -- it re-scores existing ones
    already recorded by run_one, found by config_hash."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    cost_config, _cost_config_hash = load_cost_config()
    cost_model = make_cost_model(cost_config)

    per_spec: list[tuple[RotationSpec, Any]] = []
    for spec in specs:
        try:
            all_symbols = list(spec.universe)
            pit, _data_version_hash = await load_point_in_time(
                session, all_symbols, spec.timeframe, start, end
            )
            membership = await membership_windows(session, "etf", all_symbols)
            benchmark_result = compute_benchmark_curve(pit, all_symbols, end, cost_model=cost_model)
            result = run_portfolio_backtest(
                pit, spec, membership, end, cost_model=cost_model, benchmark_result=benchmark_result
            )
        except ValueError:
            continue  # not enough bars yet for this spec's universe/lookback
        per_spec.append((spec, result))

    if not per_spec:
        return []

    # PBO is a property of the SELECTION among trials, not of any one
    # trial -- same batch-level treatment validate_specs gives it.
    min_len = min(len(result.equity_curve) for _, result in per_spec)
    n_splits = _pbo_n_splits(min_len - 1)
    pbo_value: float | None = None
    if n_splits is not None and len(per_spec) >= 2:
        returns_columns = []
        for _, result in per_spec:
            equities = [equity for _, equity in result.equity_curve[-min_len:]]
            returns_columns.append(
                [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
            )
        returns_matrix = np.array(returns_columns).T
        pbo_result = probability_of_backtest_overfitting(returns_matrix, n_splits=n_splits)
        pbo_value = pbo_result.pbo

    # cluster_by_correlation (research/clustering.py) is StrategySpec-only:
    # its representative-tiebreaker reads `spec.parameters`, a property
    # RotationSpec doesn't define, so calling it here would raise
    # AttributeError, not just mistype -- clustering.py is outside this
    # task's own authorized scope (not listed among the files it may
    # touch). cluster_info stays honestly None for every RotationSpec,
    # same "absent beats fabricated" precedent as the null decay/IC
    # fields above. See docs/DEFERRED.md.
    cluster_info_by_hash: dict[str, dict[str, Any]] = {}

    validated_specs: list[tuple[RotationSpec, Any, ValidationMetrics]] = []
    trial_sharpes: list[float] = []
    for spec, result in per_spec:
        equity_values = [equity for _, equity in result.equity_curve]
        risk = compute_risk_analytics(equity_values) if len(equity_values) >= 2 else None
        validation_metrics = ValidationMetrics(
            risk=risk,
            turnover=result.turnover,
            # hit_rate IS just an equity-curve property (fraction of bars
            # where equity rose), not a single-symbol-signal concept like
            # IC -- computed for real, unlike information_coefficient/icir
            # below.
            hit_rate=compute_hit_rate(result.equity_curve),
            information_coefficient=None,
            icir=None,
        )
        validated_specs.append((spec, result, validation_metrics))
        if risk is not None and risk.sharpe is not None:
            trial_sharpes.append(risk.sharpe)

    # >= this batch's own size -- same reasoning validate_specs' own
    # comment gives for this bound.
    n_trials_for_deflation = max(await trials_to_date(session), len(per_spec))

    experiment_ids: list[str] = []
    for spec, result, validation_metrics in validated_specs:
        row = (
            await session.execute(
                _SELECT_LATEST_EXPERIMENT_FOR_SPEC, {"config_hash": spec.config_hash()}
            )
        ).first()
        if row is None:
            continue  # run_one hasn't recorded this spec yet -- next cycle
        experiment_id, strategy_id = row.id, row.strategy_id

        try:
            await _validate_one_spec(
                session,
                spec=spec,
                result=result,
                validation_metrics=validation_metrics,
                decay_profile=_null_decay_profile(spec),
                experiment_id=experiment_id,
                strategy_id=strategy_id,
                pbo_value=pbo_value,
                trial_sharpes=trial_sharpes,
                n_trials_for_deflation=n_trials_for_deflation,
                # Honest: no single symbol's bars to classify a regime
                # from -- a RotationSpec trades a whole universe, not one
                # instrument classify_current_regime could read.
                current_regime="UNKNOWN",
                cluster_info=cluster_info_by_hash.get(spec.config_hash()),
                metric_failures=validation_metrics.metric_failures,
            )
        except Exception as exc:
            record_failure(
                "research", exc, context=f"validate_rotation_specs hash={spec.config_hash()}"
            )
            continue
        experiment_ids.append(experiment_id)

    await elect_champions(session)
    await session.commit()
    return experiment_ids


async def _validate_one_spec(
    session: AsyncSession,
    *,
    spec: StrategySpec | RotationSpec,
    result: Any,
    validation_metrics: Any,
    decay_profile: DecayProfile,
    experiment_id: str,
    strategy_id: str | None,
    pbo_value: float | None,
    trial_sharpes: list[float],
    n_trials_for_deflation: int,
    current_regime: str,
    cluster_info: dict[str, Any] | None,
    metric_failures: dict[str, str],
) -> None:
    strategy_equity_values = [equity for _, equity in result.equity_curve]

    risk = validation_metrics.risk
    dsr_value = None
    if risk is not None and risk.sharpe is not None and len(strategy_equity_values) >= 2:
        skewness = risk.skew if risk.skew is not None else 0.0
        excess_kurtosis = risk.excess_kurtosis if risk.excess_kurtosis is not None else 0.0
        dsr_result = deflated_sharpe_ratio(
            trial_sharpes_for_variance=trial_sharpes,
            this_trial_sharpe=risk.sharpe,
            n_trials_for_deflation=n_trials_for_deflation,
            n_observations=len(strategy_equity_values),
            skewness=skewness,
            kurtosis=excess_kurtosis + 3.0,
        )
        dsr_value = dsr_result.deflated_sharpe

    regime_result = regime_breakdown(strategy_equity_values)
    consistent_across_regimes = (
        regime_result.consistent_across_regimes if regime_result is not None else None
    )

    score_inputs = ScoreInputs(
        excess_return=result.vs_benchmark.excess_return,
        excess_sharpe=result.vs_benchmark.excess_sharpe,
        pbo=pbo_value,
        deflated_sharpe=dsr_value,
        has_power_at_claimed_horizon=decay_profile.has_power_at_claimed_horizon,
    )

    prior = (
        await session.execute(_SELECT_LATEST_VERDICT_FOR_FINGERPRINT, {"fp": spec.config_hash()})
    ).first()
    evidence = Evidence(
        score_inputs=score_inputs,
        turnover=result.turnover,
        consistent_across_regimes=consistent_across_regimes,
        previous_verdict=prior.verdict if prior is not None else None,
        metric_failures=tuple(metric_failures),
    )
    decision_result = decide(evidence)

    metrics_payload = {
        "risk": risk.to_dict() if risk is not None else None,
        "turnover": validation_metrics.turnover,
        "hit_rate": validation_metrics.hit_rate,
        "information_coefficient": validation_metrics.information_coefficient,
        "icir": validation_metrics.icir,
        "decay": {
            "ic_by_horizon": decay_profile.ic_by_horizon,
            "claimed_horizon": decay_profile.claimed_horizon,
            "claimed_horizon_ic": decay_profile.claimed_horizon_ic,
            "claimed_horizon_p_value": decay_profile.claimed_horizon_p_value,
            "has_power_at_claimed_horizon": decay_profile.has_power_at_claimed_horizon,
        },
        "regime": {
            "current": current_regime,
            "consistent_across_regimes": consistent_across_regimes,
        },
        "excess_return": result.vs_benchmark.excess_return,
        "excess_sharpe": result.vs_benchmark.excess_sharpe,
        # None when this spec's correlation with the rest of its batch
        # couldn't be computed (e.g. this spec never traded and has zero
        # return variance) -- an honest "not clustered", not a fabricated
        # singleton.
        "cluster": cluster_info,
        # Which named metrics failed to compute and why, never silently
        # absorbed -- see validation/metrics.py's ValidationMetrics.
        # metric_failures docstring. Empty for the overwhelming majority
        # of specs; non-empty is a real signal something needs attention,
        # surfaced verbatim rather than guessed away.
        "metric_failures": metric_failures,
    }

    session.add(
        ValidationResult(
            experiment_id=experiment_id,
            strategy_fingerprint=spec.config_hash(),
            verdict=decision_result.verdict.value,
            score=decision_result.score,
            reason_codes=decision_result.reason_codes,
            pbo=pbo_value,
            deflated_sharpe=dsr_value,
            metrics=metrics_payload,
        )
    )
    session.add(
        Decision(
            experiment_id=experiment_id,
            decision={
                "decision": decision_result.verdict.value,
                "reason": "validation",
                "reason_codes": decision_result.reason_codes,
            },
        )
    )
    if strategy_id is not None:
        # PROMPT 7: EVERY verdict updates strategies.status, not just
        # PROMOTE -- population.verdict_to_status is the one real mapping
        # from an Oracle verdict to a population lifecycle state.
        new_status = verdict_to_status(decision_result.verdict.value)
        await session.execute(_UPDATE_STRATEGY_STATUS, {"status": new_status, "id": strategy_id})


_RUN_BACKTEST_KIND = "run_backtest"


async def enqueue_specs(
    symbol: str,
    timeframe: str,
    specs: Sequence[StrategySpec | RotationSpec],
    days: int,
    *,
    priority: int,
    expected_information_value: float,
    estimated_cost: float,
    max_attempts: int,
) -> list[str]:
    """Enqueues one job per given StrategySpec/RotationSpec. idempotency_key =
    sha256(kind, spec.config_hash(), days) -- re-running this for an
    unchanged spec list re-enqueues nothing (queue.enqueue's ON CONFLICT
    DO NOTHING), rather than duplicating work already queued or already
    run. The real body enqueue_grid/enqueue_baseline_grid/
    enqueue_rotation_grid all wrap. `symbol`/`timeframe` are accepted but
    unused inside this function's own body -- kept only so this stays a
    drop-in replacement for callers that pass them (enqueue_grid,
    enqueue_baseline_grid); enqueue_rotation_grid passes empty strings
    since a RotationSpec's universe, not a single (symbol, timeframe)
    pair, is what identifies its grid."""
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
                    payload={
                        "spec": spec.model_dump(),
                        "spec_kind": "rotation" if isinstance(spec, RotationSpec) else "strategy",
                        "days": days,
                    },
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


async def enqueue_grid(
    symbol: str, timeframe: str, family: str, days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Enqueues one job per StrategySpec in `family`'s own deterministic
    grid. Unchanged signature/behavior -- now a thin wrapper over
    enqueue_specs so every existing caller keeps working exactly as
    before."""
    return await enqueue_specs(
        symbol, timeframe, generate_grid(symbol, timeframe, family), days,
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )


async def enqueue_baseline_grid(
    symbol: str, timeframe: str, days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Every classic-template family's grid
    (research.generate.generate_baseline_grid), not just MOMENTUM -- the
    fix for the bug documented in
    docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md:
    worker.py's _run_research() called enqueue_grid with a hardcoded
    family, so BOLLINGER/VOL_BREAKOUT/RSI/MACD strategies were never
    enqueued through this path at all."""
    return await enqueue_specs(
        symbol, timeframe, generate_baseline_grid(symbol, timeframe), days,
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )


async def enqueue_rotation_grid(
    generate_grid_fn: Callable[[], list[RotationSpec]], days: int, *,
    priority: int, expected_information_value: float, estimated_cost: float, max_attempts: int,
) -> list[str]:
    """Enqueues one rotation family's own grid -- no (symbol, timeframe)
    args, unlike enqueue_grid/enqueue_baseline_grid, because a
    RotationSpec's universe is fixed by its own grid generator, not
    supplied per-call the way a single-symbol grid needs a symbol.
    symbol/timeframe are passed as "" -- verified unused inside
    enqueue_specs's own body (see its docstring)."""
    return await enqueue_specs(
        "", "", generate_grid_fn(), days,
        priority=priority, expected_information_value=expected_information_value,
        estimated_cost=estimated_cost, max_attempts=max_attempts,
    )


async def _run_job(job: Job) -> str:
    """Executes one claimed job's payload against real data -- the only
    kind this worker understands is run_backtest. A separate session from
    the one claim() used: see queue.claim's docstring on why the claiming
    transaction must already be committed before work starts.

    `parent_experiment_id`/`hypothesis`/`change_set` are optional payload
    keys -- present when this job was enqueued by PROMPT 7's evolution
    step (worker.py), absent for a plain grid job (enqueue_grid never
    sets them). `run_one` already accepts and threads all three through
    to the Experiment row (migration 0006's lineage columns); this is
    just the payload -> kwargs bridge, not new lineage logic."""
    if job.kind != _RUN_BACKTEST_KIND:
        raise ValueError(f"unknown job kind: {job.kind!r}")
    spec_kind = job.payload.get("spec_kind", "strategy")
    spec: StrategySpec | RotationSpec
    if spec_kind == "rotation":
        spec = RotationSpec.model_validate(job.payload["spec"])
    else:
        spec = StrategySpec.model_validate(job.payload["spec"])
    days = job.payload["days"]
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    async with get_session() as session:
        return await run_one(
            session,
            spec,
            start,
            end,
            parent_experiment_id=job.payload.get("parent_experiment_id"),
            hypothesis=job.payload.get("hypothesis"),
            change_set=job.payload.get("change_set"),
        )


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

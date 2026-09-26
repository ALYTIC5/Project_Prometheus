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

Now five concerns run at five different rates from this ONE entrypoint,
gated by worker_cadence (is_due/mark_run below): ingest hourly, research
(today's grid/validate/evolve pipeline -- every classic-template family
AND every ML component, RANDOM_FOREST/GRADIENT_BOOSTING/
LOGISTIC_REGRESSION/SVM, not just MOMENTUM) every 30 minutes, paper
trading every tick, llm_ingestion every 2h -- arXiv q-fin abstracts
into research_papers up to PAPERS_PER_DAY, walking the backlog once new
papers run out -- and ablation daily: the six real
component-vs-baseline A/B batches (evolution, LLM hypotheses, and every
ML family) that were previously written but never scheduled anywhere in
production (docs/DEFERRED.md's "RANDOM_FOREST strategy family" entry),
bounded to a small symbol subset for the same reason register_evolution_
component's own docstring already bounds its generations. The research
cycle itself also carries one bounded, budget-gated LLM hypothesis step,
which enqueues its candidate through the SAME queue.enqueue() path as
grid and evolution children and is isolated so its failure can never
sink the deterministic work around it. The Railway cron interval itself
tightens from */30 to */15 (the finest of the five rates) so the paper
concern's tick actually happens on schedule -- still one scheduled
worker, not a second service.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.cadence import (
    ABLATION_INTERVAL_SECONDS as _ABLATION_INTERVAL_SECONDS,
)
from prometheus.core.cadence import (
    CADENCE_SLACK_FACTOR as _CADENCE_SLACK_FACTOR,
)
from prometheus.core.cadence import (
    INGEST_INTERVAL_SECONDS as _INGEST_INTERVAL_SECONDS,
)
from prometheus.core.cadence import (
    LLM_INGESTION_INTERVAL_SECONDS as _LLM_INGESTION_INTERVAL_SECONDS,
)
from prometheus.core.cadence import (
    PAPER_INTERVAL_SECONDS as _PAPER_INTERVAL_SECONDS,
)
from prometheus.core.cadence import (
    RESEARCH_INTERVAL_SECONDS as _RESEARCH_INTERVAL_SECONDS,
)
from prometheus.core.db import get_research_session, get_session
from prometheus.core.health import (
    alert_discord_for_threshold_breaches,
    flush_cycle,
    record_failure,
)
from prometheus.core.provenance import code_sha
from prometheus.core.seeds import derive_seed, rng_for
from prometheus.data.ingest_etf import backfill_etf
from prometheus.data.ingestion import backfill, load_universe_symbols
from prometheus.data.loaders import load_point_in_time
from prometheus.data.schema import PointInTimeFrame
from prometheus.experiments.ablation import (
    register_evolution_component,
    register_gradient_boosting_component,
    register_llm_component,
    register_logistic_regression_component,
    register_ml_component,
    register_svm_component,
)
from prometheus.experiments.queue import (
    enqueue,
    get_queue_settings,
    reap_stale_claims,
    requeue_succeeded,
)
from prometheus.experiments.runner import (
    drain_queue,
    enqueue_baseline_grid,
    enqueue_rotation_grid,
    enqueue_specs,
    latest_experiment_id_for_spec,
    validate_baseline_grid,
    validate_rotation_specs,
    validate_specs,
)
from prometheus.paper.broker import PaperBroker
from prometheus.paper.divergence import check_divergence
from prometheus.paper.execution import decide_and_submit, poll_fills
from prometheus.paper.reconciliation import (
    check_worse_than_holding,
    compute_paper_equity_curve,
    reconcile_order,
)
from prometheus.paper.sim_broker import SimBroker
from prometheus.research.crossover import crossover
from prometheus.research.llm.budget import current_tier, estimate_cost, model_for_tier
from prometheus.research.llm.extraction import (
    EXTRACTION_BATCH_SIZE,
    ExtractedClaim,
    extract_claims_batch,
)
from prometheus.research.llm.hypothesis import (
    LLMResponseError,
    PaperContext,
    _AnthropicClientProtocol,
    generate_hypothesis,
)
from prometheus.research.llm.ingestion import (
    abstract_only_paper,
    base_arxiv_id,
    search_arxiv,
)
from prometheus.research.llm.linking import ClaimRef, link_claims
from prometheus.research.llm.relevance import is_relevant
from prometheus.research.ml.generate import (
    generate_gradient_boosting_grid,
    generate_logistic_regression_grid,
    generate_random_forest_grid,
    generate_svm_grid,
)
from prometheus.research.mutations import parameter_tune, swap_family
from prometheus.research.population import (
    select_for_cross_breeding,
    select_for_exploitation,
    select_for_exploration,
)
from prometheus.research.prioritisation import ParentContext, expected_information_value
from prometheus.research.rotation_generate import ROTATION_GRID_GENERATORS
from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.rotation_spec import ROTATION_FAMILIES
from prometheus.strategy.spec import FAMILIES, StrategySpec
from prometheus.validation.holdout import access_holdout_for_paper


def _anthropic_client() -> _AnthropicClientProtocol:
    """Constructed lazily, once per worker cycle -- not at import time,
    so importing worker.py (e.g. from tests) never requires
    ANTHROPIC_API_KEY to be set.

    M1 (final-review fix wave): typed as hypothesis.py's own
    _AnthropicClientProtocol rather than bare `object` -- worker.py still
    doesn't need to know the real anthropic.Anthropic type, but `object`
    made the generate_hypothesis call site a mypy argument-type error.
    The protocol IS the contract this function promises to satisfy."""
    import anthropic

    return anthropic.Anthropic()


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

# Fixed arXiv category filter (Quantitative Finance), never a query derived
# from strategy state -- ingestion must not depend on research outcomes.
_LLM_ARXIV_QUERY = "cat:q-fin.*"

# Paper ingestion walks arXiv q-fin newest-first, then keeps paging deeper
# into the backlog -- q-fin only publishes a few dozen papers a day, so a
# daily target of PAPERS_PER_DAY (env, required) is reached from history.
# arXiv's API terms ask for no more than one request every 3 seconds.
_ARXIV_PAGE_SIZE = 100
_ARXIV_MAX_PAGES_PER_RUN = 5
_ARXIV_CALL_SPACING_SECONDS = 3.0

_SELECT_PAPER_ARXIV_IDS = text("SELECT arxiv_id FROM research_papers")
_COUNT_PAPERS_LAST_24H = text(
    "SELECT count(*) FROM research_papers WHERE ingested_at > now() - interval '24 hours'"
)

# Paper ingestion is its own worker_cadence concern, coarser than the
# 30-min research cycle -- same "different concerns, different rates from
# one entrypoint" pattern ingest/research/paper already use.
#
# The five interval constants and the slack factor are imported from
# core/cadence.py (see the top of this file) rather than defined here --
# GET /pipeline/ (the dashboard's pipeline-status panel) needs them too.

# Daily, same reasoning as LLM ingestion above: six real component-vs-
# baseline A/B batches (evolution, LLM hypotheses, and every ML family)
# is real, non-trivial walk-forward-backtest compute -- bounded to a
# small symbol subset for the same reason register_evolution_component's
# own docstring already bounds its generations to "tens... against 1-2
# real symbols, not a compute spike". Without this concern,
# component_registry (the Temple of Knowledge's verdicts) stays empty
# forever regardless of how many real strategies any of these mechanisms
# produces -- the pre-existing gap documented in
# docs/DEFERRED.md's "RANDOM_FOREST strategy family" entry.
_ABLATION_SYMBOLS_LIMIT = 2
_ABLATION_WINDOW_DAYS = 180
_ABLATION_EVOLUTION_GENERATIONS = 10

_SELECT_CADENCE = text("SELECT last_run_at FROM worker_cadence WHERE concern = :concern")
_UPSERT_CADENCE = text(
    """
    INSERT INTO worker_cadence (concern, last_run_at) VALUES (:concern, now())
    ON CONFLICT (concern) DO UPDATE SET last_run_at = now()
    """
)


# One-time backfill marker (worker_cadence row; never re-run once present).
# 2026-09-24 Law 8 benchmark fix: every result recorded before it compared
# the strategy against a buy-and-hold over the full loaded history instead of
# the strategy's own post-warm-up window. Re-running each already-succeeded
# backtest job once appends a superseding experiment/result under the
# corrected benchmark; the drain's time budget spreads it across cycles.
_BENCHMARK_BACKFILL_MARKER = "bench_fix_0924"


async def _run_one_time_backfills() -> None:
    async with get_session() as session:
        done = (
            await session.execute(_SELECT_CADENCE, {"concern": _BENCHMARK_BACKFILL_MARKER})
        ).first()
        if done is not None:
            return
        requeued = await requeue_succeeded(session, kind=_RUN_BACKTEST_KIND)
        await session.execute(_UPSERT_CADENCE, {"concern": _BENCHMARK_BACKFILL_MARKER})
        await session.commit()
    print(f"worker: benchmark backfill re-queued {requeued} succeeded backtest job(s)")


async def is_due(session: AsyncSession, *, concern: str, interval_seconds: float) -> bool:
    """True if `concern` has never run, or last ran more than
    interval_seconds * _CADENCE_SLACK_FACTOR ago. Each concern gates
    itself independently so one tightened */15 cron can serve three
    different cadences (PROMPTS.md's own schedule: ingest hourly /
    research 30min / paper 15min) without a second scheduled service."""
    row = (await session.execute(_SELECT_CADENCE, {"concern": concern})).first()
    if row is None:
        return True
    elapsed = (datetime.now(UTC) - row.last_run_at).total_seconds()
    return bool(elapsed >= interval_seconds * _CADENCE_SLACK_FACTOR)


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
    # I1 (final-review fix wave): `child.source` is part of the key.
    # config_hash() deliberately excludes source (it identifies BEHAVIOR,
    # see spec.py's _IDENTITY_FIELDS), so without this an LLM hypothesis
    # that happens to land on an existing grid point (fast=10/slow=50 is
    # an actual grid coordinate) deduped straight into the grid's job:
    # no strategy row with source='llm_hypothesis' was ever created,
    # register_llm_component found nothing forever, and Anthropic was
    # billed anyway. Re-running the same generator still dedupes against
    # itself -- each generator sets its own source consistently
    # ("deterministic_grid"/"mutation"/"llm_hypothesis") -- so the only
    # behavior change is that two DIFFERENT generators proposing the same
    # parameters now each get their own job and strategy row.
    idempotency_key = hashlib.sha256(
        f"{_RUN_BACKTEST_KIND}|{child.source}|{child.config_hash()}|{_GRID_LOOKBACK_DAYS}".encode()
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
    # I7 (final-review fix wave): reap_stale_claims used to run here, but
    # this concern is only hourly-gated while research's drain_queue (30
    # min) can run without ingest on the ticks in between -- moved to
    # run_once()'s top so it runs every tick regardless of cadence; see
    # that function for the full reasoning.
    await backfill(_INGEST_CATCHUP_DAYS)
    # Cross-sectional rotation families (sector/GEM/GTAA) trade a FIXED
    # ETF universe, not the crypto universe backfill() above covers --
    # without this, ohlcv_bars never gets ETF rows and every rotation
    # run_one raises ValueError("not enough bars"), harmlessly but
    # pointlessly, every research cycle. Same _INGEST_CATCHUP_DAYS window
    # as the crypto backfill above for consistency, and because it
    # matches _GRID_LOOKBACK_DAYS -- the rotation grid's own lookback --
    # for the same "wide enough that a fresh DB always has enough bars"
    # reasoning documented on _INGEST_CATCHUP_DAYS itself.
    #
    # I3 (final-review fix wave): isolated in its own try/except, same
    # per-concern isolation pattern run_once() and _run_ablation()'s
    # _register() already apply. backfill_etf talks to Alpaca, a
    # SECOND, independent provider: missing/bad credentials or an
    # Alpaca outage would otherwise fail this whole concern AFTER the
    # crypto backfill above had already succeeded and committed, and
    # because run_once() only calls mark_run(concern="ingest") when the
    # whole concern returns cleanly, the ingest concern would stay
    # permanently "due" -- re-running the hourly crypto backfill on
    # every 15-minute tick indefinitely. Crypto ingest must not depend
    # on the ETF provider's health.
    try:
        await backfill_etf(_INGEST_CATCHUP_DAYS)
    except Exception as exc:
        record_failure("ingest", exc, context="etf")


def _papers_per_run(papers_per_day: int) -> int:
    runs_per_day = 86400.0 / _LLM_INGESTION_INTERVAL_SECONDS
    return max(1, -(-papers_per_day // int(runs_per_day)))


async def _run_llm_ingestion() -> list[str]:
    """Populates research_papers from a fixed arXiv category query, never
    one derived from strategy/research state (see search_arxiv).

    Pages newest-first until a page holds nothing new, then jumps to a
    depth equal to the number of papers already stored and keeps walking
    into the backlog. Papers published since the last run can only shift
    known papers deeper, so the jump can re-show known papers but never
    skip an unseen one. Each paper is stored abstract-only and committed on
    its own, so a failure mid-run keeps everything before it."""
    papers_per_day = int(os.environ["PAPERS_PER_DAY"])
    ingested: list[str] = []
    async with get_research_session() as session:
        known = {
            base_arxiv_id(arxiv_id)
            for arxiv_id in (await session.execute(_SELECT_PAPER_ARXIV_IDS)).scalars()
        }
        last_24h = int((await session.execute(_COUNT_PAPERS_LAST_24H)).scalar_one())
        quota = min(papers_per_day - last_24h, _papers_per_run(papers_per_day))
        if quota <= 0:
            return ingested

        start = 0
        jumped_to_backlog = False
        for page_number in range(_ARXIV_MAX_PAGES_PER_RUN):
            if page_number:
                await asyncio.sleep(_ARXIV_CALL_SPACING_SECONDS)
            page = await search_arxiv(_LLM_ARXIV_QUERY, _ARXIV_PAGE_SIZE, start=start)
            if not page:
                break
            new = [paper for paper in page if base_arxiv_id(paper.arxiv_id) not in known]
            for paper in new:
                session.add(abstract_only_paper(paper))
                await session.commit()
                known.add(base_arxiv_id(paper.arxiv_id))
                ingested.append(paper.arxiv_id)
                if len(ingested) >= quota:
                    return ingested
            if not new and not jumped_to_backlog:
                start = max(start + _ARXIV_PAGE_SIZE, len(known))
                jumped_to_backlog = True
            else:
                start += _ARXIV_PAGE_SIZE
    return ingested


async def _run_ablation() -> list[str]:
    """The daily-cadence concern that actually runs the six real A/B
    ablations (evolution, LLM hypotheses, and every ML strategy family)
    against the deterministic baseline grid on real out-of-sample data.
    Bounded to a small symbol subset and a fixed historical window, not
    the full universe -- six real walk-forward backtest batches is real
    compute (see this session's own final-review cost findings), and
    this concern's whole point is honest measurement, not maximum
    coverage. Each registration is isolated: one component's failure
    (a real out-of-sample data gap, say) must not prevent the other
    five from recording their own verdict this cycle, same "one
    concern's failure can't sink the others" principle run_once()
    already applies. version=code_sha(): a deploy that changes a
    component's own implementation starts a fresh, uncontaminated trial
    history for it rather than mixing evidence across different code
    versions of "the same" component."""
    symbols = load_universe_symbols()[:_ABLATION_SYMBOLS_LIMIT]
    if not symbols:
        return []
    end = datetime.now(UTC)
    start = end - timedelta(days=_ABLATION_WINDOW_DAYS)
    version = code_sha()
    verdicts: list[str] = []

    async def _register(name: str, register_fn: Any) -> None:
        try:
            async with get_session() as session:
                result = await register_fn(session)
            verdicts.append(f"{name}={result.verdict}")
        except Exception as exc:
            record_failure("ablation", exc, context=f"component={name!r}")

    await _register(
        "evolution",
        lambda session: register_evolution_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end,
            generations=_ABLATION_EVOLUTION_GENERATIONS, version=version,
        ),
    )
    await _register(
        "llm",
        lambda session: register_llm_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end, version=version,
        ),
    )
    await _register(
        "random_forest",
        lambda session: register_ml_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end, version=version,
        ),
    )
    await _register(
        "gradient_boosting",
        lambda session: register_gradient_boosting_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end, version=version,
        ),
    )
    await _register(
        "logistic_regression",
        lambda session: register_logistic_regression_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end, version=version,
        ),
    )
    await _register(
        "svm",
        lambda session: register_svm_component(
            session, symbols=symbols, timeframe=_TIMEFRAME, start=start, end=end, version=version,
        ),
    )
    return verdicts


_ML_GRID_GENERATORS = (
    generate_random_forest_grid,
    generate_gradient_boosting_grid,
    generate_logistic_regression_grid,
    generate_svm_grid,
)


async def _run_research() -> list[str]:
    research_started = time.monotonic()
    symbols = load_universe_symbols()
    for symbol in symbols:
        await enqueue_baseline_grid(
            symbol, _TIMEFRAME, _GRID_LOOKBACK_DAYS,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )
        for generate_ml_grid in _ML_GRID_GENERATORS:
            await enqueue_specs(
                symbol, _TIMEFRAME, generate_ml_grid(symbol, _TIMEFRAME),
                _GRID_LOOKBACK_DAYS,
                priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
            )

    # Cross-sectional rotation families (sector momentum, relative
    # strength, sector mean reversion, dual momentum, GTAA, equal-weight
    # baseline): each generator carries its OWN fixed universe, unlike
    # the per-symbol crypto grids above, so this runs once per family
    # per cycle -- outside the `for symbol in symbols:` loop, not once
    # per crypto symbol (that would be redundant: the same fixed ETF
    # universe enqueued len(symbols) times over).
    for generate_rotation_grid in ROTATION_GRID_GENERATORS:
        await enqueue_rotation_grid(
            generate_rotation_grid, _GRID_LOOKBACK_DAYS,
            priority=0, expected_information_value=0.0, estimated_cost=0.0, max_attempts=3,
        )

    # Half the research interval for backtests, leaving the rest for
    # validation/evolution/LLM so the cycle actually completes and
    # mark_run fires -- an operational budget (same class of choice as
    # _GRID_LOOKBACK_DAYS), not a statistical threshold. See
    # drain_queue's `deadline` docstring for the incident behind it.
    phase_started = time.monotonic()
    ran = await drain_queue(deadline=research_started + _RESEARCH_INTERVAL_SECONDS * 0.5)
    print(f"research: drained {len(ran)} job(s) in {time.monotonic() - phase_started:.0f}s")
    phase_started = time.monotonic()

    # The Oracle (PROMPTS.md PROMPT 5): re-scores every symbol's grid
    # against real PBO/DSR/decay/regime evidence and writes
    # validation_results. Every classic-template family AND every ML
    # component (RANDOM_FOREST/GRADIENT_BOOSTING/LOGISTIC_REGRESSION/
    # SVM), not just MOMENTUM -- see
    # docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md.
    #
    # Budgeted and rotated (2026-09-24): re-validating every symbol's full
    # grid re-runs every backtest -- hours of work -- so the unbounded loop
    # never finished inside the 30-minute slot and research.mark_run never
    # fired. Each unit (one symbol's grids, or one rotation family) is
    # started only while there's budget left (85% of the slot, leaving
    # room for evolution/LLM), and the starting unit rotates with each
    # research slot so every unit is re-validated over successive cycles.
    units: list[tuple[str, Any]] = [("symbol", symbol) for symbol in symbols] + [
        ("rotation", generate) for generate in ROTATION_GRID_GENERATORS
    ]
    offset = int(time.time() // _RESEARCH_INTERVAL_SECONDS) % max(len(units), 1)
    validation_deadline = research_started + _RESEARCH_INTERVAL_SECONDS * 0.85
    validated: list[str] = []
    units_done = 0
    async with get_session() as session:
        for kind, unit in units[offset:] + units[:offset]:
            if time.monotonic() >= validation_deadline:
                break
            if kind == "symbol":
                validated.extend(
                    await validate_baseline_grid(session, unit, _TIMEFRAME, _GRID_LOOKBACK_DAYS)
                )
                for generate_ml_grid in _ML_GRID_GENERATORS:
                    validated.extend(
                        await validate_specs(
                            session, unit, _TIMEFRAME,
                            generate_ml_grid(unit, _TIMEFRAME), _GRID_LOOKBACK_DAYS,
                        )
                    )
            else:
                validated.extend(
                    await validate_rotation_specs(session, unit(), _GRID_LOOKBACK_DAYS)
                )
            units_done += 1
    print(
        f"research: validated {units_done}/{len(units)} unit(s) "
        f"(starting at #{offset}), {len(validated)} verdict(s)"
    )

    # PROMPT 7: one bounded evolution step, after validate_grid so this
    # cycle's mutation/crossover parents are selected using freshly
    # re-scored statuses, not last cycle's. Children are enqueued for a
    # FUTURE drain_queue call, not drained this cycle -- keeps this
    # cycle's own runtime bounded, matching _GRID_LOOKBACK_DAYS's own
    # "one symbol's grid runs once" bounding rather than growing this
    # cycle's work by however many children get produced.
    async with get_session() as session:
        print(f"research: validation took {time.monotonic() - phase_started:.0f}s")
        evolved_job_ids = await _run_evolution_step(session)
        await session.commit()

        # PROMPT 9: one bounded LLM hypothesis, budget-gated. Anthropic client
        # construction is deferred to here (not import time) so importing
        # worker.py never requires a real API key.
        #
        # I2 (final-review fix wave): isolated in its own broad try/except.
        # Everything above has already been committed, but an exception
        # escaping here would propagate past this function's own `return`
        # and prevent run_once()'s `mark_run(concern="research")` from
        # firing at all -- leaving last_run_at stale, so the research
        # concern would re-run at every 15-minute tick instead of every 30
        # minutes, indefinitely. Broad Exception, not ValueError: a missing
        # LLM_MONTHLY_BUDGET_USD raises pydantic.ValidationError, a missing
        # ANTHROPIC_API_KEY raises inside the anthropic constructor, and
        # anthropic's own APIError subtypes are not ValueErrors either.
        # Same "one concern's failure must not sink unrelated work"
        # principle run_once() already applies per concern.
        try:
            client = _anthropic_client()
            # Law 9: the LLM path runs as the research DB role.
            async with get_research_session() as research_session:
                for _ in range(await _hypotheses_per_cycle(research_session)):
                    llm_job_id = await _run_llm_hypothesis_step(research_session, client=client)
                    await research_session.commit()
                    if llm_job_id is not None:
                        print(f"worker: enqueued LLM hypothesis job: {llm_job_id}")
        except Exception as exc:
            record_failure("research", exc, context="llm_hypothesis_step")
    if evolved_job_ids:
        print(f"worker: enqueued {len(evolved_job_ids)} evolved candidate(s): {evolved_job_ids}")

    return ran + validated


# One liquid, already-ingested representative per claim asset class. A claim
# about an asset class with no representative here is not turned into a
# hypothesis -- the engine cannot test it on data it doesn't have.
_ASSET_CLASS_SYMBOL: dict[str, str] = {
    "crypto": "BTC/USDT",
    "equity": "SPY",
    "multi_asset": "SPY",
    "fixed_income": "TLT",
    "commodity": "GLD",
    "fx": "UUP",
}

# Testable claims no hypothesis has tested yet, most-corroborated first
# (SUPPORTS links in either direction), newest next.
_SELECT_UNTESTED_CLAIM = text(
    """
    SELECT c.id, c.paper_id, c.mechanism, c.stated_effect, c.asset_class,
           c.family_hint, p.title, p.abstract
      FROM paper_claims c
      JOIN research_papers p ON p.id = c.paper_id
     WHERE c.testable
       AND c.family_hint IS NOT NULL
       AND c.asset_class = ANY(:asset_classes)
       AND NOT EXISTS (
             SELECT 1 FROM llm_hypotheses h
              WHERE h.claim_ids @> jsonb_build_array(c.id)
           )
     ORDER BY (
             SELECT count(*) FROM claim_links l
              WHERE l.relation = 'SUPPORTS' AND (l.claim_a = c.id OR l.claim_b = c.id)
           ) DESC,
           c.id DESC
     LIMIT 1
    """
)

_SELECT_LLM_GENERATION_VERDICT = text(
    """
    SELECT verdict, disabled FROM component_registry
     WHERE component = 'llm_generation'
     ORDER BY updated_at DESC
     LIMIT 1
    """
)


@dataclass(frozen=True)
class _ClaimContext:
    claim_id: int
    symbol: str
    paper: PaperContext


async def _next_untested_claim(session: AsyncSession) -> _ClaimContext | None:
    row = (
        await session.execute(
            _SELECT_UNTESTED_CLAIM, {"asset_classes": list(_ASSET_CLASS_SYMBOL)}
        )
    ).first()
    if row is None:
        return None
    return _ClaimContext(
        claim_id=row.id,
        symbol=_ASSET_CLASS_SYMBOL[row.asset_class],
        paper=PaperContext(
            paper_id=row.paper_id,
            key_sections=(
                f"Claim under test: {row.mechanism}\n"
                f"Effect the paper reports: {row.stated_effect}\n"
                f"Closest registered family: {row.family_hint}\n\n"
                f"Paper: {row.title}\n{row.abstract}"
            ),
        ),
    )


async def _hypotheses_per_cycle(session: AsyncSession) -> int:
    """1 per research cycle (the long-standing rate) until the ablation
    harness has shown LLM generation VALUABLE against the deterministic
    baseline; only then LLM_HYPOTHESES_PER_CYCLE (env) applies. More
    unproven hypotheses would only raise the trial count every other
    strategy's DSR is deflated by."""
    row = (await session.execute(_SELECT_LLM_GENERATION_VERDICT)).first()
    if row is None or row.verdict != "VALUABLE" or row.disabled:
        return 1
    return int(os.environ.get("LLM_HYPOTHESES_PER_CYCLE", "1"))


_INSERT_LLM_USAGE = text(
    """
    INSERT INTO llm_usage (model, input_tokens, output_tokens, est_cost_usd, purpose)
    VALUES (:model, :input_tokens, :output_tokens, :est_cost_usd, :purpose)
    """
)
_INSERT_LLM_HYPOTHESIS = text(
    """
    INSERT INTO llm_hypotheses
        (strategy_fingerprint, paper_ids, claim_ids, hypothesis_text, expected_effect,
         model, input_tokens, output_tokens, est_cost_usd)
    VALUES
        (:strategy_fingerprint, :paper_ids, :claim_ids, :hypothesis_text, :expected_effect,
         :model, :input_tokens, :output_tokens, :est_cost_usd)
    """
).bindparams(bindparam("paper_ids", type_=JSONB), bindparam("claim_ids", type_=JSONB))


async def _log_llm_usage(
    session: AsyncSession,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    est_cost_usd: float,
    purpose: str = "hypothesis_generation",
) -> None:
    """Writes one llm_usage row and commits it ON ITS OWN (I3). The spend
    has already happened at the provider the moment the API call returned;
    its record must not be able to roll back because some LATER step in
    this cycle (the llm_hypotheses insert, the enqueue) failed. Losing the
    hypothesis record while keeping the usage row is the correct
    asymmetry -- the budget cap is only trustworthy if it sees every
    dollar actually spent."""
    await session.execute(
        _INSERT_LLM_USAGE,
        {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "est_cost_usd": est_cost_usd,
            "purpose": purpose,
        },
    )
    await session.commit()


# Papers with no successful extraction and fewer than
# _MAX_EXTRACTION_ATTEMPTS attempts. An unparseable response is usually the
# model's problem, not the paper's, but retrying forever would re-bill a
# paper the model genuinely can't handle.
_MAX_EXTRACTION_ATTEMPTS = 2
_SELECT_UNEXTRACTED_PAPERS = text(
    """
    SELECT p.id, p.title, p.abstract
      FROM research_papers p
     WHERE NOT EXISTS (
             SELECT 1 FROM paper_extractions e
              WHERE e.paper_id = p.id AND e.model NOT LIKE :unparseable_pattern
           )
       AND (SELECT count(*) FROM paper_extractions e WHERE e.paper_id = p.id)
           < :max_attempts
     ORDER BY p.id DESC
     LIMIT :limit
    """
)
_INSERT_PAPER_CLAIM = text(
    """
    INSERT INTO paper_claims (paper_id, mechanism, asset_class, horizon, direction,
                              stated_effect, data_period, testable, family_hint, model)
    VALUES (:paper_id, :mechanism, :asset_class, :horizon, :direction,
            :stated_effect, :data_period, :testable, :family_hint, :model)
    RETURNING id
    """
)
_INSERT_CLAIM_CONCEPT = text(
    "INSERT INTO claim_concepts (claim_id, concept) VALUES (:claim_id, :concept)"
)
_INSERT_PAPER_EXTRACTION = text(
    "INSERT INTO paper_extractions (paper_id, model, n_claims) VALUES (:paper_id, :model, :n)"
)
_SELECT_LINK_CANDIDATES = text(
    """
    SELECT c.id, c.mechanism, c.asset_class, c.horizon
      FROM paper_claims c
      JOIN claim_concepts cc ON cc.claim_id = c.id
     WHERE cc.concept = ANY(:concepts) AND c.paper_id <> :paper_id
       AND c.id < :claim_id
     GROUP BY c.id
     ORDER BY count(*) DESC, c.id DESC
     LIMIT :limit
    """
)
_INSERT_CLAIM_LINK = text(
    """
    INSERT INTO claim_links (claim_a, claim_b, relation, rationale, model)
    VALUES (:claim_a, :claim_b, :relation, :rationale, :model)
    ON CONFLICT ON CONSTRAINT uq_claim_links_pair DO NOTHING
    """
)
_LINK_CANDIDATES_PER_CLAIM = 10
# paper_extractions.model for a paper the free relevance gate skipped -- a
# completed (not unparseable) outcome, so it is never retried.
_RELEVANCE_FILTER_MARKER = "relevance-filter"


async def _log_failed_call(session: AsyncSession, exc: LLMResponseError, purpose: str) -> None:
    await _log_llm_usage(
        session, model=exc.model, input_tokens=exc.input_tokens,
        output_tokens=exc.output_tokens,
        est_cost_usd=estimate_cost(
            exc.model, input_tokens=exc.input_tokens, output_tokens=exc.output_tokens
        ),
        purpose=purpose,
    )


async def _store_claims(
    session: AsyncSession, paper_id: int, claims: list[ExtractedClaim], model: str
) -> list[tuple[ClaimRef, tuple[str, ...], int]]:
    """Inserts one paper's claims and concepts; returns the TESTABLE ones
    as (ref, concepts, paper_id) for linking."""
    testable: list[tuple[ClaimRef, tuple[str, ...], int]] = []
    for claim in claims:
        claim_id = int(
            (
                await session.execute(
                    _INSERT_PAPER_CLAIM,
                    {
                        "paper_id": paper_id,
                        "mechanism": claim.mechanism,
                        "asset_class": claim.asset_class,
                        "horizon": claim.horizon,
                        "direction": claim.direction,
                        "stated_effect": claim.stated_effect,
                        "data_period": claim.data_period,
                        "testable": claim.testable,
                        "family_hint": claim.family_hint,
                        "model": model,
                    },
                )
            ).scalar_one()
        )
        for concept in claim.concepts:
            await session.execute(
                _INSERT_CLAIM_CONCEPT, {"claim_id": claim_id, "concept": concept}
            )
        if claim.testable and claim.concepts:
            testable.append(
                (
                    ClaimRef(claim_id, claim.mechanism, claim.asset_class, claim.horizon),
                    claim.concepts,
                    paper_id,
                )
            )
    return testable


async def _link_claim(
    session: AsyncSession,
    client: _AnthropicClientProtocol,
    ref: ClaimRef,
    concepts: tuple[str, ...],
    paper_id: int,
) -> int:
    candidates = [
        ClaimRef(row.id, row.mechanism, row.asset_class, row.horizon)
        for row in (
            await session.execute(
                _SELECT_LINK_CANDIDATES,
                # Older claims only: each pair is linked once, from the newer
                # claim's side, even when both arrive in the same run.
                {"concepts": list(concepts), "paper_id": paper_id,
                 "claim_id": ref.claim_id, "limit": _LINK_CANDIDATES_PER_CLAIM},
            )
        ).all()
    ]
    if not candidates:
        return 0
    try:
        linking = await link_claims(client, new=ref, candidates=candidates)
    except LLMResponseError as exc:
        await _log_failed_call(session, exc, "claim_linking")
        return 0
    await _log_llm_usage(
        session, model=linking.model, input_tokens=linking.input_tokens,
        output_tokens=linking.output_tokens, est_cost_usd=linking.est_cost_usd,
        purpose="claim_linking",
    )
    for link in linking.links:
        await session.execute(
            _INSERT_CLAIM_LINK,
            {
                "claim_a": link.claim_a,
                "claim_b": link.claim_b,
                "relation": link.relation,
                "rationale": link.rationale,
                "model": linking.model,
            },
        )
    await session.commit()
    return len(linking.links)


async def _run_paper_knowledge(
    session: AsyncSession, *, client: _AnthropicClientProtocol
) -> tuple[int, int, int]:
    """Extracts claims from not-yet-processed papers and links testable
    claims to related claims from other papers. Returns (papers processed,
    claims stored, links stored).

    Token discipline: a free rule-based relevance gate (research/llm/
    relevance.py) marks off-topic papers without any LLM call; the rest go
    EXTRACTION_BATCH_SIZE papers per call; only testable claims -- the ones
    that can become strategies -- are linked. Every billed call is logged to
    llm_usage before anything that can fail. An unparseable paper is marked
    so it is retried at most _MAX_EXTRACTION_ATTEMPTS times."""
    # Twice ingestion's per-run rate, so a backlog (retries, or papers
    # ingested while extraction was failing) drains instead of growing.
    per_run = 2 * _papers_per_run(int(os.environ["PAPERS_PER_DAY"]))
    papers = (
        await session.execute(
            _SELECT_UNEXTRACTED_PAPERS,
            {
                "limit": per_run,
                "max_attempts": _MAX_EXTRACTION_ATTEMPTS,
                "unparseable_pattern": "%:unparseable",
            },
        )
    ).all()
    n_papers = n_claims = n_links = 0

    relevant = [p for p in papers if is_relevant(p.title, p.abstract)]
    for paper in papers:
        if paper not in relevant:
            await session.execute(
                _INSERT_PAPER_EXTRACTION,
                {"paper_id": paper.id, "model": _RELEVANCE_FILTER_MARKER, "n": 0},
            )
            n_papers += 1
    await session.commit()

    to_link: list[tuple[ClaimRef, tuple[str, ...], int]] = []
    for start in range(0, len(relevant), EXTRACTION_BATCH_SIZE):
        if await current_tier(session) == "halted":
            break
        chunk = relevant[start : start + EXTRACTION_BATCH_SIZE]
        try:
            batch = await extract_claims_batch(client, [(p.title, p.abstract) for p in chunk])
        except LLMResponseError as exc:
            await _log_failed_call(session, exc, "paper_extraction")
            for paper in chunk:
                await session.execute(
                    _INSERT_PAPER_EXTRACTION,
                    {"paper_id": paper.id, "model": f"{exc.model}:unparseable", "n": 0},
                )
            await session.commit()
            n_papers += len(chunk)
            continue
        await _log_llm_usage(
            session, model=batch.model, input_tokens=batch.input_tokens,
            output_tokens=batch.output_tokens, est_cost_usd=batch.est_cost_usd,
            purpose="paper_extraction",
        )
        for paper, claims in zip(chunk, batch.claims_by_paper, strict=True):
            if claims is None:
                marker, n = f"{batch.model}:unparseable", 0
            else:
                to_link.extend(await _store_claims(session, paper.id, claims, batch.model))
                marker, n = batch.model, len(claims)
                n_claims += n
            await session.execute(
                _INSERT_PAPER_EXTRACTION, {"paper_id": paper.id, "model": marker, "n": n}
            )
        await session.commit()
        n_papers += len(chunk)

    for ref, concepts, paper_id in to_link:
        if await current_tier(session) == "halted":
            break
        n_links += await _link_claim(session, client, ref, concepts, paper_id)
    return n_papers, n_claims, n_links


async def _run_llm_hypothesis_step(
    session: AsyncSession, *, client: _AnthropicClientProtocol
) -> str | None:
    """One bounded LLM hypothesis per research cycle, gated by budget.
    current_tier(). Deterministic generation (grid + evolution, see
    _run_research below) is completely separate code and is never gated
    on this -- a halted LLM budget stops exactly this function, nothing
    else. Returns the enqueued run_backtest job id, or None if halted, no
    papers are available yet, or the LLM's response failed StrategySpec
    validation (an honest 'no hypothesis this cycle', not a crashed
    worker cycle).

    I3: a response that fails validation was still BILLED, so its
    llm_usage row is written and committed on the failure path too --
    otherwise the monthly cap systematically under-counts exactly the
    spend that produced nothing."""
    tier = await current_tier(session)
    if tier == "halted":
        return None

    claim = await _next_untested_claim(session)
    if claim is None:
        return None

    model = model_for_tier(tier)
    try:
        result = await generate_hypothesis(
            client, model, claim.symbol, _TIMEFRAME, [claim.paper]
        )
    except LLMResponseError as exc:
        await _log_llm_usage(
            session,
            model=exc.model,
            input_tokens=exc.input_tokens,
            output_tokens=exc.output_tokens,
            est_cost_usd=estimate_cost(
                exc.model, input_tokens=exc.input_tokens, output_tokens=exc.output_tokens
            ),
        )
        # Record the attempt so the same claim isn't re-billed every cycle.
        await session.execute(
            _INSERT_LLM_HYPOTHESIS,
            {
                "strategy_fingerprint": "unparseable",
                "paper_ids": [claim.paper.paper_id],
                "claim_ids": [claim.claim_id],
                "hypothesis_text": f"unparseable response: {exc}",
                "expected_effect": "",
                "model": exc.model,
                "input_tokens": exc.input_tokens,
                "output_tokens": exc.output_tokens,
                "est_cost_usd": estimate_cost(
                    exc.model, input_tokens=exc.input_tokens, output_tokens=exc.output_tokens
                ),
            },
        )
        await session.commit()
        print(f"worker: LLM hypothesis generation produced an invalid spec, skipping: {exc}")
        return None
    except ValueError as exc:
        # A ValueError raised BEFORE the API call billed anything (an
        # unpriced model, say) -- nothing to log, nothing was spent.
        print(f"worker: LLM hypothesis generation failed before any spend, skipping: {exc}")
        return None

    await _log_llm_usage(
        session,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        est_cost_usd=result.est_cost_usd,
    )
    await session.execute(
        _INSERT_LLM_HYPOTHESIS,
        {
            "strategy_fingerprint": result.spec.config_hash(),
            "paper_ids": result.paper_ids,
            "claim_ids": [claim.claim_id],
            "hypothesis_text": result.hypothesis_text,
            "expected_effect": result.expected_effect,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "est_cost_usd": result.est_cost_usd,
        },
    )

    return await _enqueue_child(
        session,
        child=result.spec,
        parent_experiment_id=None,
        hypothesis=result.hypothesis_text,
        change_set={
            "mutation_type": "LLM_HYPOTHESIS",
            "field": "family",
            "old_value": None,
            "new_value": result.spec.family,
        },
        expected_information_value_=0.0,
    )


_SELECT_STRATEGY_FILLED_ORDER_IDS = text(
    "SELECT id FROM paper_orders WHERE strategy_id = :strategy_id AND status = 'FILLED'"
)


_INSERT_PAPER_MARK = text(
    "INSERT INTO paper_marks (symbol, close, bar_available_at) "
    "VALUES (:symbol, :close, :bar_available_at)"
)


def paper_decision_bars(
    history: PointInTimeFrame, forward: PointInTimeFrame, cutoff: datetime
) -> pl.DataFrame:
    """Pre-holdout history plus the holdout-period bars paper trading reads
    via access_holdout_for_paper, as one frame in as_of()'s own order.
    Disjoint by construction: ingestion splits the two on event_time."""
    return pl.concat([history.as_of(cutoff), forward.as_of(cutoff)]).sort(
        ["symbol", "available_at"]
    )


async def _run_paper() -> None:
    """Every champion, every tick: poll fills, reconcile, check
    divergence. Trading decisions (decide_and_submit) only actually
    submit when a new 1d bar makes the target position differ from the
    current one -- see paper/execution.py's own idempotency, not a
    separate "is a new bar due" check here.

    The champions query runs BEFORE constructing PaperBroker(), and this
    is a no-op if it's empty -- PAPER_API_KEY/PAPER_API_SECRET (required
    by PaperBroker.__init__) must only be set once paper trading has an
    actual CHAMPION to trade, not from day one of the tightened */15
    cron before any strategy has ever reached CHAMPION status.

    Divergence is checked against a strategy's WHOLE FILLED order
    history (queried by strategy_id), not just the ids poll_fills()
    happened to fill THIS tick: decide_and_submit submits at most one
    order per strategy per tick, so a single-tick delta list has length
    0 or 1 and check_divergence's materiality test
    (divergence._is_material) requires >=2 observations to have a
    variance to test at all -- with only this tick's deltas, divergence
    could never fire in production. Querying by strategy_id directly
    also avoids cross-attributing another champion's fill to this one
    when two champions share a symbol (poll_fills() itself is correctly
    scoped by symbol only, since it is just updating fill status against
    the exchange -- the attribution fix belongs here, in which deltas
    get reconciled and handed to which strategy_id).

    I9 (final-review fix wave): each champion's body is wrapped in its
    own try/except -- one champion's failure (a ccxt error, a bad
    historical row, anything) must not stop the others from being
    processed this tick. run_once() itself also isolates this whole
    concern, but that alone would still mean champion #1's exception
    prevents champions #2..N from ever being polled/reconciled this
    tick; this is a second, per-champion layer."""
    as_of_cutoff = datetime.now(UTC)

    async with get_session() as session:
        champions = (
            await session.execute(
                text("SELECT id, family, spec FROM strategies WHERE status = 'CHAMPION'")
            )
        ).fetchall()

    # C1 (final-review fix wave): a rotation strategy can hold CHAMPION
    # status (validate_rotation_specs calls elect_champions like every
    # other validation path), but live paper-trading execution for
    # rotation strategies is explicitly out of scope for this pass (see
    # docs/superpowers/specs/2026-09-21-cross-sectional-rotation-design.md's
    # own "Explicitly out of scope" section) -- there is no multi-leg
    # decide_and_submit. Skipped explicitly here rather than left to
    # raise ValidationError into the per-champion try/except below:
    # throw-and-catch on every champion on every tick is not a skip, it
    # is a silent, recurring error masquerading as one.
    champions = [row for row in champions if row.family not in ROTATION_FAMILIES]

    if not champions:
        return

    # Binance testnet when its credentials are configured; otherwise the
    # internal simulated broker (paper/sim_broker.py) -- paper trading must
    # not sit idle just because no exchange sandbox account exists.
    broker: PaperBroker | SimBroker = (
        PaperBroker()
        if os.environ.get("PAPER_API_KEY") and os.environ.get("PAPER_API_SECRET")
        else SimBroker()
    )
    for row in champions:
        try:
            spec = StrategySpec.model_validate(row.spec)
            async with get_session() as session:
                pit, _data_version_hash = await load_point_in_time(
                    session,
                    [spec.symbol],
                    spec.timeframe,
                    as_of_cutoff - timedelta(days=_GRID_LOOKBACK_DAYS),
                    as_of_cutoff,
                )
                # Every bar since holdout_start lives in the holdout vault;
                # without it paper trading decides on prices frozen at that
                # date. Logged read, not a validation access (user decision
                # 2026-09-25, docs/DECISIONS.md).
                forward = await access_holdout_for_paper(session, spec, row.id)
                await session.commit()
                bars = paper_decision_bars(pit, forward, as_of_cutoff)
                if bars.height == 0:
                    continue

                await decide_and_submit(
                    session, broker, strategy_id=row.id, spec=spec, bars=bars
                )
                await poll_fills(session, broker, symbol=spec.symbol)

                strategy_order_ids = (
                    await session.execute(
                        _SELECT_STRATEGY_FILLED_ORDER_IDS, {"strategy_id": row.id}
                    )
                ).scalars().all()
                deltas = []
                for order_id in strategy_order_ids:
                    delta = await reconcile_order(session, order_id=order_id)
                    if delta is not None:
                        deltas.append(delta)
                if deltas:
                    await check_divergence(
                        session, strategy_id=row.id, reconciliation_deltas=deltas
                    )

                current_price = float(bars.tail(1)["close"][0])
                await session.execute(
                    _INSERT_PAPER_MARK,
                    {
                        "symbol": spec.symbol,
                        "close": current_price,
                        "bar_available_at": bars.tail(1)["available_at"][0],
                    },
                )
                await session.commit()
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
        except Exception as exc:
            record_failure("paper", exc, context=f"strategy_id={row.id}")
            continue


async def run_once() -> list[str]:
    # I7 (final-review fix wave): runs unconditionally, every tick,
    # regardless of which of the three cadence-gated concerns below are
    # due this wake -- previously this lived inside _run_ingest() (hourly
    # gated), so a stale claim could wait up to an hour even though
    # research's drain_queue (every 30 min) could otherwise have picked
    # up the reclaimed job sooner. One cheap query per tick guarantees a
    # stale claim never waits longer than one cron interval (15 min).
    try:
        settings = get_queue_settings()
        async with get_session() as session:
            reaped = await reap_stale_claims(
                session, stale_after_seconds=settings.JOB_HEARTBEAT_TIMEOUT_SECONDS
            )
            await session.commit()
        if reaped:
            print(f"worker: reclaimed {len(reaped)} stale claim(s): {reaped}")
    except Exception as exc:  # I9: one concern's failure must not sink the tick
        record_failure("reap_stale_claims", exc)

    cycle_started_at = datetime.now(UTC)

    try:
        await _run_one_time_backfills()
    except Exception as exc:
        record_failure("backfill", exc)

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
        llm_ingestion_due = await is_due(
            session, concern="llm_ingestion", interval_seconds=_LLM_INGESTION_INTERVAL_SECONDS
        )
        ablation_due = await is_due(
            session, concern="ablation", interval_seconds=_ABLATION_INTERVAL_SECONDS
        )

    # I9 (final-review fix wave): each concern is isolated in its own
    # try/except -- previously any single exception (a ccxt error from
    # _run_paper, say) killed the entire tick, including concerns that
    # hadn't run yet. mark_run still only fires on that concern's own
    # success, unchanged: a crashed concern is retried next wake, but no
    # longer takes the other two concerns down with it.
    if ingest_due:
        try:
            await _run_ingest()
            async with get_session() as session:
                await mark_run(session, concern="ingest")
        except Exception as exc:
            record_failure("ingest", exc)

    if research_due:
        try:
            ran = await _run_research()
            async with get_session() as session:
                await mark_run(session, concern="research")
        except Exception as exc:
            record_failure("research", exc)

    if paper_due:
        try:
            await _run_paper()
            async with get_session() as session:
                await mark_run(session, concern="paper")
        except Exception as exc:
            record_failure("paper", exc)

    if llm_ingestion_due:
        try:
            ingested = await _run_llm_ingestion()
            async with get_session() as session:
                await mark_run(session, concern="llm_ingestion")
            if ingested:
                print(f"worker: ingested {len(ingested)} paper(s)")
        except Exception as exc:
            record_failure("llm_ingestion", exc)
        # Knowledge extraction runs after ingestion on the same cadence but
        # fails independently: a bad LLM call must not stop papers arriving.
        try:
            async with get_research_session() as session:
                papers, claims, links = await _run_paper_knowledge(
                    session, client=_anthropic_client()
                )
            print(
                f"worker: paper knowledge -- {papers} paper(s) extracted, "
                f"{claims} claim(s), {links} cross-paper link(s)"
            )
        except Exception as exc:
            record_failure("paper_knowledge", exc)

    if ablation_due:
        try:
            verdicts = await _run_ablation()
            async with get_session() as session:
                await mark_run(session, concern="ablation")
            if verdicts:
                print(f"worker: ablation verdicts: {verdicts}")
        except Exception as exc:
            record_failure("ablation", exc)

    # Step 4's minimal monitoring: persist this cycle's failure tally
    # (empty -> no rows, no-op) and alert on any exception type that
    # crossed the threshold -- unconditional, so a cycle that failed
    # entirely (e.g. every concern's is_due check itself raised) still
    # gets whatever was recorded flushed rather than losing it silently.
    try:
        async with get_session() as session:
            flushed = await flush_cycle(session, cycle_started_at=cycle_started_at)
            await session.commit()
        alert_discord_for_threshold_breaches(flushed)
    except Exception as exc:
        print(f"worker: flush_cycle failed (failure tally lost this cycle): {exc!r}")

    return ran


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained/validated {len(ran)} experiment(s): {ran}")


if __name__ == "__main__":
    main()

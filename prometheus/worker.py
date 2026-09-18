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

Now four concerns run at four different rates from this ONE entrypoint,
gated by worker_cadence (is_due/mark_run below): ingest hourly, research
(today's grid/validate/evolve pipeline, unchanged logic) every 30
minutes, paper trading every tick, and (6) PROMPT 9's llm_ingestion
daily -- an arXiv search plus PDF/GROBID extraction into
research_papers, coarser than the other three because papers don't
appear faster than that and the extraction is comparatively expensive.
The research cycle itself also now carries (7) one bounded, budget-gated
LLM hypothesis step, which enqueues its candidate through the SAME
queue.enqueue() path as grid and evolution children and is isolated so
its failure can never sink the deterministic work around it. The Railway
cron interval itself tightens from */30 to */15 (the finest of the four
rates) so the paper concern's tick actually happens on schedule -- still
one scheduled worker, not a second service.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
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
from prometheus.research.llm.budget import current_tier, estimate_cost, model_for_tier
from prometheus.research.llm.hypothesis import (
    LLMResponseError,
    PaperContext,
    _AnthropicClientProtocol,
    generate_hypothesis,
)
from prometheus.research.llm.ingestion import ingest_paper, search_arxiv
from prometheus.research.mutations import parameter_tune, swap_family
from prometheus.research.population import (
    select_for_cross_breeding,
    select_for_exploitation,
    select_for_exploration,
)
from prometheus.research.prioritisation import ParentContext, expected_information_value
from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.spec import FAMILIES, StrategySpec


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

# One bounded LLM hypothesis per research cycle -- same "bounded work per
# tick" reasoning as _EVOLUTION_EXPLOITATION_PARENTS/_EVOLUTION_EXPLORATION_
# PARENTS above, not a statistical choice. Fixed arXiv category filter
# (Quantitative Finance), never a query derived from strategy state --
# ingestion must not depend on research outcomes.
_LLM_ARXIV_QUERY = "cat:q-fin.*"
_LLM_RECENT_PAPERS_LIMIT = 3
_LLM_SYMBOL = "BTC/USDT"
_LLM_INGESTION_MAX_RESULTS = 5

# Ingestion (PDF download + GROBID call) is comparatively expensive and
# papers don't change fast enough to justify checking every 30-min
# research cycle -- a separate, coarser worker_cadence concern, same
# "different concerns, different rates from one entrypoint" pattern
# ingest/research/paper already use. Daily, not weekly: arXiv publishes
# new quant-finance papers daily, and a $0-idle scale-to-zero GROBID
# service means checking daily costs nothing when there's nothing new.
_LLM_INGESTION_INTERVAL_SECONDS = 86400.0  # daily

_INGEST_INTERVAL_SECONDS = 3600.0  # hourly
_RESEARCH_INTERVAL_SECONDS = 1800.0  # 30 min
_PAPER_INTERVAL_SECONDS = 900.0  # 15 min -- also the new cron tick itself

# mark_run stamps last_run_at at the END of a concern's own work, and each
# interval constant above exactly equals its own tick period -- without
# slack, a concern's nonzero runtime means `elapsed` at the next tick is
# always slightly under interval_seconds, is_due returns False that tick
# and True the tick after, and the cadence silently averages out to
# roughly DOUBLE what's intended (paper ~30min not 15, etc). 0.9 absorbs
# a concern's own runtime (up to 10% of its interval) while still keeping
# the crash-retry semantics: a crashed tick that never called mark_run
# leaves last_run_at unchanged, so `elapsed` keeps growing every wake
# regardless of this factor and the concern stays due.
_CADENCE_SLACK_FACTOR = 0.9

_SELECT_CADENCE = text("SELECT last_run_at FROM worker_cadence WHERE concern = :concern")
_UPSERT_CADENCE = text(
    """
    INSERT INTO worker_cadence (concern, last_run_at) VALUES (:concern, now())
    ON CONFLICT (concern) DO UPDATE SET last_run_at = now()
    """
)


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


async def _run_llm_ingestion() -> list[str]:
    """The daily-cadence concern that actually populates research_papers
    -- without this, ingestion.py has no production caller and
    research_papers stays empty forever, starving
    _run_llm_hypothesis_step of any context to work with. Fixed arXiv
    category query, never derived from strategy/research state (see
    ingestion.search_arxiv's own docstring). ingest_paper is idempotent
    on arxiv_id, so re-discovering an already-ingested paper in a later
    search is a safe no-op, not a duplicate.

    Takes no session parameter and manages its own -- same shape as
    _run_ingest() above (backfill() manages its own session
    internally), not _run_research()/_run_paper()'s shape (which open
    their own sessions per internal step). One session for this whole
    concern is enough: ingestion has no cross-step state that needs
    isolating the way research's grid/validate/evolve steps do."""
    candidates = await search_arxiv(_LLM_ARXIV_QUERY, _LLM_INGESTION_MAX_RESULTS)
    ingested: list[str] = []
    async with get_session() as session:
        for candidate in candidates:
            paper = await ingest_paper(session, candidate.arxiv_id)
            ingested.append(paper.arxiv_id)
        await session.commit()
    return ingested


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
            llm_job_id = await _run_llm_hypothesis_step(session, client=_anthropic_client())
            await session.commit()
            if llm_job_id is not None:
                print(f"worker: enqueued LLM hypothesis job: {llm_job_id}")
        except Exception as exc:
            print(f"worker: LLM hypothesis step failed: {exc!r}")
    if evolved_job_ids:
        print(f"worker: enqueued {len(evolved_job_ids)} evolved candidate(s): {evolved_job_ids}")

    return ran + validated


_SELECT_RECENT_PAPERS = text(
    "SELECT id, key_sections FROM research_papers ORDER BY ingested_at DESC LIMIT :limit"
)


async def _select_recent_papers(session: AsyncSession, limit: int) -> list[PaperContext]:
    rows = (await session.execute(_SELECT_RECENT_PAPERS, {"limit": limit})).fetchall()
    return [PaperContext(paper_id=r.id, key_sections=r.key_sections) for r in rows]


_INSERT_LLM_USAGE = text(
    """
    INSERT INTO llm_usage (model, input_tokens, output_tokens, est_cost_usd, purpose)
    VALUES (:model, :input_tokens, :output_tokens, :est_cost_usd, :purpose)
    """
)
_INSERT_LLM_HYPOTHESIS = text(
    """
    INSERT INTO llm_hypotheses
        (strategy_fingerprint, paper_ids, hypothesis_text, expected_effect,
         model, input_tokens, output_tokens, est_cost_usd)
    VALUES
        (:strategy_fingerprint, :paper_ids, :hypothesis_text, :expected_effect,
         :model, :input_tokens, :output_tokens, :est_cost_usd)
    """
).bindparams(bindparam("paper_ids", type_=JSONB))


async def _log_llm_usage(
    session: AsyncSession,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    est_cost_usd: float,
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
            "purpose": "hypothesis_generation",
        },
    )
    await session.commit()


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

    papers = await _select_recent_papers(session, _LLM_RECENT_PAPERS_LIMIT)
    if not papers:
        return None

    model = model_for_tier(tier)
    try:
        result = await generate_hypothesis(client, model, _LLM_SYMBOL, _TIMEFRAME, papers)
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
                text("SELECT id, spec FROM strategies WHERE status = 'CHAMPION'")
            )
        ).fetchall()

    if not champions:
        return

    broker = PaperBroker()
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
                bars = pit.as_of(as_of_cutoff)
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
            print(f"worker: paper concern failed for strategy {row.id}: {exc!r}")
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
        print(f"worker: reap_stale_claims failed: {exc!r}")

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
            print(f"worker: ingest concern failed: {exc!r}")

    if research_due:
        try:
            ran = await _run_research()
            async with get_session() as session:
                await mark_run(session, concern="research")
        except Exception as exc:
            print(f"worker: research concern failed: {exc!r}")

    if paper_due:
        try:
            await _run_paper()
            async with get_session() as session:
                await mark_run(session, concern="paper")
        except Exception as exc:
            print(f"worker: paper concern failed: {exc!r}")

    if llm_ingestion_due:
        try:
            ingested = await _run_llm_ingestion()
            async with get_session() as session:
                await mark_run(session, concern="llm_ingestion")
            if ingested:
                print(f"worker: ingested {len(ingested)} paper(s): {ingested}")
        except Exception as exc:
            print(f"worker: llm_ingestion concern failed: {exc!r}")

    return ran


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained/validated {len(ran)} experiment(s): {ran}")


if __name__ == "__main__":
    main()

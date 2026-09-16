"""Scheduled worker entrypoint. PROMPTS.md PROMPT 7's "THE WORKER": wakes
on a cron schedule (Railway), does one bounded pass, exits -- not an
always-on process. CLAUDE.md's cost discipline: two always-on services
(api, postgres) plus one scheduled worker, not a third always-on process.

Each cycle: (1) an idempotent ingestion catch-up for a short recent
window, (2) enqueues the deterministic grid for every symbol in the real
universe (idempotent by config_hash+days -- a symbol's grid runs ONCE,
not every cycle, see experiments.runner.enqueue_grid), (3) drains
whatever's pending.

What this does NOT do, and why: it does not generate new strategies each
cycle -- research/mutations.py (Prompt 7's evolution loop) doesn't exist
yet (docs/DEFERRED.md). "Live" here means ohlcv_bars/benchmark_equity
genuinely growing every cycle, and the deterministic grid genuinely
having run once across the real universe -- not a strategy population
that evolves generation over generation yet.
"""
from __future__ import annotations

import asyncio

from prometheus.core.db import get_session
from prometheus.data.ingestion import backfill, load_universe_symbols
from prometheus.experiments.queue import get_queue_settings, reap_stale_claims
from prometheus.experiments.runner import drain_queue, enqueue_grid

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

    for symbol in load_universe_symbols():
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

    return await drain_queue()


def main() -> None:
    ran = asyncio.run(run_once())
    print(f"worker: drained {len(ran)} experiment(s): {ran}")


if __name__ == "__main__":
    main()

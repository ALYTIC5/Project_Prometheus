"""worker.py's four concern cadences, as a standalone module -- extracted
so the API service can report worker status (GET /pipeline/) without
importing worker.py itself, which pulls in ccxt, anthropic, and the paper
broker's full dependency graph at module load time. worker.py imports
these from here rather than defining its own copy, so the two can never
drift.
"""
from __future__ import annotations

LLM_INGESTION_INTERVAL_SECONDS = 86400.0  # daily
INGEST_INTERVAL_SECONDS = 3600.0  # hourly
RESEARCH_INTERVAL_SECONDS = 1800.0  # 30 min
PAPER_INTERVAL_SECONDS = 900.0  # 15 min -- also the worker cron tick itself

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
CADENCE_SLACK_FACTOR = 0.9

CONCERN_INTERVALS: dict[str, float] = {
    "ingest": INGEST_INTERVAL_SECONDS,
    "research": RESEARCH_INTERVAL_SECONDS,
    "paper": PAPER_INTERVAL_SECONDS,
    "llm_ingestion": LLM_INGESTION_INTERVAL_SECONDS,
}

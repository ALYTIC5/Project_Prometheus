# Decisions

Operational and cross-cutting decisions that don't fit `DEFERRED.md` (scope
calls) or `DEPENDENCIES.md` (library choices) -- infra behavior, process
notes, things a future session needs to know are true but wouldn't find by
reading the code.

---

## Railway cron schedule is a manual, dashboard-only setting (2026-09-24)

`prometheus-worker`'s cron schedule is configured in the Railway
dashboard/CLI, not committed to this repo -- confirmed again this session:
`railway service --help`/`railway service update --help` expose no
cron-editing subcommand, matching the 2026-09-17 paper-trading plan's own
finding (`docs/superpowers/plans/2026-09-17-paper-trading.md`, Task 10).

**Found still at `*/30 * * * *`, not the `*/15 * * * *` that plan called
for** -- the paper-trading concern (`_PAPER_INTERVAL_SECONDS = 900.0`, 15
min) has therefore only ever been checked on alternating ticks since it
shipped, roughly halving its real cadence. This is exactly the disconnect
that caused the drift: a code change (`core/cadence.py`) can commit and
deploy cleanly while the operational setting it assumes (the cron
interval) silently stays stale, because nothing ties them together --
tightening the cadence constant does not and cannot tighten the cron that
calls it.

**Action needed (manual, not done by this session):** in the Railway
dashboard, `prometheus-worker` service → Settings → Cron Schedule → change
`*/30 * * * *` to `*/15 * * * *`.

**Trigger for revisiting this note:** if Railway's CLI or API ever exposes
cron-schedule mutation, wire a `railway.json`/`railway.toml` (or an
equivalent committed config) so this class of drift becomes impossible
instead of merely documented.

## The signal-strength contract (2026-09-24)

`validation/metrics.py`'s IC/ICIR computation hardcoded
`pl.col("_fast") - pl.col("_slow")`, a construction only 4 of 47
registered families' `signal_for()` output ever produced. Every other
family raised `ColumnNotFoundError` inside `experiments/runner.py`'s
`validate_grid`, caught by a bare `except Exception: continue` that
discarded the whole row -- including `risk`/`turnover`/`hit_rate`, which
had already computed cleanly. Net effect: ~43 of 47 families never
produced a `VALIDATED` result in production; nothing reached
`elect_champions`; evolution had no real scored parents to mutate from.

Fixed by giving every family a declared (`strategy/spec.py`'s
`EMITS_SIGNAL_STRENGTH`), family-appropriate continuous `_signal_strength`
column, and by making `compute_metrics` independent-per-metric
(`ValidationMetrics.metric_failures`) instead of all-or-nothing --
incomplete evidence now persists as a real row with the failure named,
and `validation/decision.py` refuses `PROMOTE` while `metric_failures` is
non-empty, rather than the whole spec silently vanishing. Full detail:
`tests/test_validation_metrics.py`'s module docstring and the
2026-09-24 session transcript.

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

## Law 8 benchmark: own universe, own post-warm-up window, hard-checked (2026-09-24)

Audit of an Oracle scatter showing every point at one benchmark return
found no shared global benchmark -- the chart simply plotted the latest 200
experiments, which were one or two symbols (98.6% of 441k experiments were
result-less insufficient-data rejects from the retry churn). It did find:

- **Warm-up mismatch.** The benchmark entered on bar 1 of the loaded
  history; a strategy can't hold a position until its declared warm-up
  (`engine.min_bars_for`) is over, so a 200-day SMA was charged ~200 days of
  buy-and-hold it could never have held. Now both the strategy's equity
  curve and its benchmark start at `engine.warmup_start_index(spec)`
  (rotation: the first rebalance date), and `benchmark.assert_benchmark_matches`
  raises `BenchmarkMismatch` if universe or first/last date differ.
  EMA-based families (MACD/TRIX/Keltner/SAR) emit positions before their
  declared warm-up while their indicators are unconverged; those bars are
  no longer counted.
- **Entry cost.** `run_one`'s stored `benchmark_return_pct` measured
  curve[0]→curve[-1], and curve[0] is already net of entry cost -- the
  benchmark was excused its own cost. Now measured from STARTING_CAPITAL.
- **I5.** `benchmark_equity` keyed by date alone (last writer wins across
  universes) -> keyed by (universe_key, date), migration 0018. Pre-existing
  rows are labelled LEGACY_MIXED and ignored.
- `compute_benchmark_curve` takes universe, window_start, window_end and
  cost_model as required arguments -- no defaults for anything Law-8
  defining. `decision.decide` returns CONTINUE_RESEARCH/BENCHMARK_MISMATCH
  first if a result's benchmark doesn't match its strategy.
- Enforced by `tests/laws/test_benchmark_matches_universe.py` across every
  single-asset and rotation family, with decoy symbols in the data.
- Backfill: a one-time worker step (marker `bench_fix_0924`) re-queues every
  already-succeeded backtest job once; re-runs append superseding
  experiment/result rows (Law 6), spread over cycles by the drain budget.

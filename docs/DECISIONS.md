# Decisions

Operational and cross-cutting decisions that don't fit `DEFERRED.md` (scope
calls) or `DEPENDENCIES.md` (library choices) -- infra behavior, process
notes, things a future session needs to know are true but wouldn't find by
reading the code.

---

## The vault is used; pre-gate promotions re-tested; paper loss limits (2026-09-28)

Prompted by `AUDIT_REPORT.md`: nothing had ever been judged on unseen data.

**User decisions.** The vault (bars >= `holdout_start` 2026-09-16) opens
on **2027-03-16** (`config/holdout.yaml` `vault_opens`, six months). Until
then nothing may become VALIDATED or CHAMPION. Each gate discovery then
gets ONE vault test: the strategy runs on research bars (warm-up) + vault
bars, and only the vault part of both curves is scored with the gate's own
one-sided excess-return test at **p < 0.05**. Waiting discoveries stay
PROMISING and are paper-traded, labelled `AWAITING_HOLDOUT (unverified)`.
Every pre-gate CHAMPION/VALIDATED gets its one discovery-gate test now and
goes to PROMISING either way.

**How.**
- `validation/holdout_test.py` (`run_holdout_test`, `holdout_passed`); verdicts
  are append-only in `evaluator.holdout_verdicts` (migration 0029).
- `set_status` refuses VALIDATED *and* CHAMPION without a passed verdict
  (`VALIDATED_WITHOUT_HOLDOUT` violation); `reinstate_champion` likewise.
- `_apply_discovery_gate` returns PROMISING + `AWAITING_HOLDOUT` for a
  discovery without a verdict. Because that is now the first claim of
  success, a canary reaching it is a `CANARY_BREACH`
  (`status.note_discovery`) -- otherwise canaries would have stopped
  testing anything.
- Worker: `_run_holdout_tests` after research (no-op before `vault_opens`);
  one-time `promo_regate_928` (`experiments/regate.py`).
- Paper trading trades `validation/promotion.paper_eligible_strategies`
  (CHAMPIONs + awaiting discoveries, one row per spec, never canaries) and
  flattens any open position that is no longer eligible.
- Paper loss limits (`paper/execution.py`), per strategy against its own
  EUR 1000 account: drawdown from peak >= `MAX_DRAWDOWN_PCT` or loss since
  the UTC day's start >= `MAX_DAILY_LOSS_PCT` forces flat and writes a
  `RISK_*` paper finding once per day. A drawdown breach persists by
  construction (flat equity cannot regain the peak): that strategy is
  halted until a human intervenes. The peak is taken over fill points and
  day starts, not every tick, so it can understate a transient high.
- `tools/ops/worker_now.py run --force X` now only back-dates concerns;
  the next scheduled tick runs them (Railway skips an overlapping scheduled
  tick, but a manually started run was replaced when the next tick began,
  twice on 2026-09-28). `--now` starts one anyway, with a warning.

## ICIR parent fitness, LLM failure refinement, options snapshots (2026-09-28)

**User decisions.** ICIR (consistency) is the parent-selection fitness only
-- verdicts, the discovery gate and promotion are unchanged (no Law 7
change). Failure feedback is LLM refinement that must earn its place by
ablation. Options: 11 SPDR sector ETFs + SPY + QQQ, daily per-expiry
aggregates, no raw chains.

**ICIR.** `breedable_scores` gains `icir` (migration 0028); exploitation and
crossover parents are ordered `icir DESC NULLS LAST, score DESC`. Families
with no continuous signal (6 breakout/regime families) have no ICIR and
rank after, by score. Ablation component `icir_parent_fitness`: two
evolution runs from the same grid and seed, parents from the top half by
ICIR vs by return; judged on return like every other component (known
limitation: it does not measure consistency itself).

**Refinement.** `research/llm/refinement.py` gets one failed strategy's
evidence from the canary-free `breedable_evidence` view (verdict, reason
codes, ICIR, IC by horizon, excess return/Sharpe, PBO, DSR -- never the
discovery-gate payload) and returns a revised parameter point of the SAME
family with a stated prior. Parent = highest ICIR (then score) among
PROMISING/EXPERIMENTAL strategies never refined before;
`llm_hypotheses.parent_config_hash` records attempts so none is billed
twice. The child is a Phase 3 hypothesis (`source='llm_refinement'`,
`llm_stated` prior). 1 per research cycle; 0 once the `llm_refinement`
ablation (best refinement child vs best random-mutation child, per
symbol) disables it. Same family, not "same mechanism class": a
refinement tunes the parent, it does not swap ideas.

**Options.** `data/providers/cboe_options.py` reads CBOE's public delayed
chain (`cdn.cboe.com/api/global/delayed_quotes/options/{T}.json`, which
307-redirects some tickers to `cdn-api.cboe.com` -- the client follows
redirects). Worker concern `options`, daily, only from 21:15 UTC (after
the 16:00 ET close in both EDT and EST, plus the 15-min delay) to
midnight UTC. Session date = the underlying's exchange-local last-trade
date, so a weekend fetch dedupes onto Friday via
`UNIQUE(underlying, quote_date, expiry)`. `options_daily` is append-only;
`available_at` = fetch time. Nothing trades on it: there is no free
historical options data, so the "options vs price disagreement" idea can
only be tested on sessions recorded from 2026-09-28 on.
`GET /options/summary`.

**Not changed, flagged.** `validation/scoring.py`'s DSR component is
`deflated_sharpe > 0`, always true for a probability; it inflates the
composite score (now only a tie-breaker for breeding, still the verdict
score). Fixing it changes verdict scores, so it needs a Law 7 corpus
re-evaluation first.

## Phase 3: every backtest is a pre-registered hypothesis (2026-09-28)

**User decisions.** Priors for grid/mutation/crossover are Laplace's rule,
(d+1)/(n+2), over that generator's own gate record; an LLM hypothesis
states its own prior. A near-duplicate is a one-step neighbour (+/-1 int,
+/-5% float, same family + symbol/universe + timeframe) of an
already-registered spec. Near-duplicates and unregistered backtests still
run but are never promotable and never spend alpha-wealth; near-duplicates
enqueue at priority -1 (below every generator's 0).

**How.** `hypotheses` (migration 0027, append-only, research role SELECT +
INSERT) is written by `research/hypotheses.py::register_hypothesis` at the
only two job-creation sites (`runner.enqueue_specs`, `worker._enqueue_child`)
before the job exists. `config_hash` is UNIQUE: the first registration is
the pre-registration, and a later generator proposing the same spec cannot
restate it. Parameters are part of `config_hash`, so a changed parameter is
a new hypothesis and a new gate test -- "no widening after results" holds by
construction. Mechanism: `strategy/mechanisms.py` (every family -> one of 6
classes + one sentence); deterministic generators state their family's, an
LLM hypothesis states the paper claim's and is MECHANISM_MISMATCH when the
spec's class differs from the claim's `family_hint` class.
`_apply_discovery_gate` refuses NOT_PREREGISTERED / NEAR_DUPLICATE /
MECHANISM_MISMATCH before any LORD++ test; the gate payload carries the
hypothesis id and prior for Phase 7.

**Consequences worth knowing.**
- Canary jitter moved from one step to two (+/-2, +/-10%) and a canary may
  not be a one-step neighbour of the grid or another canary; otherwise every
  canary would be a NEAR_DUPLICATE the gate never tests. Canary config
  hashes therefore changed; old registry rows stay (append-only).
- CONSECUTIVE_DOWN's grid (2, 3, 4) is the only baseline grid with one-step
  neighbours: 3 and 4 register as near-duplicates of 2.
- Specs run before 0027 are registered the next time the grid re-enqueues
  them; mutation/crossover children enqueued before 0027 are
  NOT_PREREGISTERED for good.
- Backfill artifact (first prod cycle, 2026-09-28 ~15:40 UTC):
  `hypothesis_gate_stats` counts only tests of already-registered specs, so
  the first grid specs registered saw 0/0 -> prior 0.5, falling toward
  1/(n+2) as the pre-0027 ledger rows' specs got registered. Those rows are
  final (append-only); Phase 7 calibration should exclude registrations
  from that first backfill cycle.
- Not done: return-correlation near-duplicates (needs stored return
  streams), scoring the stored priors (Phase 7).

## Phase 2: LORD++ discovery gate replaces a guard that did nothing (2026-09-28)

**What was wrong.** `decide()` promoted when `deflated_sharpe > 0`, but DSR
is `Phi(z)` -- a probability in (0,1) -- so the check passed whenever DSR was
computed. Separately, the Sharpe fed to PSR/DSR was annualised (cpz-quant,
x sqrt(252)) while PSR also scales by sqrt(n_bars), inflating z ~16x. Every
VALIDATED/CHAMPION before this date was promoted with no effective
multiple-testing control -- which is why canaries got through.

**What replaces it.**
- PROMOTE from `decide()` is a candidate only. The LORD++ gate (Ramdas et al.
  2017, default gamma sequence) decides discoveries at alpha = 5%, W0 = 2.5%
  (user decision). Ledger: `evaluator.alpha_wealth_ledger`, append-only,
  one test per config_hash ever (user decision), non-representative
  cluster members untested.
- p-value: PSR of per-bar EXCESS returns over the strategy's own matched
  buy-and-hold (Law 8), per-period units, vs 0. Not DSR: DSR already
  corrects for trial count and would double-correct.
- DSR stays a reported diagnostic with the units fixed. `scoring.py` still
  has a `dsr > 0` score component, now uninformative; changing a score
  component is a Law 7 corpus experiment -- follow-up, not done here.
- `set_status` refuses VALIDATED without a ledger discovery
  (`VALIDATED_WITHOUT_DISCOVERY` violation) -- Law 10 at the choke point.
- Existing VALIDATED strategies were NOT grandfathered (user decision): each
  gets its one test on its next re-validation; failure demotes to PROMISING.

**Measured.** Simulation (100 streams x 1000 tests, 10% true effects):
realised FDR 0.9% independent, 1.0% at rho 0.3, 0.7% at rho 0.6 (LORD++ is
conservative; ~32 discoveries/1000). The excess-return p-value rejected
5.0% of pure-noise strategies at the 5% level (calibrated). 102 canaries
through the real pipeline: 0 breaches (was 0-3 before the gate).
Correlation here is equicorrelation only; real backtest dependence can be
worse -- FDR control is approximate, not guaranteed.

## Paper knowledge engine (2026-09-26)

- **200 papers/day** (`PAPERS_PER_DAY`, user's number) from arXiv `cat:q-fin.*`
  every 2h. q-fin publishes a few dozen a day, so most of the volume walks the
  backlog. Papers are stored abstract-only; `research_papers` is insert-only,
  so full text is never back-filled onto an existing row.
- Each paper gets one Haiku extraction call (structured claims + concept
  tags); each new claim is compared with claims from other papers sharing a
  concept (typed links: SUPPORTS/CONTRADICTS/EXTENDS/SAME_MECHANISM). All
  four tables are append-only. Every billed call is in `llm_usage` with its
  own purpose; the existing 80%/100% budget tiers apply.
- **Hypotheses test claims, not "the 3 newest papers".** Volume stays at one
  per research cycle until the `llm_generation` ablation verdict is
  VALUABLE; only then does `LLM_HYPOTHESES_PER_CYCLE` apply. User decision
  this session: scale knowledge now, strategy volume only on proof.

## Law 9 evaluator isolation -- what it is and is not (2026-09-26)

- Research role (0024) is a real Postgres boundary for every code path that
  connects as `RESEARCH_DATABASE_URL`: ingestion, claim extraction/linking
  and the LLM hypothesis step. Proven by permission-denied tests.
- **Not a process boundary.** The worker process also holds the superuser
  `DATABASE_URL`, and the evolution step (mutation/crossover) still runs on
  it because it needs lineage lookups on `experiments`. Its population reads
  go through the breeding views, so canaries are excluded, but nothing
  stops that code path reading raw tables. Closing this needs the evaluator
  in a separate service (a cost-budget decision, deferred).

## Canaries (2026-09-26)

- ~5% of each baseline grid (the prompt's rate) gets a salted near-duplicate
  whose signal the evaluator swaps for a known null. `CANARY_SALT` must be
  set wherever grids are enqueued/validated.
- "Promoted past PROMISING" = VALIDATED or CHAMPION, per
  `STRATEGY_STATES`' own ordering (REGIME_SPECIALIST ranks below PROMISING).
- **Open finding, measured before deploy:** 102 canaries through the real
  pipeline on zero-drift synthetic data: 0-3 received a PROMOTE verdict,
  depending on how many trials the database already held (fewer trials,
  weaker DSR deflation). The failures came from symbols whose buy-and-hold
  fell: partly-flat noise "beats" a falling benchmark. The gate refused
  every one, but in production any such breach halts ALL promotions until a
  human runs `validation.status.clear_promotion_halt`. The fix belongs in
  Phase 2 (online FDR discovery gate); no validation threshold was tuned to
  hide it (Law 7).
- The canary kinds lose to costs on average (null-suite z = -15 to -19), the
  same bias `experiments/ablation.py` documents for placebos, so a zero
  false-pass rate is weaker evidence than it sounds.

## Running the worker on demand; cron is settable after all (2026-09-28)

`python -m tools.ops.worker_now run [--force CONCERN ...] [--wait]` starts
the worker now via Railway's GraphQL `deploymentInstanceExecutionCreate`
(the dashboard's cron "run now"), refusing while another execution is
active. `--force` back-dates concerns through `POST /admin/worker/force`
(`ADMIN_TOKEN` on the API service). `status` lists recent executions and
concern timestamps. The note below is superseded: `serviceInstanceUpdate`
sets `cronSchedule`, and the worker now runs `*/15 * * * *` as the
paper-trading plan intended.

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

## Keyless ETF data, internal paper broker, bar revisions (2026-09-25)

**ETF data: Yahoo v8 chart endpoint** (`prometheus/data/providers/yahoo.py`),
chosen because the user asked for free, keyless data instead of an Alpaca
signup. Stooq is keyless but serves only dividend+split-*adjusted* history
(adjustments use future corporate actions: a Law 1 leak). Alpha Vantage,
Tiingo, EODHD and Finnhub all need a key. Yahoo's OHLC is split-adjusted in
place, so the adapter reverses splits using Yahoo's own split events and
stores raw traded prices. Limits: it's an unofficial endpoint (it can
rate-limit or change shape), and it isn't survivorship-safe. That's
acceptable because the ETF universe is a fixed list whose Law 2 listing
dates come from `config/universe_etf.yaml`.

**Paper trading: internal SimBroker** (`prometheus/paper/sim_broker.py`),
used whenever `PAPER_API_KEY`/`PAPER_API_SECRET` are unset. It makes no
network calls, so Law 5 holds by construction. It fills at the decision
close ± `slippage_bps`, and reconciliation charges `taker_fee_bps` per fill.
That's the same cost model as the backtest engine. It is an honest forward
test on unseen data, not a test of exchange execution: backtest-vs-paper
divergence reads ~zero by construction.

**Bar availability and revisions (Law 1 fix).** `event_time` is a candle's
OPEN, but `available_at` was open + 5 min. A daily close was therefore
labelled knowable ~24h early. Ingestion also stored the still-open candle,
and `ON CONFLICT DO NOTHING` froze it (BTC 2026-09-24: stored 84,430.46 vs
real 84,411.53). The fix:
- `available_at` = close + 5 min (migration 0021 relabels existing rows).
- Unclosed candles are never stored.
- A changed closed candle becomes a new `revision` with `available_at = now`.
- `as_of` returns the latest revision visible at the cutoff.

Test: `tests/laws/test_bar_revisions_point_in_time.py`.

## Paper trading reads the holdout, logged, outside the one-touch rule (2026-09-25)

**User decision.** `config/holdout.yaml` defines the holdout as forward-looking:
every bar at or after 2026-09-16 goes into the vault. Paper trading read only
`ohlcv_bars`, so it decided on prices frozen at that date. The first simulated
TRX order was priced at 0.3354 when the latest close was 0.3403.

The fix is `validation.holdout.access_holdout_for_paper`, which:
- logs every read to `holdout_access_log` with `detail.kind = "PAPER"`;
- is never denied;
- is excluded from the one-validation-access check, so a strategy's single
  validation read is still enforced exactly as before
  (`tests/laws/test_holdout_paper_reads.py`).

Paper results never feed validation or promotion. Their only effect is
quarantine on divergence. The cost is roughly one log row per champion per
worker tick.

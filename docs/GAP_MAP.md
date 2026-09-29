# Gap map: docs/BUILD_PLAN.md against the code (written in P0, 2026-09-29)

For each prompt P1-P14: the files it will touch, what already exists, and
conflicts I foresee. The last section lists what `BUILD_PLAN.md` gets wrong
about the code. The plan was written against the audit's commit `70a8e96`;
`main` is now `12d54dd` (2026-09-28), plus the P0 PRs.

## Work shipped after the audit that the plan does not know about

Commit `12d54dd` (2026-09-28, "one-shot vault test, pre-gate promotions
re-tested, paper loss limits"), deployed to production:

- **Vault test exists.** `prometheus/validation/holdout_test.py`
  (`run_holdout_test`, `holdout_passed`) plus append-only
  `evaluator.holdout_verdicts` (migration 0029).
  - `set_status` refuses VALIDATED **and** CHAMPION without a passed verdict.
  - `config/holdout.yaml` has `vault_opens: 2027-03-16` (= epoch 1's evaluation date).
- **Gate discoveries wait for the vault.** They become PROMISING +
  `AWAITING_HOLDOUT`; a canary reaching a discovery is a `CANARY_BREACH`
  (`validation/status.note_discovery`).
- **Pre-gate re-test already ran in production** (marker `promo_regate_928`,
  2026-09-28 17:16 UTC).
  - Of 28 strategies (CHAMPION + VALIDATED): 26 failed the gate, 2 were
    untestable, 0 discoveries.
  - **All 28 are now PROMISING**; there are no CHAMPIONs.
- **Paper trading.**
  - It trades CHAMPIONs plus `AWAITING_HOLDOUT` discoveries (none today).
  - It flattens any open position no longer eligible; the RANDOM_FOREST
    TRX position was therefore scheduled to be closed.
  - `MAX_DRAWDOWN_PCT` / `MAX_DAILY_LOSS_PCT` are enforced **per strategy**
    (force flat plus a `RISK_*` paper finding), not portfolio-wide.
- **`tools/ops/worker_now.py run --force`** now only back-dates concerns;
  `--now` starts a run.

P0 added (PR #1): `config/search.yaml` + `prometheus/core/search_flags.py`, the
search freeze.

## Per prompt

### P1 Keep it alive and watched
- **Touches:** `prometheus/worker.py` (run_once, concerns),
  `prometheus/core/cadence.py`, `prometheus/core/health.py` (existing
  failure tally, `record_failure`, `flush_cycle`, Discord alert on threshold
  breaches), `api/routes/pipeline.py` (`/pipeline/`: concerns, recent
  failures, job health), `experiments/queue.py` (SKIP LOCKED queue,
  heartbeat, `reap_stale_claims`), `Dockerfile` (`CMD` runs
  `alembic upgrade head` on every start, worker included), `tools/ops/worker_now.py`.
- **Exists:**
  - per-concern cadence (`worker_cadence`) with crash-retry semantics;
  - job heartbeats and stale-claim reaping for queue jobs;
  - `/pipeline/`;
  - the Discord threshold alert (`alert_discord_for_threshold_breaches`).
- **Missing:** `job_runs`, hard timeouts on HTTP/Anthropic calls, per-job
  advisory locks, `/health/summary`, a daily summary, a dead-man's-switch
  ping, `make health`, `make pull-snapshot`.
- **Conflict / evidence for Part A.1:**
  - Twice on 2026-09-28 a manually started run
    (`deploymentInstanceExecutionCreate`) ended exactly when the next
    scheduled tick began (15:45→16:00, 16:18→16:30).
  - Scheduled runs that overlapped nothing completed normally
    (16:00→16:07, 16:30→16:40).
  - So the evidence points at *manual* executions being replaced by the
    scheduled one, not at cron-vs-cron, which Railway skips.
- **Part A.3 / A.4 facts:**
  - The options concern exists (`worker._run_options`, 21:15 UTC window) and
    was never confirmed in production before P0.
  - Exactly 1 `llm_refinement` hypothesis was registered in production on
    2026-09-28 (`/research-health/hypotheses`), so the step does work.

### P2 Risk limits that bite; honest paper accounting
- **Touches:** `prometheus/paper/execution.py` (`check_risk_limits`,
  `breached_limit`, `_clamp_target_qty`, `decide_and_submit`),
  `paper/sim_broker.py`, `paper/reconciliation.py`
  (`compute_paper_equity_curve`), `core/config.py` (`RiskLimits`, env-only),
  `core/protected.py` (P0 loader, not yet authoritative),
  `api/routes/scoreboard.py`, `api/routes/paper.py`,
  `validation/promotion.py` (`paper_eligible_strategies`).
- **Exists:** per-strategy daily-loss and drawdown enforcement (force flat plus
  a finding); KILL_SWITCH; the position cap.
- **Missing:**
  - portfolio-wide daily loss and a gross-exposure cap across strategies;
  - an alert per breach;
  - the admin re-enable route for drawdown halts (today a drawdown halt
    simply persists);
  - `make kill`;
  - next-bar-open fills;
  - env-only-tightens semantics against `config/protected.yaml`.
- **Conflict (needs the owner's decision in P2):**
  - Item 4 wants "the 13 pre-gate CHAMPIONs → LEGACY_UNVERIFIED".
  - Production has **no** CHAMPIONs now: all 28 pre-gate promotions are
    PROMISING after the 2026-09-28 re-test.
  - LEGACY_UNVERIFIED would be applied to those 28 (or to the 13 that were
    champions at some point) by id, recorded append-only.
  - "RANDOM_FOREST-013405 keeps paper trading as a plumbing test": the
    orphan close-out has (by design of `12d54dd`) flattened its position.
    P2 must re-admit it explicitly, labelled "not evidence".
- **Scoreboard contradiction:** still present (`/scoreboard/` computes its
  own state; `/paper/` uses `paper_eligible_strategies`).

### P3 One honest ledger
- **Touches:** `experiments/runner.py` (`run_one`, `validate_specs`),
  `experiments/ablation.py` (its own `run_backtest` calls, including
  `register_icir_parent_fitness_component` and
  `register_llm_refinement_component`, which run hundreds of uncounted
  backtests per day), `experiments/regate.py`,
  `validation/holdout_test.py` (both call `run_backtest` directly),
  `validation/multiple_testing.py` (`trials_to_date` =
  `SELECT COUNT(*) FROM results`), `research/hypotheses.py` (the
  `hypotheses` table already has a canonical `config_hash` and
  `parent_config_hash`).
- **Exists:** `results` (counted trials); `hypotheses` pre-registration (source,
  parent, prior); `experiments.config_hash`; code SHA via
  `core/provenance.code_sha`; `data_version_hash` from `load_point_in_time`.
- **Conflict:** the `run_trial` AST law test must also cover `regate.py`,
  `holdout_test.py` and `paper/execution.py`'s `signal_for` use (paper
  decisions are not backtests; exempt them by name).

### P4 Law 7 first, then fix the score
- **Touches:** `validation/scoring.py` (`_dsr_component`: `dsr > 0`, lines
  52-53), `validation/decision.py` (`_PROMISING_SCORE_FLOOR`, verdict
  logic), `tests/laws/test_threshold_global.py` (xfail stub),
  `tests/test_violations.py` (xfail stub), `api/routes/strategies.py` and
  `clusters.py` (show `score`), frontend sections showing the score.
- **Also affected:** `research/population.py` and `validation/promotion.py`
  order by score (parents are now ICIR-first; election is by score).
- **Conflict:** PBO is computed per validation batch in `runner.validate_specs`
  and stored per strategy row (`validation_results.pbo`).

### P5 Catch cheating by its results
- **Touches:** `backtest/engine.py` (`run_backtest_from_positions`, used by
  `experiments/ablation.py`'s ComponentFn arms, including
  `placebo_component`, so the provenance rule must accommodate ablation
  arms), `backtest/null_signals.py`, `tests/laws/test_no_lookahead.py`,
  `tests/test_backtest_no_lookahead.py`.
- **Exists:** the `.shift(1)` discipline in every family; law tests for
  point-in-time; canaries with null signals.
- **Conflict:**
  - Fill timing moves to the next bar's open. `paper/execution.py` and
    `sim_broker.py` fill at the latest close ± slippage today; P2 changes
    that first.
  - The metrics recompute touches every stored `validation_results` row, via
    new rows (Law 6).

### P6 Honest data: dead coins included
- **Touches:** `config/universe.yaml` (hand-written survivors, every
  `delisted_at: null`), `data/ingestion.py` (`load_universe_symbols` drops
  only delisted rows; ccxt Binance US), `data/universe.py`
  (`membership_windows`, a `universe_membership` table), `data/quality.py`
  (volume-spike quarantine), `data/providers/yahoo.py` (ETFs),
  `data/ingest_macro.py` (FRED), `config/costs.yaml` (flat 10 + 5 bps).
- **Exists:** Law 2 law test (`tests/laws/test_survivorship.py`) over
  `universe_membership`; dated membership windows for ETFs.
- **Conflict:** production ingests crypto from **Binance US** (a 451 geo-block
  on binance.com market data), so the archive-reachability check in item 1
  matters.

### P7 The vault, rebuilt
- **Touches:** `validation/holdout.py` (`access_holdout`, now also
  multi-symbol; `access_holdout_for_paper`), `validation/holdout_test.py`
  (the `12d54dd` one-shot time-vault test, which becomes the time half of
  `vault.py`), `config/holdout.yaml` (hard-protected since P0), migration
  0024/0029, `tests/laws/test_evaluator_isolation.py`,
  `tests/laws/test_holdout_vault.py`.
- **Exists:** time-vault one-shot with a p < 0.05 rule, `evaluator.holdout_verdicts`,
  and `vault_opens`.
- **Conflict:**
  - "Remove or reroute the unused access_holdout": it is no longer unused
    (`holdout_test.run_holdout_test` calls it).
  - The `12d54dd` pass rule (one-sided p < 0.05 vs buy-and-hold) differs from
    the plan's time-vault rule (twins + bootstrap); P7 must supersede it
    through `config/protected.yaml`, not silently.

### P8 Gauntlet v2 and an honest re-run
- **Touches:** `validation/*` (`discovery_gate.py`, `regime.py`, `decay.py`,
  `splits.py`, `decision.py`, `promotion.py`), `research/hypotheses.py`
  (near-duplicate rule: a crude plateau signal), `api/routes/strategies.py`
  (list capped at 500 rows), `world/population.py`.
- **Exists:** decay (IC at 9 horizons), regime classification, CPCV/walk-forward
  IC folds, DSR, PBO, and LORD++ with 102+ tests.
- **Conflict:**
  - The status vocabulary is used by `world/projection.py` and the frontend
    (`stateToVisual.ts`); renaming statuses ripples there.
  - `STRATEGY_STATES` in `research/population.py`.

### P9 Truth tests
- **Touches:** `validation/canaries.py` (5% salted canaries, 3 null kinds),
  `backtest/null_signals.py`, `tests/test_canaries.py` (102-canary acceptance
  test), worker scheduling, the halt machinery in `validation/status.py` (halt
  and clear, `/admin/promotion-halt/clear`).
- **Exists:** null canaries in production (406 registered) and the promotion
  halt/clear routes. Missing: planted edges (power), oracles, the falling
  coin, a nightly job.

### P10 Smarter, cheaper search
- **Touches:** `worker._run_search_steps` (P0), `_run_evolution_step`,
  `_run_llm_refinement_step`, `research/population.py` (ICIR-first parent
  selection since 2026-09-28), `mutations.py`, `crossover.py`,
  `research/llm/refinement.py` and `hypothesis.py`.
- **Blind-prompt conflict:** the prompts show symbols and paper excerpts
  with years today; `refinement.py`'s user prompt includes the symbol.
- **Exists:** ablation components `llm_generation`, `llm_refinement` and
  `icir_parent_fitness` (LLM-vs-random is partly there); stated priors in
  `hypotheses.prior_probability`.

### P11 Options and money flow
- **Touches:** `data/providers/cboe_options.py` (parses full chains, then keeps
  only per-expiry aggregates in `options_daily`, migration 0028),
  `worker._run_options` (21:15 UTC window), `api/routes/options.py`
  (`/options/summary`).
- **Conflict:** the per-contract data is already fetched every day and thrown
  away; storing it is a small change in `_run_options`.

### P12 Forward paper incubation
- **Touches:** `paper/*`, `validation/promotion.paper_eligible_strategies`
  (today: CHAMPION + AWAITING_HOLDOUT), `worker._run_paper`.
- **Conflict:** "Only DISCOVERED and VALIDATED strategies incubate" replaces
  the `AWAITING_HOLDOUT` book from `12d54dd`.

### P13 Dashboard and project commands
- **Touches:** `frontend/src/dashboard/*` (the Strategies section shows score;
  `PaperTradingSection` shows labels since `12d54dd`), `frontend/app/page.tsx`,
  `api/routes/*`, `.claude/skills/` (does not exist yet).

### P14 Independent audit
- **Touches:** read-only everywhere; the verifier agent
  (`.claude/agents/verifier.md`, P0).

## Where BUILD_PLAN.md is wrong or out of date about the code

1. **"13 champions ... are still in the book" (P2, Keep/fix table).** Since
   2026-09-28 17:16 UTC there are none: all 28 pre-gate CHAMPION/VALIDATED
   strategies were re-tested through the gate and set to PROMISING
   (`experiments/regate.py`).
2. **"The one-shot holdout function exists but nothing calls it" (P7).** Since
   `12d54dd`, `validation/holdout_test.run_holdout_test` calls it, from
   `worker._run_holdout_tests` (a no-op until 2027-03-16).
3. **"Daily-loss and drawdown limits are loaded but never enforced" (P2).**
   Since `12d54dd` they are enforced per strategy; portfolio-wide limits
   and gross exposure are still missing.
4. **D9 "Railway skips runs; it doesn't kill them."** True for overlapping
   *scheduled* runs (Railway docs; confirmed: scheduled runs completed). But
   both observed cut-offs involved a *manually started* execution ending the
   moment the next scheduled one began. That is a kill/replacement of manual
   runs, which P1 should confirm rather than assume away.
5. **"AI refinement step ... never been seen working" (P1).** One
   `llm_refinement` hypothesis was registered in production on 2026-09-28.
6. **Risk defaults (P0 item 4).** Production's env limits were stricter than
   the plan's defaults on every limit (5 / 20 / 1 / 2 / 10), so
   `config/protected.yaml` uses those.
7. **The plan cites commit `70a8e96` for file paths.** Paths are still valid,
   but line numbers in `worker.py` and `runner.py` moved.

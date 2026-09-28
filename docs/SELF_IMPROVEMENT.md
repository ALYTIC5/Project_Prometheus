# Self-Improvement Engine

The loop improves the **research process**, not the backtest score. The
measure is **research calibration**: how well past judgements predicted
performance on data that did not exist when the judgement was made. Any change
that raises backtest scores without raising calibration is presumed to be
overfitting. Out-of-sample data arrives at one day per day; nothing here
changes that.

Status legend: DONE / PARTIAL / NOT STARTED. Dates are when the status was
last verified.

---

## Phase 0 -- Audit (DONE, 2026-09-26)

Null suite (1000 seeds, p<0.05) and placebo ablation (NEUTRAL) green in CI;
signal-strength/IC and benchmark-universe fixes in and backfilled
(`bench_fix_0924`). RD-Agent review not done.

## Phase 1 -- Guardrails before growth (DONE, 2026-09-26)

- **Evaluator isolation (Law 9).** Research role `RESEARCH_DB_ROLE` (migration
  0024): no privilege on any judging table, no access to `holdout`/`evaluator`
  schemas; breeding only through `breedable_strategies`/`breedable_scores`.
  Paper ingestion, claim extraction/linking and LLM hypotheses run as that
  role. Enforced by `tests/laws/test_evaluator_isolation.py` (static + real
  permission-denied tests). Gap: the evolution step still uses the superuser
  connection (see `docs/DECISIONS.md`).
- **Single status writer.** `validation/status.py::set_status`; "promoted"
  means VALIDATED or CHAMPION.
- **Canaries.** ~5% of each baseline grid, salted (`CANARY_SALT`), null signal
  swapped in by the evaluator. Breach = refuse + halt all promotions +
  `CANARY_BREACH` violation; only `clear_promotion_halt` (human) resumes.
  `GET /research-health/canaries`.
- Canaries found the pre-gate pipeline promoting noise (2 of ~190, ~1%):
  the old `deflated_sharpe > 0` check was always true. Promotions were
  halted 2026-09-26 -> cleared 2026-09-28 once Phase 2 was live (reason
  logged in `evaluator.promotion_halts`).

## Phase 2 -- Discovery gate, online FDR (DONE, 2026-09-28)

LORD++ (alpha 5%, W0 2.5%) on the PSR p-value of per-bar excess returns vs
the matched buy-and-hold; append-only `evaluator.alpha_wealth_ledger`; one
test per spec ever and per correlation cluster; `set_status` refuses
VALIDATED without a discovery (Law 10, `tests/laws/test_discovery_gate.py`).
Simulated FDR 0.7-1.0% (target 5%); 102-canary acceptance test 0 breaches;
first production cycles: 70 tests, 0 discoveries, no breach. The gate is
strict while nothing has been discovered (next threshold ~1e-5) -- SAFFRON
is the prompt's measured ablation if it proves too conservative.
`GET /research-health/discovery-gate`.

## Phase 3 -- Pre-registered hypotheses (NOT STARTED)

Hypothesis record before its backtest: mechanism, predicted direction/effect/
horizon, frozen parameter ranges, matched benchmark, **generator
prior_probability**. Mechanism-alignment and originality checks. Claims from
the paper knowledge engine (below) are the natural source of mechanisms.

## Phase 4 -- MAP-Elites + islands (NOT STARTED)
## Phase 5 -- Bandit scheduler (NOT STARTED)
## Phase 6 -- Structured memory / KnowledgeFacts (PARTIAL)

Partial substrate exists: `paper_claims`, `claim_concepts`, `claim_links`
(SUPPORTS/CONTRADICTS/EXTENDS/SAME_MECHANISM) and hypothesis provenance
(`llm_hypotheses.claim_ids`). Evaluator-maintained KnowledgeFacts with expiry
and failure constraints are not built.

## Phase 7 -- Research calibration (NOT STARTED)

Forward confirmation record, calibration ledger (Brier, survival rate,
backtest/forward decay, per-generator calibration), meta-validation of rules
corpus-wide only.

**Addition -- Brier skill vs a naive forecaster** (from bennyjo/phil,
Apache-2.0, design only): alongside absolute calibration, report the Brier
score of the system's predicted survival probabilities *relative to* a naive
forecaster that always predicts the historical base rate of VALIDATED
strategies surviving forward. `skill = 1 - Brier_system / Brier_base_rate`.
A system that cannot beat the base rate is not skilled, however calibrated.
Top-level dashboard metric. Needs Phase 3 predictions and forward data.

## Phase 8 -- Retrospection / proxy-reality gap (NOT STARTED)

## Phase 9 -- What the system may change about itself (NOT STARTED)

MAY change automatically (through Phase 7 meta-validation only): bandit
priors and exploration floor, mutation rates, generator weighting, MAP-Elites
resolution, scoring weights, KnowledgeFact status. MAY PROPOSE (human
approval, `docs/proposals/`): new families, data sources, validation rules,
descriptors, code changes. MAY NEVER change: law tests, risk limits, holdout
boundary, alpha-wealth ledger, canary registry, evaluator code, DB roles, the
benchmark definition, this list.

**Additions from bennyjo/phil (Apache-2.0, designs only -- its code targets
prediction markets and is not integrated):**

1. **Self-edit ledger as git commits.** Every automatic change is (a) a row in
   an append-only, evaluator-isolated `self_edit_ledger` and (b) a commit to
   the `research-policy` branch, authored by `research-loop@prometheus.invalid`,
   whose message holds the motivating evidence, the predicted effect on
   calibration, and the review date. No self-edit without a falsifiable
   prediction.
2. **Scheduled retrospective audit.** Each edit gets a review date sized to
   its expected effect (never after a single outcome). At review, compare
   calibration in the window after vs before. Statistical decision, never an
   LLM's: improved beyond noise -> KEEP; no detectable change -> KEEP,
   flagged unproven, re-review; degraded beyond noise -> REVERT by a new
   commit and ledger row restoring the prior values (Law 6). An LLM may
   explain a decision, not make it. Dashboard: **self-edit win rate** -- the
   fraction of the system's own changes that survived review.
3. **CI path protection** -- see "Built now" below.

Items 1-2 are built with Phase 9, when there are real automatic edits to
record and a calibration signal (Phase 7) to judge them. The noise test and
review-window sizing must be decided then, from the data, not invented now.

## Phase 10 -- Research Health dashboard (PARTIAL)

API only so far: `/research-health/canaries`, `/research-papers/summary`,
`/research-papers/learned`. Planned order: calibration over time, Brier skill
vs base rate, forward survival, canary false-pass rate, self-edit win rate,
proxy-reality gap, alpha-wealth, confirmation capacity, bandit arms,
MAP-Elites coverage, knowledge facts, pending proposals.

---

## Built now: CI protected-path guard (2026-09-28)

`tools/ci/check_protected_paths.py`, CI job `protected-paths`. Fails any
commit on `research-policy`, or authored by `research-loop@prometheus.invalid`,
that touches `prometheus/validation/`, `prometheus/experiments/violations.py`,
`prometheus/core/config.py`, `config/holdout.yaml`, `alembic/`, `tests/laws/`,
`CLAUDE.md`, `.github/` or `tools/ci/`. A third layer beside the DB roles and
the law tests. Human commits on other branches are unaffected.

## Paper knowledge engine (supports Phases 3 and 6)

Up to 200 arXiv q-fin papers/day (backlog walk), a one-time seed from the
awesome-systematic-trading list (16 of 61 titles resolvable), a free
relevance gate, 8-paper Haiku extraction batches, typed cross-paper links
for testable claims, and hypotheses built from the most-corroborated
untested claim (one per cycle until the `llm_generation` ablation is
VALUABLE). Details and measured costs in `docs/DECISIONS.md`.

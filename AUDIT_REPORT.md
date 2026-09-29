# Project Prometheus — Audit Report

Audit date: 2026-09-28. Commit audited: `70a8e96` (main). Read-only: no project file was changed to produce this report.

The auditor is the same Claude session that wrote most of the recent commits (Phase 2–3, ICIR/refinement/options). That session reviewed its own work below as critically as the rest, but treat it as a self-audit, not an independent one.

---

## 1. Verdict (plain English)

1. **What it is.** Prometheus is a well-engineered *research lab* that repeatedly generates simple technical-indicator trading strategies for crypto (and some ETFs). It backtests them against buy-and-hold after costs, runs statistical filters, and paper-trades survivors with fake money. It does not trade real money and has no live-broker code.
2. **Evidence of an edge.** None. Its own strict multiple-testing gate has tested 102 strategies and found **0 discoveries**. The only strategy that has actually paper-traded is down 0.15% after three days.
3. **The rankings you can see are not trustworthy.** The dashboard's "top" strategies all share an identical score of 95.385. That score is inflated by a check that always passes, and it is computed on the same data the strategies were chosen on (in-sample).
4. **The single biggest problem.** The "sealed holdout" is **never used to test a strategy**. The one-shot holdout function exists and is tested, but nothing in the pipeline calls it. The holdout itself is only ~12 days old, and the research data has been frozen since 2026-09-15. So nothing has ever been checked on genuinely unseen data, except a few days of paper trading.
5. **Engineering vs. economics.** Engineering quality is high: laws enforced by tests, look-ahead guards, append-only history, canary strategies that catch false positives. The *economics* are weak: a hand-picked survivor crypto universe, no out-of-sample verdict, and 13 "champions" that were promoted by a now-removed broken check and are still paper-trading.

---

## 2. Project map

**Languages:** Python 3.11/3.13 (backend), TypeScript/Next.js 14 + PixiJS (frontend).

**Entry points:**
- API: `uvicorn prometheus.main:app`.
- Worker: `python -m prometheus.worker`, a Railway cron every 15 min.
- Both use the same Docker `CMD`, which runs `alembic upgrade head` first (`Dockerfile`).

**Tooling:**
- `tools/ops/worker_now.py` (force a Railway run), `tools/ci/check_protected_paths.py`, `tools/art/*` (sprite pipeline).
- Makefile: art targets only.
- CI (`.github/workflows/ci.yml`): `protected-paths`, `lint-type-test`, `db-tests`, `laws`.
- `.claude/`: `settings.local.json` and worktrees only. No commands, agents or hooks.
- `CLAUDE.md`: 10 "Laws" plus world/art laws.

**Tree (runtime code, lines of code):**

| Folder | LOC | Purpose |
|---|---|---|
| `prometheus/api` | 1,750 | FastAPI routes (dashboard data, admin) |
| `prometheus/backtest` | 3,784 | custom vectorised engine, 47 families, ML signals, costs, benchmark |
| `prometheus/core` | 1,110 | config, DB models, seeds, cadence |
| `prometheus/data` | 1,875 | ingestion (ccxt/Binance US, Yahoo ETFs, FRED, CBOE options), point-in-time loader |
| `prometheus/experiments` | 3,572 | runner, job queue, ablation harness, lineage, violations |
| `prometheus/research` | 4,031 | grid/ML/rotation generators, mutation/crossover, LLM papers/hypotheses/refinement |
| `prometheus/validation` | 1,784 | metrics, decay, CPCV splits, DSR, PBO, LORD++ gate, canaries, promotion |
| `prometheus/paper` | 856 | paper broker (Binance testnet wrapper + internal SimBroker), execution |
| `prometheus/world` | 1,077 | "pixel world" projection |
| `tests` | 17,768 | 1,160 tests |
| `frontend` | 7,395 | dashboard + pixel world |
| `alembic` | 2,278 | 28 migrations |

**Dependencies (pinned):**

| Area | Libraries |
|---|---|
| Stats | polars 1.44.1, numpy 2.4.6, scipy 1.16.3, **cpz-quant 1.1.0** (PBO, DSR, CPCV, analytics), scikit-learn 1.9.1 |
| Data / exchange | ccxt 4.5.77 |
| HTTP / LLM | httpx 0.27.2, anthropic 1.6.0 |
| Backend | FastAPI, SQLAlchemy 2.0.35, asyncpg, Alembic |
| Frontend | pixi.js 8.1.6, recharts 2.12.7 |

Not used: OpenBB, yfinance (Yahoo is called directly over HTTP), vectorbt, backtrader, alphalens, qlib, RD-Agent, alpaca-py, streamlit.

**Git history:**
- 289 commits, first 2026-09-04, last 2026-09-28.
- The history is 24 days long, and the last 3 days alone added LORD++, pre-registration, canaries, ICIR fitness, LLM refinement and options recording. That is a very fast pace; much of the newest logic has run in production for hours, not weeks.
- 15 most recent commits: see Appendix C.
- 0 TODO/FIXME markers in tracked code.

**Abandoned / clutter (untracked, not in git):**
- `core/`, `data/`, `migrations/` at the repo root: an earlier skeleton of the same project, superseded by `prometheus/`. Dead code.
- `v/`: a stray virtualenv.
- Two empty folders with garbled names (`C:Users...artvox`, `C:Users...tools`) created by a mis-quoted path.
- `Mockups.zip`, `lookAtMe.zip`, `graphify-out/`.

---

## 3. What it actually does (from the code)

| # | Component | Status | Files | How it really works |
|---|---|---|---|---|
| 1 | Data | **Partial** | `data/ingestion.py`, `ingest_etf.py`, `ingest_macro.py`, `loaders.py`, `quality.py`, `config/universe*.yaml` | Daily bars: ~20 crypto pairs via ccxt/Binance US, ETFs via Yahoo's chart endpoint, macro series via FRED. Stored in Postgres with `available_at` = candle close + 5 min, append-only revisions. Hourly ingestion. **The universe is a hand-written list of today's surviving coins** (every `delisted_at: null`, no LUNA/FTT). Every bar ≥ 2026-09-16 goes to `holdout.ohlcv_bars`, so the research dataset stopped growing on 2026-09-15. |
| 2 | Options data | **Partial (started today)** | `data/providers/cboe_options.py`, table `options_daily` | CBOE free delayed chain for 11 sector ETFs + SPY + QQQ. Daily per-expiry aggregates: call/put volume, OI, premium, ATM IV. Deployed 2026-09-28; the first snapshot is due after 21:15 UTC. **Zero history**; there is no free historical options source. |
| 3 | Strategy representation | Exists | `strategy/spec.py`, `rotation_spec.py` | A pydantic `StrategySpec`: one of 47 fixed families + 4 ML families + 13 rotation families, with numeric parameters. No free code. The symbol is supplied by the system; the LLM chooses family + parameters only. It cannot hard-code dates. |
| 4 | Strategy generation | Exists | `research/generate.py`, `ml/generate.py`, `rotation_generate.py`, `mutations.py`, `crossover.py`, `llm/hypothesis.py`, `llm/refinement.py` | A deterministic grid (205 specs/symbol) plus random mutation/crossover. Claude Sonnet 5 (Haiku when the budget is low) turns one paper claim per cycle into a spec, and (new) refines one failed strategy per cycle. Output is JSON validated by the pydantic model; invalid → rejected, still billed and logged. Prompts: Appendix A. |
| 5 | Research ingestion | Exists | `llm/ingestion.py`, `extraction.py`, `linking.py`, `relevance.py`, `seed_lists.py` | Up to 200 arXiv q-fin abstracts/day (plus 16 from awesome-systematic-trading). A regex relevance gate, then Haiku extracts claims (mechanism, horizon, testable, family hint) in batches of 8, then claims are linked (SUPPORTS/CONTRADICTS/…). Prod: 231 papers, 191 claims, 28 testable, 237 links. Abstracts only, no full text. |
| 6 | Backtest engine | Exists (custom) | `backtest/engine.py`, `costs.py`, `benchmark.py` | Vectorised polars. Position for bar *i* is decided from data up to *i−1* (`.shift(1)`), long/flat only, 100% of capital per trade, no shorting, no leverage. Costs: `config/costs.yaml` taker 10 bps + slippage 5 bps per side. The buy-and-hold benchmark of the same universe is charged the same entry cost. |
| 7 | Scoring metrics | Exists, **flawed** | `validation/metrics.py`, `decay.py`, `scoring.py`, `multiple_testing.py` | Computed: Sharpe/drawdown (cpz-quant), turnover, hit rate, IC (Spearman), ICIR over CPCV folds, IC at 9 horizons (1–100 bars), PBO, DSR, excess return/Sharpe vs B&H. The verdict "score" is the mean of four pass/fail components, one of which is `deflated_sharpe > 0`. That is **always true**, because DSR is a probability (`scoring.py:52-53`). Since 2026-09-28 the loop breeds parents by **ICIR**; verdicts still use the composite score. |
| 8 | Improvement loop | Exists | `worker.py::_run_evolution_step`, `_run_llm_refinement_step`, `research/population.py` | Every 30 min: exploitation parents (VALIDATED/CHAMPION, ranked by ICIR) get a ±10–35% parameter tweak or a family swap; the top-2 per family are crossed over; random exploration. The LLM refinement step (deployed today, **not yet observed running in prod**) sends one failed strategy's reason codes + metrics to Claude. Everything is kept in the DB; nothing is deleted (append-only). No generation limit or search-budget stop. |
| 9 | Overfitting defences | Mixed | see table below | |
| 10 | Trial counting | Exists | `multiple_testing.py:180` `SELECT COUNT(*) FROM results`; `evaluator.alpha_wealth_ledger` | Every backtest through the runner writes a `results` row. Experiment IDs have reached ~450,600. That count feeds the DSR's expected-max-Sharpe. Ablation backtests are *not* counted. The LORD++ ledger counts gate tests (102). |
| 11 | Money-flow / divergence | **Missing** | — | Rotation families rank ETFs by price momentum/volatility only. No money-flow or options-vs-price logic; options data only starts recording today. |
| 12 | Paper/live trading | Exists (paper only) | `paper/broker.py`, `sim_broker.py`, `execution.py`, `worker.py` | Champions' latest signal becomes a market order to an internal **SimBroker** (prod has no testnet keys). A Binance **testnet** wrapper refuses to start if any live-sounding env var exists, and asserts "testnet" in its URL (`broker.py:90-111`). `KILL_SWITCH` and a per-position cap are enforced (`execution.py:102-134`). **`MAX_DAILY_LOSS_PCT` and `MAX_DRAWDOWN_PCT` are loaded but never enforced.** No code path to a live venue; `tests/laws/test_no_real_money.py`. |
| 13 | Dashboard | Exists | `frontend/src/dashboard/*`, `app/page.tsx` | A Next.js dashboard (strategies, experiments scatter, benchmark chart, costs, paper trading, papers, queue, laws, violations) plus a PixiJS "pixel world" view. Served by the API service on Railway. |
| 14 | Tests | Exists | `tests/`, `tests/laws/` | Local run on a fresh Postgres: **1,158 passed, 1 skipped, 2 xfailed**. The xfails are `xfail(strict=True)` stubs, including **Law 7 (threshold changes must re-evaluate the corpus) — not implemented** (`tests/laws/test_threshold_global.py`). ruff clean; mypy clean on `core/` + `validation/`. |

**Overfitting defences (item 9):**

| Defence | Status |
|---|---|
| Train/test split | Implemented but **flawed**. CPCV/walk-forward folds (`splits.py`) only measure IC per fold; indicator strategies have no fitted parameters, so parameters are chosen on the full research window. |
| Walk-forward for ML | Correct. Refit on a trailing window; the scaler is fit on train only (`ml_signal.py:85-126`). |
| Sealed holdout | **Flawed / effectively missing.** `holdout.py::access_holdout` is never called by the pipeline (only `access_holdout_for_paper`). The holdout is ~12 days. |
| Deflated Sharpe | Implemented (`multiple_testing.py`). The score uses it incorrectly (always-true check). |
| PBO | Implemented, but **per grid batch**: every strategy for a symbol gets the same PBO (e.g. all ATOM strategies = 0.0923). |
| Online FDR (LORD++, α=5%) | Implemented correctly (`discovery_gate.py`). It is the only thing standing between in-sample noise and VALIDATED. |
| Monte Carlo | Missing (canaries test the pipeline, not each strategy). |
| Parameter neighbourhood / plateau | Partial. A one-step near-duplicate rule since today; no plateau test. |
| Cost stress (2×) | Missing from the pipeline. |
| Regime test | Implemented (`regime.py`, REGIME_SPECIALIST verdict). |
| Canaries (planted null strategies) | Implemented. 406 registered, 2 breaches, both before the gate. |

---

## 4. Red-flag table

| Check | Result | Evidence |
|---|---|---|
| Look-ahead: signal on close[t] traded at close[t] | **PASS (minor caveat)** | Every family ends in `.shift(1)` (`engine.py:125-135` etc.). Caveat: the fill is assumed at close[t−1], the same close the signal saw (a market-on-close assumption); the bar is only "available" 5 min later. Small optimism. |
| `.shift(-n)` in features | **PASS** | Only in the IC forward-return (`metrics.py:132`, correct use) and the ML label (`ml_features.py:55`). Training rows stop at `checkpoint`, whose label is known when predicting (`ml_signal.py:85-88`). |
| Full-sample normalisation | **PASS** | `StandardScaler` fit per training window (`ml_signal.py:121-123`). |
| Point-in-time availability | **PASS** | `available_at` = close + lag; bar revisions; `tests/laws/test_no_lookahead.py`, `test_bar_revisions_point_in_time.py`. |
| Holdout leakage | **PASS (no leakage) / FAIL (no holdout test)** | The research loop never reads ≥ 2026-09-16 bars, but no strategy is ever judged on them (`access_holdout` unused). |
| Missing/zero costs | **PASS** | 10 + 5 bps per side on strategy and benchmark. Doubling costs cut a synthetic MOMENTUM result from +11.6% to +5.0% (Step 5 below). No liquidity/volume constraint. |
| Survivorship bias | **FAIL** | `config/universe.yaml`: today's survivors only; `load_universe_symbols` drops only rows with `delisted_at`, and none are set. Mitigation: each strategy is compared to holding the *same* coin, so the bias inflates both sides. |
| Selection bias | **PARTIAL** | Promotion since 2026-09-28 goes through LORD++ (correct). But the dashboard shows raw best-of-~450k in-sample results. **13 CHAMPIONs were promoted before the gate** by the always-true DSR check and are kept (owner decision). |
| Hard-coded tickers/dates from the LLM | **PASS** | The LLM returns only family + numbers; the symbol comes from the system (`hypothesis.py:271-279`, `refinement.py`). Residual risk: the model may know which parameter values worked historically. |
| Unrealistic fills | **PASS (mostly)** | Breakout levels use `.shift(1)`; fills at close + slippage; no high/low fills. The SimBroker fills instantly at price ± ~5 bps. |
| Metric formula bugs | **FAIL** | (1) `scoring.py:53` `dsr > 0` always true → inflated scores (visible: identical 95.385 tops). (2) PBO is shared per batch, not per strategy. (3) Fixed in Phase 2: DSR fed annualised Sharpe (~16× z-inflation), which is why 13 champions exist. |
| Live-trading path | **PASS** | No live adapter; testnet-only guard; law test. An AI agent editing code could add one, and nothing but review/CI laws prevents that. The CI guard only blocks commits by the research-loop identity, not by a human-driven agent. |
| Secrets in repo / history | **PASS** | No key patterns in the working tree or full git history (Anthropic, AWS, Alpaca PK/AK, GitHub, Discord webhooks). `.env.example` could not be read (local deny rule). **Note:** an Anthropic key (`sk-a****`) was pasted into this chat session; it is not in the repo, but consider rotating it. |
| Risk limits | **FAIL (partial)** | `MAX_DAILY_LOSS_PCT` / `MAX_DRAWDOWN_PCT` defined (`core/config.py:39-40`) but never enforced. No aggregate exposure cap across the 13 champions. |
| Law 7 enforcement | **FAIL** | `tests/laws/test_threshold_global.py` is an `xfail(strict=True)` stub. |

---

## 5. Performance evidence and sanity tests

**Source.** The production Postgres (Railway) is reachable only through the project's own read-only HTTP API; local databases contain test fixtures only. I used GET requests to the project's own API (no broker endpoint). This is a deliberate, disclosed deviation from "no network". Everything else below is local.

**Scale:**
- ~450,600 experiments (backtests) recorded; 4,617 pre-registered hypotheses; 102 LORD++ gate tests, **0 discoveries**.
- Next gate threshold 9.4e-6, alpha-wealth 0.020.
- A 500-row sample of strategies:

  | Status | Count |
  |---|---|
  | REJECTED | 277 |
  | REGIME_SPECIALIST | 110 |
  | PROMISING | 106 |
  | QUARANTINED | 5 |
  | DORMANT | 2 |

- The API also lists **13 CHAMPIONs** (one per family), all promoted before the gate.

**Top 10 by the project's own score.** All are **in-sample**, and none passed the gate.

| Strategy | Symbol | Score | Excess return vs B&H | Excess Sharpe | DSR | PBO |
|---|---|---|---|---|---|---|
| KELTNER_REVERSION-014907 | ATOM | 95.4 | +210.6 pts | 1.78 | 0.037 | 0.092 |
| KELTNER-022560 | ATOM | 95.4 | +87.6 | 0.56 | 0.0001 | 0.092 |
| SMA200_FILTER-003451 | ATOM | 95.4 | +82.4 | 0.56 | 0.0005 | 0.092 |
| MFI-006636 | ATOM | 95.4 | +77.6 | 0.45 | 0.0001 | 0.092 |
| EMA_CROSSOVER-003295 | ATOM | 95.4 | +76.6 | 0.49 | 0.0001 | 0.092 |
| BOLLINGER-023043 | ATOM | 95.4 | +56.5 | 0.13 | 0.00001 | 0.092 |
| TRIPLE_MA_ALIGNMENT-003444 | ATOM | 95.4 | +45.7 | 0.32 | 0.0001 | 0.092 |
| VOL_REGIME_SWITCH-002072 | LTC | 86.0 | +48.9 | 0.37 | 0.011 | 0.210 |
| CONSECUTIVE_DOWN-004973 | LTC | 89.5 | +44.1 | 0.19 | 0.015 | 0.210 |
| KELTNER-022554 | LTC | 89.5 | +28.0 | 0.46 | 0.016 | 0.210 |

Read this table as: the DSRs are near zero (the results are consistent with luck after ~450k trials), yet the score is 95 because the DSR check always passes. The identical PBOs show PBO is per batch. ATOM dominates, which suggests "ATOM fell a lot in the research window, so being flat often beat holding it".

**Paper trading (only real out-of-sample evidence):**
- One champion has traded: RANDOM_FOREST-013405 on TRX/USDT, 2026-09-25 → 2026-09-28, 4 fills.
- Equity €1,000 → **€998.48 (−0.15%)**. TRX buy-and-hold over roughly the same fills: ~−3%.
- Three days is statistically meaningless. It was not compared to SPY (the strategy trades TRX).
- The other 12 champions have no fills.
- The scoreboard shows "NOT_STARTED — just holding" (`system_value: null`) even though a champion is trading, so the scoreboard is inconsistent with the paper section.

**Sanity tests** (throwaway script on synthetic random-walk data, the project's real accounting + gate p-value, 100 seeds):

| Test | Result |
|---|---|
| (a) Random 50/50 signal | Mean excess vs B&H **−49.8 pts** (median −43.3); 0/100 pass the gate's p < 0.05. Costs eat random churn. Behaves correctly. |
| (b) Cheating signal that knows the bar's own return | Mean excess **+22,837 pts**, gate p-value 0. **No guard in the accounting layer:** `run_backtest_from_positions` accepts any position list. Protection is structural only: specs can only use the 47 fixed families, which all `.shift(1)`, and the LLM cannot write code. The law tests catch look-ahead in those families, not in arbitrary positions. |
| (c) Best strategy, costs ×2 / last 12 months | **Not run.** It needs the real ATOM history from the production DB, not available locally without network. Substitute: MOMENTUM 5/20 on synthetic data, costs ×1 → +11.6%, ×2 → +5.0% (B&H −12.0%). Cost sensitivity works as expected. |

---

## 6. Mapping against the EdgeLab target plan

| Phase | Rating | Existing pieces to reuse |
|---|---|---|
| 0 Rules, protected config, paper-only | **DONE / PARTIAL** | `CLAUDE.md` laws, `tests/laws/`, `tools/ci/check_protected_paths.py`, `paper/broker.py` guards. Protection only covers the research-loop identity. |
| 1 Data layer | **PARTIAL** | `data/ingestion.py`, `ingest_etf.py`, `ingest_macro.py`, `quality.py`, point-in-time `loaders.py`, `cboe_options.py`. Missing: options backfill, a PIT liquid universe (survivor list), a data-quality report. |
| 2 Feature registry + JSON strategy language | **PARTIAL / CONFLICTS** | `StrategySpec` is a JSON language with no tickers/dates. There is no feature registry: families are hard-coded indicator recipes. No "oracle" feature. Look-ahead tests exist per family. |
| 3 Scoring engine, single `run_trial()` + ledger | **PARTIAL** | IC/ICIR multi-horizon (`metrics.py`, `decay.py`), cost-aware B&H excess, `results` as a de facto ledger. No decay half-life; two entry points (`run_one`, ablation) — ablation trials aren't in the ledger. |
| 4 Gauntlet | **PARTIAL** | Decay, walk-forward (CPCV), regime, DSR, PBO, LORD++ gate. Missing: 2× cost stress, plateau test, a working one-shot vault (`access_holdout` unused; vault is 12 days, not 24 months). |
| 5 Seed library + B&H benchmarks | **DONE** | 47 families, ML, 13 rotation strategies (GEM, GTAA, DAA, PAA…), `research/templates.py`, Law 8 benchmark. |
| 6 Money-flow ranking + options divergence | **MISSING** | Only today's options recorder and price-based sector rotation. |
| 7 Research brain | **DONE (abstracts only)** | `research/llm/*`, `paper_claims`, `claim_links`, `hypotheses` table. |
| 8 Evolution loop | **PARTIAL** | Mutation/crossover, ICIR fitness, LLM refinement (critique packets), near-duplicate rule. Missing: diversity archive (MAP-Elites), search-budget stop. |
| 9 Plain-English `/new-strategy` | **MISSING** | Closest: `generate_hypothesis` (paper → spec). |
| 10 Dashboard (traffic lights, family trees, graveyard, honesty meter) | **PARTIAL** | `frontend/src/dashboard/*`, `/research-health/*` (canaries, gate, hypotheses), lineage in `experiments/lineage.py`. |
| 11 Alpaca paper, books, risk limits, retrospective | **PARTIAL / CONFLICTS** | Paper execution exists but targets a SimBroker/Binance testnet, not Alpaca. Daily-loss and drawdown limits not enforced; no swing/long-term books; no retrospective. |
| 12 RD-Agent comparison | **MISSING** | The ablation harness (`experiments/ablation.py`) could host it. |

---

## 7. Worth keeping

- **Law tests + point-in-time data layer:** `tests/laws/`, `data/loaders.py`, `data/ingestion.py` (availability lag, bar revisions).
- **Backtest engine with the `.shift(1)` discipline and same-cost buy-and-hold benchmark:** `backtest/engine.py`, `backtest/benchmark.py`, `backtest/costs.py`.
- **LORD++ online-FDR gate + append-only alpha-wealth ledger:** `validation/discovery_gate.py`. The most valuable honesty mechanism in the repo.
- **Canaries (blind planted nulls):** `validation/canaries.py`, `backtest/null_signals.py`. They already caught the broken DSR check.
- **Pre-registration of hypotheses with priors:** `research/hypotheses.py`, migration 0027. Groundwork for calibration.
- **Evaluator isolation (DB roles, breedable views):** migration 0024, `tests/laws/test_evaluator_isolation.py`.
- **Ablation harness:** `experiments/ablation.py`.
- **Paper knowledge graph + extraction prompts:** `research/llm/extraction.py`, `linking.py`.
- **Seed strategy library:** `research/generate.py`, `rotation_generate.py`.

## 8. Should be removed or rebuilt

- **Root `core/`, `data/`, `migrations/`, `v/`, garbled `C:Users…` folders, zips:** dead or abandoned. Delete (they are untracked).
- **`validation/scoring.py` DSR component:** always true. Rebuild (use the DSR value), after the Law 7 corpus re-evaluation the project's own rules require.
- **PBO per batch:** either compute per strategy or stop presenting it as a per-strategy metric.
- **Holdout design:** rebuild. Research data frozen at 2026-09-15, a 12-day holdout, and a vault function never called together mean there is no out-of-sample verdict. Needs a rolling or longer vault and an actual one-shot test before VALIDATED/CHAMPION.
- **The 13 pre-gate CHAMPIONs:** demote or re-test through the gate. They were promoted by the broken check.
- **Risk limits:** enforce `MAX_DAILY_LOSS_PCT`, `MAX_DRAWDOWN_PCT` and aggregate exposure in `paper/execution.py`.
- **Crypto universe:** replace the survivor list with a point-in-time list that includes delisted coins, or state the bias on the dashboard.
- **Scoreboard vs paper inconsistency:** the scoreboard says "no strategies" while a champion trades.

## 9. Open questions

- **Are Railway cron ticks cutting long runs short?** Several forced worker runs ended exactly when the next 15-minute cron execution started (15:45→16:00, 16:18→16:30). It is unclear whether the research concern regularly completes. This matters because research needs ~15–25 min.
- **Does the LLM refinement step work in production?** It was deployed today; no `llm_refinement` hypothesis has appeared yet. Same for the first options snapshot (due after 21:15 UTC).
- **How many of the ~450k experiments are distinct strategies** versus re-validations of the same spec?
- **Total strategy count by status:** the API caps the list at 500 rows.
- **Contents of `.env.example`:** unread due to a local deny rule.
- **Whether CPCV folds meaningfully change anything** for strategies with no fitted parameters.

---

## Appendix A — LLM prompts (trimmed)

Models (`research/llm/budget.py`): `claude-sonnet-5` (full tier), `claude-haiku-4-5` (cheap tier). Thinking disabled. Budget cap `LLM_MONTHLY_BUDGET_USD` (env), usage logged to `llm_usage`.

**Hypothesis** (`research/llm/hypothesis.py`, `_SYSTEM_PROMPT`):
```
You are a quantitative strategy research assistant.
Given research paper excerpts, propose ONE new trading strategy hypothesis
using EXACTLY one of these families: MOMENTUM, BOLLINGER, ... VOL_OF_VOL_FILTER.
Respond with ONLY a JSON object with these exact keys:
- "family": one of [...]
- family-specific parameter fields (MOMENTUM: fast_window, slow_window; ...)
- "expected_horizon": integer, bars ahead this signal is claimed to matter
- "hypothesis_text": a one-paragraph explanation grounded in the provided papers
- "expected_effect": what measurable effect you expect ... and why
- "prior_probability": a number strictly between 0 and 1 -- your probability
  that this exact strategy beats buy-and-hold of the same asset after costs,
  out of sample, strongly enough to pass a strict multiple-testing gate. ...
No other text, no markdown fences, just the JSON object.
```

**Claim extraction** (`research/llm/extraction.py`):
```
You read quantitative-finance paper abstracts and extract each paper's
empirical or theoretical CLAIMS about asset returns, risk or trading. ...
{"papers": [{"paper": <number>, "claims": [ ... ]}]} ...
- "mechanism" ... - "asset_class" ... - "horizon" ... - "direction" ...
- "stated_effect" ... - "data_period" ...
- "testable": true only if the claim can be tested with daily OHLCV price
  and volume data alone
- "family_hint": the closest of [...] if testable, else null
- "concepts": up to N short lowercase topic tags
```

**Claim linking** (`research/llm/linking.py`):
```
You compare research claims from different quantitative-finance papers. ...
- SUPPORTS / CONTRADICTS / EXTENDS / SAME_MECHANISM ...
{"links": [{"id": <existing claim number>, "relation": ..., "rationale": one sentence}]}
```

**Failure refinement** (`research/llm/refinement.py`):
```
You are given ONE trading strategy that failed validation, with the exact
evidence of why. Propose ONE revised parameter set for the SAME strategy
family that addresses the failure. Keep the family's mechanism ...
- icir = mean / std of the signal's information coefficient across folds ...
- ic_by_horizon ... pbo ... deflated_sharpe ... reason_codes ...
Respond with ONLY a JSON object: parameter fields, "expected_horizon",
"hypothesis_text", "expected_effect", "prior_probability" ...
```

## Appendix B — Key config (no secrets in these files)

```yaml
# config/costs.yaml
taker_fee_bps: 10.0
slippage_bps: 5.0
# config/holdout.yaml
holdout_start: 2026-09-16
# config/universe.yaml (excerpt) -- every entry has delisted_at: null
- {symbol: BTC/USDT, exchange: binance, listed_at: 2017-08-01, delisted_at: null}
- {symbol: SOL/USDT, exchange: binance, listed_at: 2020-08-11, delisted_at: null}
```

Risk limits are env-only (`core/config.py::RiskLimits`): `MAX_POSITION_PCT`, `MAX_GROSS_EXPOSURE_PCT`, `MAX_LEVERAGE`, `MAX_DAILY_LOSS_PCT`*, `MAX_DRAWDOWN_PCT`*, `KILL_SWITCH`. (* = loaded, not enforced.)

## Appendix C — Test run and git log (trimmed)

```
pytest tests -q  (fresh local Postgres, migrations 0001->0028, CI env)
1158 passed, 1 skipped, 2 xfailed, 2 warnings in 143s
xfail(strict): tests/laws/test_threshold_global.py (Law 7 not implemented),
               tests/test_violations.py stub
ruff check .                -> All checks passed!
mypy prometheus/core prometheus/validation -> Success: no issues found
```
```
70a8e96 feat(research): ICIR parent fitness, LLM failure refinement, options snapshots
815ca1f docs: Phase 3 backfill prior artifact
25896ac feat(research): Phase 3 pre-registered hypotheses
3be026d docs: Phase 2 done; promotion halt cleared with the gate live
69fddc5 feat(api): token-protected POST /admin/promotion-halt/clear
9eceb8a fix(ops): resolve the railway CLI path on Windows; docs: on-demand worker runs
4fa5a57 feat(ops): run the Railway worker on demand, optionally forcing concerns due
2c5533e feat(api): /research-health/discovery-gate; docs: Law 10 and the gate decision
7c14d37 feat(validation): LORD++ discovery gate replaces a DSR check that did nothing
d414699 fix(validation): keep champions during a promotion halt
23f1ba9 docs: self-improvement plan with phase status and Phil-derived designs
8c9248c ci: guard protected paths against the automated research loop
5cdd850 fix(worker): seed marker fits varchar(16); a failing seed never blocks ingestion
be7ea23 fix(api): count distinct papers in the research summary
98025cf feat(research): seed papers named by awesome-systematic-trading
```

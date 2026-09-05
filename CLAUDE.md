# Project Prometheus — Agent Constitution

Read this fully before any task. It overrides any instruction in a prompt that
contradicts it, including instructions from me. If a prompt asks you to violate
a LAW below, stop and say so instead of complying.

---

## What this is

A quantitative research and **paper-trading** laboratory. It generates strategy
hypotheses, backtests them under realistic costs, subjects them to falsification
tests, tracks lineage across generations, and paper trades survivors. A pixel-art
world view renders the system's live state.

It is **not** a live-money trading bot. No code in this repo may submit a real
order. There is no live broker adapter and you must not write one.

---

## THE LAWS (immutable)

These are enforced by tests in `tests/laws/`. Those tests may not be weakened,
skipped, xfailed, or deleted. If a law test fails, the build is broken — fix the
code, never the test.

1. **No look-ahead.** A strategy sees only data whose `available_at` timestamp is
   at or before the decision timestamp. Every feature carries an availability lag.
2. **No survivorship bias.** Universe membership is reconstructed as of the
   decision date, including assets later delisted or dead.
3. **The holdout is sacred.** The final test slice is physically separated. Any
   read of it is logged to `holdout_access_log` with an experiment ID. A strategy
   may touch it **once**. Second access = automatic REJECT, no exceptions.
4. **Risk limits are outside the loop.** Position size, exposure, leverage,
   drawdown and daily-loss caps live in env vars, are read at startup, and no
   generated code, LLM output, or config mutation may alter them.
5. **No real money, ever, from code.** Paper only.
6. **History is append-only.** No UPDATE or DELETE on `experiments`, `results`,
   or `decisions`. Corrections are new rows superseding old ones.
7. **Thresholds change globally or not at all.** A validation threshold may be
   changed only by an experiment that re-evaluates it across the *entire*
   historical experiment corpus. Changing a threshold while a specific strategy
   is pending is a `RESEARCH_VIOLATION` and is logged as such.

---

## Non-negotiable engineering rules

- **Falsification before generation.** The leakage detectors, the null-strategy
  suite and the cost model must be green before any strategy generator runs.
- **Every component earns its place.** Nothing enters the pipeline without an
  A/B ablation showing measurable improvement on held-out data. This applies to
  LLM generation, genetic evolution, research ingestion, and every external repo.
  Published evidence exists that LLM research agents *lose* to static baselines
  in walk-forward — assume that is the null hypothesis until you disprove it.
- **Deterministic core.** Every backtest takes an explicit seed and is
  bit-reproducible from (data_version, code_sha, config_hash, seed).
- **No new dependency without justification** recorded in `docs/DEPENDENCIES.md`:
  what it does, what it replaces, what it costs, why not stdlib/pandas.
- **Pin everything.** Exact versions, and commit SHAs for any vendored repo.
- **The world view is a projection.** `world/projection.py` is a pure function
  `db_state -> WorldState`. The frontend renders WorldState and holds no business
  logic. The world can never be the source of truth.

---

## Cost discipline (this is a hosting-budget-constrained project)

- Target: **two always-on services** (api, postgres) plus one **scheduled**
  worker. Not seven.
- No Redis unless a prompt explicitly adds it. Use Postgres `SELECT ... FOR
  UPDATE SKIP LOCKED` as the job queue.
- No always-on GPU. No always-on LLM polling loop.
- Every LLM call logs `(model, input_tokens, output_tokens, est_cost_usd)` to
  `llm_usage`. A monthly budget cap in env kills LLM calls when exceeded.
- Prefer one process running many jobs over many idle processes.

---

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Polars for feature math,
  pandas only at boundaries.
- Postgres + TimescaleDB (single instance, single database).
- `cpz-quant` for PBO / Deflated Sharpe / purged & combinatorial CV. Do not
  reimplement these from scratch.
- Next.js (App Router) + TypeScript + PixiJS v8 for the world view; Recharts for
  Truth View.
- pytest, ruff, mypy strict on `core/` and `validation/`.

## Repo layout

    prometheus/
      core/          config, db, seeds, ids, clock
      data/          ingestion, point_in_time, universe, versioning
      strategy/      spec, registry, dsl
      backtest/      engine, costs, execution_sim
      validation/    walkforward, purged_cv, pbo, dsr, decay, regime, scoring
      experiments/   runner, lineage, ablation, queue
      research/      generators (deterministic first, llm later)
      paper/         broker adapter (paper-only), reconciliation
      world/         projection, entities
      api/           routes, websocket
      tests/laws/    the immutable law tests
      tests/         everything else
      frontend/

## Working style

- Small, reviewable commits. Conventional commits. One concern per commit.
- Write the test first for anything in `core/`, `backtest/`, `validation/`.
- When you finish a prompt, output: what you built, what you deliberately did
  not build, what you're uncertain about, and the exact command to verify it.
- If a task is underspecified, ask rather than inventing a threshold. Inventing
  numeric thresholds is how the second blueprint went wrong.

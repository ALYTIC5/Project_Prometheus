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
8. **Everything runs against Buy & Hold.** Every strategy, every backtest, every
   paper-trading result, every dashboard view is compared against a €1,000
   buy-and-hold of the strategy's own universe (equal-weight for multi-asset,
   100% for single-asset). The benchmark uses the SAME cost model for entry
   (one buy at inception). If a strategy cannot beat this after costs, it is
   not an edge — it is activity. The buy-and-hold equity curve is always
   visible. The system's job is to prove it can do better; the default
   assumption is that it cannot.
9. **The evaluator is out of reach.** No research, generation, or LLM process
   may write to evaluation code, validation state, the holdout, the canary
   registry, or the alpha-wealth ledger. Research code runs as the
   non-superuser research DB role (migration 0024), reads the population only
   through the canary-free breeding views, and every strategy status change
   goes through `validation/status.py::set_status`. Enforced by
   `tests/laws/test_evaluator_isolation.py`.

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

## World & Art Laws (World Track)

W1. Every visual state is a pure function of WorldState plus
    config/world_visuals.yaml. The renderer never decides something "looks bad".
W2. Information-bearing motion is only for signal entities (agents bound to jobs,
    heroes bound to strategies). Ambient townsfolk are allowed ONLY if they are:
    visually distinct, excluded from anything the user reads as workload,
    hideable via "Signal only", seeded-deterministic, and never enter the Oracle,
    Vault, Arena or Harbour.
W3. Scenes never decide outcomes. Outcomes come from event payloads. Animation
    duration is cosmetic and must never imply timing that didn't happen.
W4. Mock/scenario data always shows a non-dismissable "SIMULATED DATA" banner
    and can never be the default in a production build.
W5. No variant-specific branches outside the sprite manifest (Prompt 1 rule).
W6. No text or numbers baked into art. The engine renders all text (e.g. the
    Monument's "€1,000").
W7. Every asset is palette-locked to world_client/sprites/palette.json and has a
    row in art/registry.json (tool, PixelLab id, prompt, generations spent, date).
W8. PixelLab spend: generate as much as the work needs, following the
    PAUSE-AND-RESUME PROTOCOL (below). Run a pilot before any batch. Never use
    mode="pro" or confirm_cost=true without explicit human approval in chat.
    If $ART_CHECKPOINT_GENERATIONS is set, pause for review when it is reached.
W9. The PixelLab token never appears in any repo file, log, registry row, commit,
    or chat message. Never ask the user to paste a key into the conversation;
    tell them to update the PIXELLAB_API_TOKEN environment variable instead.

### Pause-and-resume protocol (PixelLab credits)
- Before EVERY batch, call get_balance and estimate the batch cost. If the
  balance cannot cover the whole batch, do not start it (half-finished batches
  leave animations with missing directions).
- Treat any PixelLab error mentioning credits, balance, quota, insufficient,
  payment, 402 or 429 as "out of generations". Stop queueing immediately.
- Jobs already queued keep running. Poll them to completion, download, and ingest.
- Write art/RESUME.md: the prompt being run (e.g. W4), the exact step, what is
  done, what is queued, what remains, and the estimated generations still needed.
  Every job id must already be in art/registry.json.
- Commit the work, then end the session with this message to the user:
    "PixelLab generations exhausted. Top up the account (or update
     PIXELLAB_API_TOKEN), restart Claude Code, and run the RESUME prompt."
- On resume: call get_balance first, confirm it is the SAME PixelLab account
  (list_characters must show the mockup characters), fill any partial animation
  groups via animation_group_id before starting new work, then continue from
  art/RESUME.md.
W10. Quantitative values are never rendered in decorative fonts or replaced by
     game scores. Hero stats always expose the underlying metric on hover and
     show "UNMAPPED" when no source exists.
W11. WORLD SCALE IS ENFORCED, NEVER ASSUMED. Before queueing ANY PixelLab job,
     `tools.art.scale.preflight(key, canvas)` must pass. Every downloaded asset
     must pass `python -m tools.art.check_asset <png> <size> --key <key>` (which
     measures content size against world scale). Buildings are sized from the
     backend footprint (construction.py BUILDING_LOCATIONS), never from
     theme.yaml's `footprint`. A category with no rule in theme.yaml `scale:`
     may not be generated until its size is decided. An asset that fails scale
     never ships and is never "fixed later" -- regenerate at the right canvas.
     Report scale results to the user for every generated asset. Tests:
     tests/test_art_scale.py (may not be weakened or skipped).

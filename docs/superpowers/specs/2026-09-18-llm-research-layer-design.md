# LLM Research Layer (PROMPT 9) — Design

**Spec status:** approved in conversation, written up for record and for the
implementation plan to argue from.

## Goal

Add an LLM-driven strategy hypothesis generator that ships gated: it never
touches the holdout set, never evaluates its own output, and is registered
as an ablation component that must prove it beats the Prompt 7 deterministic
baseline net of API cost before it's ever trusted. If it doesn't, it stays
disabled and that result is surfaced prominently, not hidden.

## Decisions made (with reasoning)

- **LLM provider: Anthropic API.** Matches this project's own ecosystem.
  Two model tiers for the budget gate: Sonnet (full budget), Haiku (≥80% of
  monthly budget spent).
- **Restricted DSL: reuse the 3 existing `StrategySpec` families** (MOMENTUM/
  BOLLINGER/VOL_BREAKOUT), not a new expression grammar. `strategy/spec.py`'s
  own docstring names a bigger DSL (`features/signals/entry_rules/...`) as
  the eventual Prompt 9 surface, but building a safe whitelisted-indicator
  grammar + validator + interpreter is a substantial standalone project of
  its own. CLAUDE.md's own null hypothesis — LLM research tends to lose to
  static baselines — argues for proving the cheap version first: let the LLM
  pick a family and parameters via the EXISTING, already-validated
  `StrategySpec` constructor. No engine changes, directly ablatable with
  machinery that already exists. Revisit a real DSL only if this proves
  valuable enough to be worth expanding its expressiveness.
- **arXiv ingestion depth: full PDF text extracted, but only
  abstract+introduction+methodology+results/conclusion sections fed to the
  LLM.** Full text is still stored for future reprocessing; the trimmed
  `key_sections` field is what actually goes into the hypothesis prompt, to
  control token cost without losing the abstract-only-is-too-thin problem.
- **VibeQuant does not exist as a paper-extraction reference.** Web search
  found several unrelated small repos named "vibequant" (a `yfinance`
  wrapper library, a couple of near-empty forks) — none has any paper/PDF
  extraction functionality. Same "named repo doesn't fit reality" outcome
  already documented for other externally-named repos in this project
  (Qubx, PROMPT 8).
- **Section extraction: GROBID (`kermitt2/grobid`, 5.1k★, Apache 2.0), not a
  regex heuristic.** A real, production-proven ML-based structured-extraction
  tool for exactly this job (used by ResearchGate, CERN, Mendeley), with an
  official Python client (`grobid-client-python`) — a genuinely better fit
  than hand-rolled heading-regex matching. The real cost: it's a Java Docker
  service, not a pure-Python library, which is real infra weight for a
  hosting-budget-constrained project (CLAUDE.md's cost discipline targets
  two always-on services + one worker). Resolved by deploying GROBID as its
  own Railway service with **scale-to-zero enabled** — $0 idle cost, only
  ever spun up (cold-starting on the rare request) when an ingestion cycle
  actually calls it over Railway's private network. Not an always-on third
  service, and not a Docker-in-Docker pattern from inside the worker
  (Railway services have no Docker socket access to do that even if wanted).
- **AgentQuant and QuantEvolve: deferred, not evaluated.** PROMPTS.md marks
  both optional. Same posture as the Qubx evaluation: real scope, no
  evidence yet that the core LLM layer itself is worth having, so evaluating
  two more repos is premature. Recorded in `docs/DEFERRED.md`.

## Data model (migration `0013_llm_research.py`)

```sql
CREATE TABLE research_papers (
    id              BIGSERIAL PRIMARY KEY,
    arxiv_id        VARCHAR(32) UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    abstract        TEXT NOT NULL,
    full_text       TEXT NOT NULL,
    key_sections    TEXT NOT NULL,  -- abstract+intro+methodology+results/conclusion via GROBID, or pypdf-only fallback
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_hypotheses (
    id               BIGSERIAL PRIMARY KEY,
    strategy_id      VARCHAR REFERENCES strategies(id),
    paper_ids        JSONB NOT NULL DEFAULT '[]',  -- research_papers.id list this hypothesis cited
    hypothesis_text  TEXT NOT NULL,
    expected_effect  TEXT NOT NULL,
    model            VARCHAR(64) NOT NULL,
    input_tokens     INTEGER NOT NULL,
    output_tokens    INTEGER NOT NULL,
    est_cost_usd     NUMERIC(10, 6) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
    id               BIGSERIAL PRIMARY KEY,
    model            VARCHAR(64) NOT NULL,
    input_tokens     INTEGER NOT NULL,
    output_tokens    INTEGER NOT NULL,
    est_cost_usd     NUMERIC(10, 6) NOT NULL,
    purpose          VARCHAR(64) NOT NULL,  -- e.g. "hypothesis_generation" -- every call logs here, successful or not, matching CLAUDE.md's cost-discipline section verbatim
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

None of these three tables need Law 6's append-only trigger extended onto
them beyond `llm_usage`/`llm_hypotheses`/`research_papers` themselves being
insert-only by construction (nothing here is ever UPDATEd) — no new
exemption logic needed, same posture as `AblationTrial`.

## Modules

### `research/llm/ingestion.py`

- `search_arxiv(query: str, max_results: int) -> list[ArxivPaper]` — calls
  arXiv's public API (no key required), returns id/title/abstract/pdf_url.
- `ingest_paper(session, arxiv_id: str) -> ResearchPaper` — downloads the
  PDF, extracts full text via `pypdf` (stored as `full_text`, archival), then
  calls the GROBID service (`grobid-client-python`, over Railway's private
  network — `GROBID_URL` env var) to get real structured section
  segmentation and pulls out abstract+introduction+methodology+results/
  conclusion into `key_sections`. If the GROBID service is unreachable
  (cold-start timeout, service down) this is a soft failure: falls back to
  `full_text` truncated to the same section budget via `pypdf` alone, logged
  as a warning, never a hard failure of the ingestion cycle — a paper with
  slightly worse extraction is better than no paper ingested this cycle.
  Idempotent on `arxiv_id` (upsert, matching `ConfigSnapshot`'s
  dedup-by-key precedent, not Law 6's strategies/results/decisions
  append-only set).

### `research/llm/budget.py`

- `BudgetSettings` (pydantic-settings, same fail-fast pattern as
  `RiskLimits`): reads `LLM_MONTHLY_BUDGET_USD` from env.
- `current_tier(session) -> Literal["full", "cheap", "halted"]`: sums
  `llm_usage.est_cost_usd` for the current calendar month, compares against
  `LLM_MONTHLY_BUDGET_USD`. `<0.8× budget` → `"full"` (Sonnet), `<1.0×` →
  `"cheap"` (Haiku), `>=1.0×` → `"halted"`.
- `model_for_tier(tier) -> str`: the literal Anthropic model id for a tier.
- `estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float`:
  a small `{model: (usd_per_1k_input, usd_per_1k_output)}` constant table
  (Anthropic's published per-model pricing, cited, not invented) — the one
  place a token count becomes a dollar figure, called by whatever persists
  an `llm_usage`/`llm_hypotheses` row.

### `research/llm/hypothesis.py`

**The safety-critical module. Takes no DB session parameter anywhere in its
public API — structurally cannot open a holdout connection, cannot call
`run_backtest`, cannot evaluate its own output.**

- `generate_hypothesis(client: anthropic.Anthropic, model: str, symbol: str,
  timeframe: str, paper_context: list[PaperContext]) -> LLMHypothesis` —
  builds a prompt from `paper_context` (each entry's `key_sections`, not
  `full_text`), calls the Anthropic Messages API, parses the structured
  response (family, params, expected_horizon, hypothesis_text,
  expected_effect) and constructs a real `StrategySpec` via its existing
  constructor — a malformed LLM response fails `StrategySpec`'s own
  validation and raises, it is never silently coerced into something
  invalid.
- Returns `LLMHypothesis(spec: StrategySpec, hypothesis_text: str,
  expected_effect: str, paper_ids: list[int], model: str, input_tokens: int,
  output_tokens: int, est_cost_usd: float)`.

A thin orchestration function elsewhere (`worker.py`'s research cycle, see
below) is what persists the result: inserts the `Strategy` row
(`source="llm_hypothesis"`, same field `research/mutations.py` already uses
for `source="mutation"`), the `llm_hypotheses` row, and the `llm_usage` row
— then the resulting spec flows into the exact same
`experiments/runner.py`/`enqueue_grid`/`validate_grid` pipeline every other
spec goes through. No bypass path exists for an LLM-generated spec to reach
holdout early or skip validation.

**Holdout-safety test:** a structural test asserting
`research/llm/hypothesis.py` imports nothing from `prometheus.validation.holdout`
or `prometheus.core.db` (no `get_holdout_session`, no `AsyncSession` type
anywhere in its signatures) — the module literally cannot open the
connection Law 3 protects, checked by static inspection of its own AST/
imports rather than trusting a runtime mock not to catch every path.

### Worker integration (`prometheus/worker.py`)

`_run_research()` gets one more bounded step, after the existing evolution
step, gated by `budget.current_tier()`:

```python
tier = await budget.current_tier(session)
if tier != "halted":
    model = budget.model_for_tier(tier)
    # one bounded hypothesis per cycle (same "one evolution step per
    # cycle" bounding _run_evolution_step already uses) -- symbol chosen
    # the same way enqueue_grid iterates `symbols` today. Paper search is a
    # fixed arXiv category filter (q-fin.* -- Quantitative Finance), not a
    # free-text query: search_arxiv takes an explicit query argument for
    # testability, but production always calls it with this fixed category,
    # never anything derived from strategy state.
    ...
```

Deterministic generation (grid + evolution) is unconditional, unaffected by
`tier == "halted"` — it is entirely separate code in the same function,
never gated on budget.

### Ablation (`prometheus/experiments/ablation.py`)

`register_llm_component(session, *, symbols, timeframe, start, end,
version)` — same shape as the existing `register_evolution_component`:
per symbol, scores the best baseline-grid spec and the best LLM-generated
spec (from `llm_hypotheses` joined to `strategies`) with the real backtest
engine, records one paired trial via the existing `record_trial`, then
`_recompute_registry` produces a real VALUABLE/NEUTRAL/HARMFUL/UNPROVEN
verdict — reused, not reimplemented. This automatically reaches the Temple
of Knowledge via `component_registry` → `world/projection.py`, already
wired for every other component.

## Testing

- `tests/test_llm_hypothesis_holdout_safety.py` — the structural
  no-holdout-import test described above.
- `tests/test_llm_hypothesis.py` — `generate_hypothesis` with a mocked
  Anthropic client, asserting: a well-formed response produces a valid
  `StrategySpec`; a malformed response (bad family, invalid param
  combination) raises rather than producing an invalid spec.
- `tests/test_llm_budget.py` — `current_tier`'s three thresholds, using a
  real Postgres `llm_usage` table (db-marked, same skip posture as every
  other db test in this suite).
- `tests/test_llm_ingestion.py` — `ingest_paper` with a mocked GROBID client:
  (1) a well-formed TEI response produces the right `key_sections` (asserts
  references/acknowledgments are excluded); (2) a GROBID connection failure
  falls back to the `pypdf`-only path without raising, and is still a
  complete, storable `ResearchPaper` row.
- Ablation: extend `tests/test_ablation_*` coverage with
  `register_llm_component`'s own paired-trial shape, mirroring
  `register_evolution_component`'s existing test.

## Out of scope (this prompt)

- A general restricted DSL beyond the 3 existing families (see decision
  above) — `strategy/dsl.py` stays unbuilt; revisit only if this component
  proves VALUABLE enough to be worth expanding.
- AgentQuant, QuantEvolve — deferred (`docs/DEFERRED.md`).
- Any change to `paper/` (paper trading only trades PROMOTE-verdict
  strategies today, regardless of `source` — an LLM-sourced strategy that
  reaches PROMOTE is already eligible with zero paper/ changes needed).

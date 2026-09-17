# PROMPT 8 — Paper trading (Harbour launches)

Status: approved for implementation planning.
Scope: `PROMPTS.md` lines 668-708. Law 5 is absolute — no code path in
this design ever submits a real-money order.

## Eligibility and capital

- Only `CHAMPION` strategies board a ship. `CHAMPION` is already a
  derived, bounded set (`research/population.py::elect_champions` — one
  best-scoring `VALIDATED` strategy per family). With today's three
  families that is a hard cap of 3 concurrent paper strategies, not an
  invented limit.
- Each boarded strategy paper-trades with exactly €1,000 of notional,
  matching `backtest/engine.py::STARTING_CAPITAL` and
  `backtest/benchmark.py::STARTING_CAPITAL` exactly, so reconciliation
  (expected vs. actual) compares the same-sized position the backtest
  validated, not a rescaled one.
- When `elect_champions` demotes a stale champion or promotes a new one,
  the demoted strategy's open paper position is closed out (market order,
  same broker path) and it stops receiving new signals; a newly-elected
  champion boards on its next 1d bar close, not mid-cycle.

## Decision cadence vs. execution cadence

The CHAMPION's trading decision is computed on 1d bars via the exact
same `signal_for()` call the backtest uses — never recomputed on a
shorter bar, which would silently validate a different, unvalidated
strategy and break reconciliation. What runs faster is the execution
loop: order status polling, fills, and reconciliation checks, on a
15-minute cadence. This is not an invented number — it is PROMPTS.md's
own literal schedule ("data ingest hourly, research drain every 30 min,
paper reconciliation every 15 min when live").

### Worker cron changes

The Railway cron interval tightens from `*/30 * * * *` to
`*/15 * * * *` — still one scheduled worker, not a second service
(`CLAUDE.md`: "two always-on services... plus one scheduled worker, not
seven"). Three concerns now run at three different rates from the same
entrypoint, gated by a new table:

```sql
CREATE TABLE worker_cadence (
    concern      TEXT PRIMARY KEY,
    last_run_at  TIMESTAMPTZ NOT NULL
);
```

- `ingest` — due if `now() - last_run_at >= 60 min` (or no row yet).
- `research` — grid enqueue + `drain_queue` + `validate_grid` + the
  PROMPT 7 evolution step, today's entire `run_once()` body. Due at
  `>= 30 min`.
- `paper` — execution + reconciliation + divergence. Due at `>= 15 min`
  (i.e., every tick).

Each concern updates its own `last_run_at` only after it completes
successfully, so a crashed tick re-attempts that concern next wake
rather than silently skipping it.

## Components

### `paper/broker.py`

Thin wrapper over `ccxt.binance()` — deliberately not `binanceus`
(`data/ingestion.py`'s choice, forced by Binance.com's 451 geo-block on
*market-data* endpoints). Binance's public spot testnet
(testnet.binance.vision) is a wholly separate sandbox with its own
credential pair and is unaffected by that geo-block; `binanceus` has no
equivalent testnet. On construction:

- Calls `exchange.set_sandbox_mode(True)` and asserts the resulting
  `exchange.urls['api']` string contains the known testnet host —
  raises `RuntimeError` if not (defense against a future ccxt version
  changing sandbox behavior silently).
- Reads credentials from `PAPER_API_KEY` / `PAPER_API_SECRET` only.
- Raises `RuntimeError` at construction if any live-sounding variable
  (`BINANCE_API_KEY`, `BINANCE_API_SECRET`, or anything matching
  `^(?!PAPER_).*API_(KEY|SECRET)$` scoped to known exchange prefixes) is
  present in the environment at all — sandboxed or not, its mere
  presence is the failure mode this guards against.
- Exposes `submit_order`, `fetch_order`, `cancel_order`,
  `fetch_open_orders` — the same subset shape `data/ingestion.py`'s
  `ExchangeClient` protocol already establishes for `fetch_ohlcv`, so
  both broker and ingestion follow one "typed ccxt subset" convention.
- Every call retries transient `ccxt.NetworkError` with the same
  backoff shape `experiments/queue.py`'s job retry already uses
  (`JOB_BACKOFF_BASE_SECONDS` / `JOB_BACKOFF_MAX_SECONDS` from
  `QueueSettings`), not a new backoff constant.

### `paper/execution.py`

- `decide_and_submit(session, champion, broker)`: called once per
  champion per worker tick. No-ops unless a new 1d bar has closed since
  the champion's last recorded decision. Computes `signal_for()`,
  diffs against current position (see below), and if a change is
  needed, sizes the order off €1,000 notional clamped by
  `RISK_LIMITS.MAX_POSITION_PCT` / `MAX_GROSS_EXPOSURE_PCT` /
  `MAX_LEVERAGE` (Law 4 — read, never mutated), then submits via
  `paper/broker.py` with a deterministic `client_order_id =
  sha256(strategy_id | event_time | side)` so a retried tick after a
  crash never double-submits.
- `poll_fills(session, broker)`: called every tick regardless of
  whether a new bar closed. Fetches open `paper_orders` rows, calls
  `fetch_order`, updates status/`filled_qty`/`avg_fill_price`/
  `filled_at`.
- Position for a strategy is *derived*, not stored: `SUM(filled_qty *
  sign(side))` over that strategy's `paper_orders`. One source of
  truth, no separate positions table to drift out of sync.

### `paper/reconciliation.py`

For every order that reaches `FILLED` since the last tick: compares
`expected_price`/`expected_qty` (recorded at submission time, from the
same `signal_for()` call and `apply_cost` model the backtest used) against
`avg_fill_price`/`filled_qty`, and derives entry/exit/fill-latency/cost/
P&L deltas. Also recomputes the champion's realized paper equity curve
and compares it against a €1,000 buy-and-hold over the identical window
(`backtest/benchmark.py`, Law 8) — a strategy trailing its own
buy-and-hold writes a `PAPER_WORSE_THAN_HOLDING` finding, surfaced with
the same prominence the Monument gives Law 8 elsewhere (not a buried log
line).

### `paper/divergence.py`

Applies a materiality check (reusing the null-strategy suite's existing
z=1.96 convention against the reconciliation deltas' own distribution —
not a new invented percentage) to slippage and fill-rate divergence. On
a material divergence: writes `PAPER_DIVERGENCE` to `paper_findings`,
sets `strategies.status = 'QUARANTINED'` (existing status from
`population.py`'s vocabulary — no new state introduced), and records the
recalibration proposal as a new `experiments` row (`strategy_id` set,
`hypothesis` describing the observed divergence, `change_set` describing
the suggested `config/costs.yaml` delta, `status="proposed"`) —
**not** a queue job. `experiments/runner.py::run_one` raises
`ValueError` for any job `kind` other than `"run_backtest"`
(verified — line 589), so a `cost_recalibration_proposal` job would
fail/retry/dead-letter, not sit as a harmless visible no-op.
PROMPTS.md's own wording is "propose cost-model recalibration as a new
**experiment**" anyway — `experiments.hypothesis`/`change_set` already
model exactly this. Visible in the dashboard's Experiments section, not
Queue. Nothing acts on this proposal automatically: Law 7 requires a
threshold change to be re-evaluated across the entire historical corpus,
never adopted off one strategy's proposal — the actual recalibration
consumer is deferred and documented, not silently dropped.

### `paper/duration.py`

The real content here is a citation, not a new number:
Bailey & López de Prado's **Minimum Track Record Length** — the natural
companion to the Probabilistic/Deflated Sharpe Ratio already hand-rolled
in `validation/multiple_testing.py` from the same paper, reusing its
private `_phi`/`_phi_inv` helpers and the same `(1 - skew*SR + (kurt-1)/4
* SR^2)` denominator PSR already computes. Adding
`minimum_track_record_length(sharpe_hat, benchmark_sharpe, skewness,
kurtosis, confidence) -> int` to `validation/multiple_testing.py`
(same module, same citation, same helpers — not a parallel
implementation). `paper/duration.py` calls it to get the required
independent-trade count, then translates that into a calendar horizon
using the champion's own historical trade frequency from its backtest
history.

## Data model

New migration, three tables:

```sql
CREATE TABLE paper_orders (
    id               TEXT PRIMARY KEY,
    strategy_id      TEXT NOT NULL REFERENCES strategies(id),
    client_order_id  TEXT NOT NULL UNIQUE,
    exchange_order_id TEXT,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    qty              NUMERIC(28, 8) NOT NULL,
    status           TEXT NOT NULL DEFAULT 'SUBMITTED',
    expected_price   NUMERIC(20, 8) NOT NULL,
    expected_qty     NUMERIC(28, 8) NOT NULL,
    filled_qty       NUMERIC(28, 8) NOT NULL DEFAULT 0,
    avg_fill_price   NUMERIC(20, 8),
    submitted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    filled_at        TIMESTAMPTZ
);

CREATE TABLE paper_findings (
    id           BIGSERIAL PRIMARY KEY,
    strategy_id  TEXT NOT NULL REFERENCES strategies(id),
    kind         TEXT NOT NULL,  -- PAPER_WORSE_THAN_HOLDING | PAPER_DIVERGENCE
    payload      JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- append-only, same trigger pattern migration 0003 already applies to
-- experiments/results/decisions (Law 6): these are historical findings,
-- never corrected in place.

CREATE TABLE worker_cadence (
    concern      TEXT PRIMARY KEY,
    last_run_at  TIMESTAMPTZ NOT NULL
);
-- deliberately mutable (like strategies.status), not append-only: this
-- is scheduling state, not a history log.
```

`paper_orders` is mutable (like `Strategy`) — a fill updates the same
row, it is not an event log; the append-only guarantee applies to
`paper_findings` only.

## Qubx evaluation (PROMPTS.md's explicit ask)

Checked via `gh repo view xLydianSoftware/Qubx`: GPLv3-licensed
("Framework for quantitative strategies development, backtesting and
live execution"), primary content is Jupyter notebooks, 69 stars.
Conclusion: **not adopted**.

- License: GPLv3 linked into this codebase risks obligating the whole
  combined work to GPLv3 if ever distributed — an unforced risk when
  `ccxt` (already an MIT dependency, already used in
  `data/ingestion.py`) covers everything a testnet broker adapter needs.
- Shape: notebook-first, not a clean headless library — a poor fit for
  the bounded, async, Postgres-queue-driven worker this repo already
  runs.
- PROMPTS.md explicitly permits concluding "our adapter is simpler" —
  this is that conclusion, recorded in `docs/DEPENDENCIES.md` and
  `docs/DEFERRED.md` (evaluated-and-rejected, with reasoning, not
  silently skipped).

## Error handling

- Broker construction failure (testnet assertion, live-var guard) is
  fatal at worker startup for the `paper` concern only — `ingest` and
  `research` continue unaffected that tick.
- Transient `ccxt.NetworkError` during submit/poll: retried with the
  queue's existing backoff constants; a submission that still fails
  after retry leaves the order unsubmitted (never partially recorded)
  and logs for next tick's retry — `client_order_id`'s determinism makes
  this safe to simply re-attempt.
- A fill discovered for an order whose `expected_price` was computed
  against since-superseded data (e.g. universe delisting mid-flight) is
  still reconciled against what was actually expected at submission
  time — reconciliation answers "was our prediction right," not "what
  would we predict today."

## Testing

- `paper/broker.py`: constructor asserts testnet URL; raises on any
  live-sounding env var present (parametrized over the known exchange
  prefixes); retry-on-`NetworkError` behavior via a fake `ExchangeClient`.
- `paper/execution.py`: idempotent submission (same tick replayed
  produces one order, not two); position-from-fills summation math;
  order sizing respects `RISK_LIMITS` clamps.
- `paper/reconciliation.py`: known expected-vs-actual fixtures produce
  the correct deltas; `PAPER_WORSE_THAN_HOLDING` fires against a
  synthetic losing equity curve and does not fire against a winning one.
- `paper/divergence.py`: materiality check against a synthetic
  divergence distribution; quarantine + `cost_recalibration_proposal`
  enqueue on trip.
- `validation/multiple_testing.py::minimum_track_record_length`: checked
  by hand against the closed-form formula for a few (SR, SR*, skew,
  kurt) tuples.
- One integration test gated on a real `PAPER_API_KEY`/`PAPER_API_SECRET`
  testnet credential pair — skipped without one, same pattern already
  used for DB-gated tests in this suite.

## Verification (PROMPTS.md's own words)

"48h paper run against testnet, reconciliation populates, divergence
fires when cost model deliberately mis-specified." Given the 1d decision
cadence, a 48h window will show at most 1-2 real trading decisions per
champion — report that honestly rather than switching timeframes to
manufacture more activity (see cadence discussion above). What the 48h
window genuinely proves: the execution loop stays connected and polls
correctly every 15 minutes, real fills reconcile against real backtest
predictions, and a deliberately mis-specified cost model trips
`PAPER_DIVERGENCE` — not that any given champion generated many trades
in two days.

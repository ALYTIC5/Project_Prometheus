# Multi-Asset Data Provider Abstraction + ETF Adapter — Design

**Spec status:** approved in conversation, written up for record and for the
implementation plan to argue from. **Revised 2026-09-20**: the originally
approved ETF provider (Stooq) turned out to be a dead end — see below —
and was replaced with Alpaca before any code was written against it.

**Scope note:** this is sub-project 1 of a larger, explicitly decomposed
multi-asset data layer effort (the user's own "PROMPT 2 (REVISED)"). The
full effort is: (1) provider abstraction + ETF adapter — this spec, (2)
crypto adapter migration onto the same abstraction (+ folding in
CoinGecko/Coinpaprika to fix the existing Binance.US thin-liquidity
quarantine problem on 12 universe symbols), (3) forex adapter (ECB/
Frankfurter), (4) options snapshot collection (Tradier sandbox + Alpaca
indicative feed) + the options-flow feature built-but-dormant, (5)
per-asset-class benchmark, (6) law test / scheduling wiring threaded through
each step above rather than done as a separate lump. Single-stock data
stays an unimplemented interface stub (paid providers only) across all of
this — never `yfinance`, which is survivorship-biased and split-adjusted in
place.

## Goal

Add a provider-agnostic way to bring in a second, non-crypto asset class
(ETFs/indices) without touching the crypto ingestion path that just got
stabilized this session, and without re-inventing point-in-time storage,
quality checks, or versioning — all three already exist and are already
asset-class-agnostic.

## What already exists (discovered during brainstorming, not assumed)

The original prompt this is based on assumed a from-scratch data layer.
Reading the actual codebase found most of it already built:

- `data/schema.py` — the five-timestamp (`event_time`, `available_at`,
  `ingested_at`, `source`, `revision`) point-in-time schema and the
  structurally-enforced `PointInTimeFrame` accessor. Already asset-agnostic.
  Its `OHLCVBar` dataclass is the *feature-visible* shape (no source/
  revision) — the new provider abstraction does NOT return this type (see
  "New code" below for why).
- `data/quality.py` — gaps, duplicate timestamps, price validity, OHLC
  relationship, volume-spike (20σ), stale-bar checks. Already
  asset-agnostic, operates on any OHLCV polars frame.
- `data/versioning.py` — `record_data_version()` / `compute_content_hash()`,
  already wired into `ingestion.backfill()`. Needs widening (below), not
  rebuilding.
- `data/universe.py` — `as_of(session, date)` / `sync_from_yaml()` against a
  real `universe_membership` table with `listed_at`/`delisted_at`. Needs an
  asset-class filter (below), not rebuilding.
- `data/models.py` — `RawIngest`, `OhlcvBar`, `UniverseMembership`,
  `DataVersion` ORM models, all already asset-agnostic except
  `UniverseMembership` (no asset-class column yet).

So this sub-project is genuinely small: a provider abstraction, one real
adapter, two small extensions, one small migration, one new config file.

## Decisions made (with reasoning)

- **ETF provider: Alpaca, not Stooq.** Stooq (`stooq.com/q/d/l/`) was the
  original choice — a real, longstanding, keyless CSV endpoint by
  reputation and by web search — but a direct live check found it now
  requires solving a client-side JavaScript proof-of-work challenge
  (SHA-256 hashcash, POSTed to `/__verify`) before serving any data, on
  every request, confirmed with `curl` including a realistic browser
  User-Agent. This is a real, current anti-scraping measure, not a
  transient fluke or an artifact of missing headers — a plain server-side
  HTTP client cannot pass it, and replicating the challenge in Python
  would be circumventing an anti-bot measure on a site actively trying to
  block exactly this kind of programmatic access, which this project
  won't do. Alpaca's free tier requires one-time account signup (the
  user's original objection to it) but has a documented, stable, genuinely
  scriptable REST API — the realistic option once Stooq was ruled out live
  rather than assumed working.
- **`adjustment=raw` passed explicitly on every request, even though it's
  Alpaca's documented default.** Confirmed via Alpaca's own docs/forum
  posts: default is `raw` (unadjusted). Passed explicitly anyway — this
  parameter is exactly what separates honest point-in-time data from the
  "split-adjusted in place" problem the user's own spec calls out as the
  central reason `yfinance` is excluded. Never rely on an implicit default
  for something Law-adjacent; same posture as the migration's own
  `DEFAULT 'crypto' ... DROP DEFAULT` below.
- **`survivorship_safe=True`, `point_in_time=True` for Alpaca**, both
  cleanly true (not caveated the way the Stooq draft needed to be) —
  Alpaca is a real, documented, audited brokerage data feed, not a
  best-effort scrape.
- **Ingestion orchestration stays isolated (Approach B of three
  considered), not unified with crypto's `backfill()` yet.** Considered:
  (A) generalize `backfill()` now to take a `MarketDataProvider` and wrap
  ccxt as `CcxtProvider` alongside a new `AlpacaProvider`; (B) new,
  separate `data/ingest_etf.py` that reuses the existing
  quality/versioning/storage pipeline but doesn't touch `backfill()`/ccxt;
  (C) do both this sub-project and the crypto migration as one change.
  Rejected A: touches the crypto ingestion path that just got debugged and
  stabilized this session, for no benefit that isn't captured just as well
  one sub-project later. Rejected C: contradicts the phased decomposition
  the user already approved, largest blast radius. Chose B: strictly
  additive, the short-lived duplication between `backfill()` and
  `ingest_etf()` is resolved in sub-project 2 (already the next planned
  step, not deferred indefinitely).
- **One new dependency: none.** Alpaca's REST API is plain JSON over
  HTTPS with two header values for auth — `httpx` (already a dependency,
  used for arXiv ingestion) covers it. No `alpaca-py` SDK needed for a
  surface this small, same reasoning `research/llm/ingestion.py` already
  used to hand-roll arXiv's HTTP calls instead of installing an arxiv SDK.
- **`asset_class` as an explicit new column on `universe_membership`**, not
  inferred from `exchange`. Considered inferring from `exchange` (no
  migration needed: `exchange='binance'` implies crypto,
  `exchange='alpaca'` implies ETF) but rejected — conflates "data provider"
  with "asset class," which breaks the moment two asset classes share a
  provider (plausible once forex/options adapters exist). One small
  migration now is cheaper than an ambiguous column meaning forever.
- **Provider returns a new `RawBar`, not `schema.OHLCVBar`.** `OHLCVBar`
  already carries `available_at`, which implies ingestion-lag policy has
  already been applied — but that policy is an orchestration decision, not
  a provider concern, exactly matching how today's ccxt path works:
  `ingestion.py`'s `_INGESTION_LAG` constant and `ccxt_rows_to_bars()` live
  in the orchestration layer, not inside any exchange client. A provider
  only knows `(symbol, event_time, open, high, low, close, volume)`; the
  orchestrator (`ingest_etf.py`) computes `available_at`/`source`/
  `revision` the same way `ingest_symbol()` does today.

## Data model (new migration `0014`)

```sql
ALTER TABLE universe_membership ADD COLUMN asset_class VARCHAR(16) NOT NULL DEFAULT 'crypto';
ALTER TABLE universe_membership ALTER COLUMN asset_class DROP DEFAULT;
```

The `DEFAULT 'crypto'` exists only to backfill every existing row (all of
today's universe is crypto) without a manual data migration step; dropped
immediately after so future inserts must specify it explicitly, matching
this project's "no invented default that silently hides a real decision"
posture used elsewhere (e.g. `next_strategy_id`'s explicit family
validation).

No changes to `ohlcv_bars`, `raw_ingest`, or `data_versions` schemas —
`source` (already `VARCHAR(32)`) holds `'alpaca'` the same way it holds
`'binanceus'` today. `data_versions.source_versions` (already `JSONB`)
widens its Python-side shape only, no column/migration change:

```python
# Before: dict[str, str]                    {"binanceus": "v1"}
# After:  dict[str, dict[str, object]]      {"alpaca": {"version": "v2", "survivorship_safe": True, "point_in_time": True}}
```

## New code

- **`data/providers/base.py`** — `RawBar` dataclass + `MarketDataProvider`
  ABC:
  ```python
  @dataclass(frozen=True)
  class RawBar:
      symbol: str
      event_time: datetime
      open: float
      high: float
      low: float
      close: float
      volume: float

  class ProviderCapabilities(TypedDict):
      asset_classes: list[str]
      intervals: list[str]
      survivorship_safe: bool
      point_in_time: bool
      rate_limit: str  # human-readable, e.g. "200 req/min (free tier)"

  class MarketDataProvider(ABC):
      @abstractmethod
      def capabilities(self) -> ProviderCapabilities: ...
      @abstractmethod
      async def fetch_bars(
          self, symbols: list[str], start: datetime, end: datetime, interval: str
      ) -> list[RawBar]: ...
  ```
  No `fetch_chain()` on the ABC yet — YAGNI until sub-project 4 (options)
  actually needs it; adding a method later is a small, additive change to
  an internal interface with exactly one consumer today.

- **`data/providers/alpaca.py`** — `AlpacaProvider(MarketDataProvider)`.
  `fetch_bars()` calls `GET https://data.alpaca.markets/v2/stocks/bars`
  once per symbol (simpler than the API's multi-symbol pagination
  bookkeeping, and matches the one-fetch-per-symbol shape
  `ingestion.ingest_symbol()` already uses for crypto) with headers
  `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` (from `ALPACA_API_KEY`/
  `ALPACA_SECRET_KEY` env vars, read at call time not import time — same
  "importing this module never requires the key to be set" posture
  `worker._anthropic_client()` already uses), params
  `timeframe=1Day, start, end, adjustment=raw, limit=10000`, following
  `next_page_token` until it's null. Parses each `{"t","o","h","l","c","v"}`
  bar into a `RawBar` (drops `n`/`vw`, not needed). `capabilities()`
  returns `survivorship_safe=True, point_in_time=True,
  asset_classes=["etf"], intervals=["1d"]`.

- **`data/ingest_etf.py`** — `backfill_etf(days: int) -> None`, mirroring
  `ingestion.backfill()`'s shape but provider-driven:
  1. `universe.sync_from_yaml(session, "config/universe_etf.yaml", asset_class="etf")`
  2. `record_config_snapshot(session, "config/universe_etf.yaml")` — same
     Law-adjacent audit trail `backfill()` already keeps for
     `config/universe.yaml`
  3. `AlpacaProvider().fetch_bars(symbols, since, now, "1d")`, one symbol
     at a time (matching crypto's per-symbol shape)
  4. per symbol: compute `available_at = event_time + timedelta(minutes=5)`
     (same fixed lag `ingestion._INGESTION_LAG` uses — a provider's daily
     bar is knowable shortly after close, not instantly), attach
     `source="alpaca"`, `revision=1`
  5. `quality.run_quality_checks()` (small, targeted extension — see
     below) per symbol; a
     failing symbol is quarantined (raw status recorded, no bars written)
     and ingestion continues to the next symbol, same as `ingest_symbol()`
  6. store passing bars into `ohlcv_bars` via the *existing*
     `_INSERT_BAR`-shaped query (same table, same unique constraint) —
     small, self-contained insert helper local to this module, not a
     shared import from `ingestion.py` (Approach B: no changes to that
     file this sub-project)
  7. Law 3: the same holdout-cutoff split `ingest_symbol()` performs
     (`event_time >= holdout_start` → `holdout.ohlcv_bars` instead of
     `ohlcv_bars`) — duplicated here deliberately, not extracted into a
     shared helper this sub-project, to keep the diff to `ingestion.py` at
     zero (see "Decisions made" above); revisit in sub-project 2
  8. `versioning.record_data_version()` with the widened
     `source_versions` shape

- **`data/providers/stocks.py`** — `StockProvider` interface stub only
  (2.3e). Raises `NotImplementedError` from `fetch_bars()`, with a
  docstring naming Polygon/Sharadar/Tiingo as the paid providers that
  would satisfy `survivorship_safe=True`, and explicitly warning against
  `yfinance` for the reasons already established. No tests beyond "it
  exists and matches the ABC signature" — there's no behavior to test.

- **`config/universe_etf.yaml`** — same shape as `config/universe.yaml`
  (`symbol`/`exchange`/`listed_at`/`delisted_at`), `exchange: alpaca` for
  every row, the 28-symbol list from the prompt with real, verified
  inception dates (stockanalysis.com, spot-checked 10/28 live rather than
  assumed from memory): SPY (1993-01-22), QQQ (1999-03-10),
  IWM (2000-05-22), DIA (1998-01-14); the 11 SPDR sectors, all listed
  1998-12-16 except XLRE (2015-10-07) and XLC (2018-06-18); bond/commodity/
  currency/international ETFs TLT/IEF/LQD (2002-07-22), HYG (2007-04-04),
  GLD (2004-11-18), SLV (2006-04-21), USO (2006-04-10), UNG (2007-04-18),
  UUP (2007-02-20), FXE (2005-12-09), EEM (2003-04-07), EFA (2001-08-14),
  VNQ (2004-09-23). `listed_at` set to these real dates so `as_of()`
  reconstruction is meaningful from day one rather than defaulting every
  row to "today."

## Extended (small)

- **`data/quality.py` — `check_gaps()`/`run_quality_checks()` gain an
  optional `max_gap_hours: float | None = None` parameter (default
  preserves today's crypto behavior exactly, zero risk to the existing
  path).** Found while writing the implementation plan, not in the
  original design: `check_gaps()`'s expected-hours-per-bar math
  (`_BAR_HOURS["1d"] = 24`) assumes a bar every 24 hours, which is true
  for crypto's 24/7 market but false for equities/ETFs — a normal Friday
  close to Monday open gap is ~65 hours, and a 3-day holiday weekend is
  ~96 hours. Calling `run_quality_checks()` truly unchanged against real
  Alpaca daily bars would quarantine *every* real ingestion on its very
  first weekend gap. `ingest_etf.py` passes `max_gap_hours=100.0`
  (comfortably above a 3-day weekend, still catches a genuinely broken
  4+ day outage) explicitly; every existing crypto call site passes
  nothing and keeps its current, unchanged threshold.
- **`data/versioning.py`** — `record_data_version()`'s `source_versions`
  parameter type widens as shown above. `compute_content_hash()` is
  unchanged (already asset-agnostic).
- **`data/universe.py`** — `as_of(session, as_of_date, asset_class: str)`
  gains a required `asset_class` filter (required, not optional with a
  default — every real caller already knows which asset class it wants;
  an optional default would silently mix classes for a caller that forgot
  to pass one). `sync_from_yaml(session, path, asset_class: str)` gains
  the same required param. **Every existing call site
  (`tests/laws/test_survivorship.py`, `ingestion.backfill()`) is updated
  to pass `"crypto"` explicitly** — this is a breaking signature change to
  an existing function, not purely additive, and the plan must update
  those call sites in the same task that changes the signature.
- **New test in `tests/laws/test_survivorship.py`**: proves the new
  `asset_class` filter actually isolates the two universes — an ETF
  symbol never appears in a crypto `as_of()` query and vice versa. This is
  the one genuinely new law-relevant guarantee this sub-project
  introduces to that file.
  `tests/laws/test_no_lookahead.py` is **not** extended: on inspection it
  is pure synthetic in-memory data with no DB and no asset-class-specific
  logic at all (`PointInTimeFrame.as_of()` doesn't know or care what a
  symbol string means) — the original spec draft's plan to parametrize it
  for ETF would have tested nothing new. Recorded here so the omission
  reads as a decision, not an oversight.

## Testing

- `tests/test_providers_alpaca.py` — `AlpacaProvider.fetch_bars()` against
  mocked `httpx` responses (a realistic captured Alpaca JSON page shape,
  including a `next_page_token` case to prove pagination is actually
  followed), asserting correct `RawBar` construction and auth headers
  sent. No live network call, no real API key needed to run the suite.
- `tests/test_ingest_etf.py` — `db`-marked, skipped locally without
  `TEST_DATABASE_URL`, same convention as `test_population.py` /
  `test_queue_semantics.py`. Asserts `backfill_etf()` writes real rows
  through the *existing* quality/versioning pipeline, using a fake
  provider (not live Alpaca) so the test suite never depends on external
  network availability or a real API key.
- Law test extension as described above.
- `docs/DEPENDENCIES.md`: no new entry (zero new dependencies).

## Verification

```
alembic upgrade head
pytest tests/test_providers_alpaca.py -v
TEST_DATABASE_URL=... pytest tests/test_ingest_etf.py tests/laws/test_survivorship.py -v
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python -m prometheus.data.ingest_etf --days 2000   # manual CLI smoke test, needs real keys
```

Dashboard: no dashboard change in this sub-project. `DATA` section showing
per-asset-class row counts/provider flags (the prompt's original
verification step) is a natural follow-up once sub-project 2 (crypto
migration) exists too and there are genuinely two asset classes to compare
— building it against one asset class alone would just reproduce what
`/buildings/`'s existing `library` row_count already shows.

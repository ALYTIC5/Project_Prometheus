# Multi-Asset Data Provider Abstraction + ETF Adapter — Design

**Spec status:** approved in conversation, written up for record and for the
implementation plan to argue from.

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

- **ETF provider: Stooq, not Alpaca.** Alpaca's free tier still requires
  account signup; the user wants a genuinely keyless option to start today.
  Stooq (`stooq.com/q/d/l/`) is a real, longstanding, keyless CSV endpoint
  used across the quant-python community (QuantStart, common
  backtrader/zipline data source) — confirmed via web search, not assumed.
  Its split/dividend-adjustment and data-quality practices aren't
  independently audited like a paid vendor's; for the large, liquid,
  index-tracking ETFs in this universe (SPY, sector SPDRs, etc.) that's
  low real risk, but the capability flags below record this honestly
  rather than optimistically.
- **`survivorship_safe=True`, `point_in_time=True` for Stooq, with a
  documented caveat, not a blind True.** These flags are LAW-adjacent
  (Law 1/2) and propagate into every backtest result via `data_version`.
  Recording them as true "because it's probably fine" without the caveat
  in the adapter's own docstring would be the kind of silent optimism
  CLAUDE.md's cost/quality discipline exists to prevent.
- **Ingestion orchestration stays isolated (Approach B of three
  considered), not unified with crypto's `backfill()` yet.** Considered:
  (A) generalize `backfill()` now to take a `MarketDataProvider` and wrap
  ccxt as `CcxtProvider` alongside a new `StooqProvider`; (B) new, separate
  `data/ingest_etf.py` that reuses the existing quality/versioning/storage
  pipeline but doesn't touch `backfill()`/ccxt; (C) do both this
  sub-project and the crypto migration as one change. Rejected A: touches
  the crypto ingestion path that just got debugged and stabilized this
  session, for no benefit that isn't captured just as well one sub-project
  later. Rejected C: contradicts the phased decomposition the user already
  approved, largest blast radius. Chose B: strictly additive, the
  short-lived duplication between `backfill()` and `ingest_etf()` is
  resolved in sub-project 2 (already the next planned step, not deferred
  indefinitely).
- **No new dependency.** Stooq is a plain CSV-over-HTTP GET, no auth, no
  SDK. `httpx` is already a dependency (arXiv ingestion). Zero new entries
  in `docs/DEPENDENCIES.md`.
- **`asset_class` as an explicit new column on `universe_membership`**, not
  inferred from `exchange`. Considered inferring from `exchange` (no
  migration needed: `exchange='binance'` implies crypto,
  `exchange='stooq'` implies ETF) but rejected — conflates "data provider"
  with "asset class," which breaks the moment two asset classes share a
  provider (plausible once forex/options adapters exist). One small
  migration now is cheaper than an ambiguous column meaning forever.

## Data model (new migration)

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
`source` (already `VARCHAR(32)`) holds `'stooq'` the same way it holds
`'binanceus'` today. `data_versions.source_versions` (already `JSONB`)
widens its Python-side shape only, no column/migration change:

```python
# Before: dict[str, str]                    {"binanceus": "v1"}
# After:  dict[str, dict[str, object]]      {"stooq": {"version": "v1", "survivorship_safe": True, "point_in_time": True}}
```

## New code

- **`data/providers/base.py`** — `MarketDataProvider` ABC:
  ```python
  class ProviderCapabilities(TypedDict):
      asset_classes: list[str]
      intervals: list[str]
      survivorship_safe: bool
      point_in_time: bool
      rate_limit: str  # human-readable, e.g. "no documented limit"

  class MarketDataProvider(ABC):
      @abstractmethod
      def capabilities(self) -> ProviderCapabilities: ...
      @abstractmethod
      async def fetch_bars(
          self, symbols: list[str], start: datetime, end: datetime, interval: str
      ) -> list[OHLCVBar]: ...  # OHLCVBar already defined in data/schema.py
  ```
  No `fetch_chain()` on the ABC yet — YAGNI until sub-project 4 (options)
  actually needs it; adding a method later is a small, additive change to
  an internal interface with exactly one consumer today.

- **`data/providers/stooq.py`** — `StooqProvider(MarketDataProvider)`.
  `fetch_bars()` does one `httpx` GET per symbol against
  `https://stooq.com/q/d/l/?s={symbol}.us&i=d`, parses the CSV response
  (Date,Open,High,Low,Close,Volume) into `OHLCVBar` rows, applies the same
  fixed ingestion-lag convention `ingestion.ccxt_rows_to_bars()` already
  uses for `available_at`. `capabilities()` returns
  `survivorship_safe=True, point_in_time=True` with the caveat above in
  its own docstring, `asset_classes=["etf"]`, `intervals=["1d"]`.

- **`data/ingest_etf.py`** — `backfill_etf(days: int) -> None`, mirroring
  `ingestion.backfill()`'s shape but provider-driven:
  1. `universe.sync_from_yaml(session, "config/universe_etf.yaml")`
     (asset_class="etf" now that the column exists)
  2. `StooqProvider().fetch_bars(symbols, since, now, "1d")`
  3. `quality.run_quality_checks()` (reused unchanged) per symbol
  4. store passing bars into `ohlcv_bars` (reused `_INSERT_BAR`-shaped
     query, same table)
  5. `versioning.record_data_version()` with the widened
     `source_versions` shape

- **`data/providers/stocks.py`** — `StockProvider` interface stub only
  (2.3e). Raises `NotImplementedError` from `fetch_bars()`, with a
  docstring naming Polygon/Sharadar/Tiingo as the paid providers that
  would satisfy `survivorship_safe=True`, and explicitly warning against
  `yfinance` for the reasons already established. No tests beyond "it
  exists and matches the ABC signature" — there's no behavior to test.

- **`config/universe_etf.yaml`** — same shape as `config/universe.yaml`
  (`symbol`/`exchange`/`listed_at`/`delisted_at`), `exchange: stooq` for
  every row, the 28-symbol list from the prompt: SPY QQQ IWM DIA, the 11
  SPDR sectors (XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC), and
  TLT IEF HYG LQD GLD SLV USO UNG UUP FXE EEM EFA VNQ. `listed_at` set to
  each ETF's real inception date (public information, not invented) so
  `as_of()` reconstruction is meaningful from day one rather than
  defaulting every row to "today."

## Extended (small)

- **`data/versioning.py`** — `record_data_version()`'s `source_versions`
  parameter type widens as shown above. `compute_content_hash()` is
  unchanged (already asset-agnostic).
- **`data/universe.py`** — `as_of(session, as_of_date, asset_class: str)`
  gains a required `asset_class` filter (required, not optional with a
  default — every real caller already knows which asset class it wants;
  an optional default would silently mix classes for a caller that forgot
  to pass one). `sync_from_yaml()` gains an `asset_class` param, read from
  each YAML row going forward rather than hardcoded per call, so one
  function still serves both `config/universe.yaml` (crypto) and
  `config/universe_etf.yaml`.
- **`tests/laws/test_no_lookahead.py`** — the existing 200-random-pair
  truncation-proof parametrized to also run against ETF bars once
  `ingest_etf` has run in the test fixture, not a separate duplicated test.
- **`tests/laws/test_survivorship.py`** — extended the same way: assert an
  `as_of()` query for a historical ETF date behaves correctly (even though
  today's 28-symbol ETF universe has no real delisted members yet — the
  test asserts the *mechanism* works per asset class, same posture as the
  crypto test seeding known-dead pairs).

## Testing

- `tests/test_providers_stooq.py` — `StooqProvider.fetch_bars()` against a
  mocked `httpx` response (a real captured Stooq CSV sample), asserting
  correct `OHLCVBar` construction, `available_at` lag, and error handling
  on a malformed/empty CSV. No live network call in the test suite.
- `tests/test_ingest_etf.py` — `db`-marked, skipped locally without
  `TEST_DATABASE_URL`, same convention as `test_population.py` /
  `test_queue_semantics.py`. Asserts `backfill_etf()` writes real rows
  through the *existing* quality/versioning pipeline, using a fake
  provider (not live Stooq) so the test suite never depends on external
  network availability.
- Law test extensions as described above.
- `docs/DEPENDENCIES.md`: no new entry (zero new dependencies).

## Verification

```
alembic upgrade head
pytest tests/test_providers_stooq.py -v
TEST_DATABASE_URL=... pytest tests/test_ingest_etf.py tests/laws/ -v
python -m prometheus.data.ingest_etf --days 2000   # manual CLI smoke test
```

Dashboard: no dashboard change in this sub-project. `DATA` section showing
per-asset-class row counts/provider flags (the prompt's original
verification step) is a natural follow-up once sub-project 2 (crypto
migration) exists too and there are genuinely two asset classes to compare
— building it against one asset class alone would just reproduce what
`/buildings/`'s existing `library` row_count already shows.

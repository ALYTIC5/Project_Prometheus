# <Family Name> (STRATEGYSPEC_FAMILY_CONSTANT)

**Registered:** YYYY-MM-DD, before any backtest of this family has run.

## Hypothesis

<Plain-language economic or behavioral reason this signal might predict
returns. Not "it's a well-known indicator" -- why would this specific
price/volume pattern precede a real move.>

## Source

<Citation: author, paper/book, year. Or, honestly: "no citation --
novel construction, not adapted from existing literature.">

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `<field_name>` | `<value1, value2, ...>` | <why these specific values, e.g. "the construction's own standard default plus nearby cited variants"> |

Fixed here. A later desire to explore a different range is a **new**
registration doc, never an edit to this one after results are seen.

## Expected horizon

<Integer, and why -- matches `StrategySpec.expected_horizon`'s own
"real input to decay testing, not decoration" requirement.>

## Benchmark

<Which Law 8 buy-and-hold this family is measured against -- almost
always "this family's own single symbol's €1,000 buy-and-hold," stated
explicitly only when it's genuinely something else.>

## Data requirements

<What OHLCV/other data this needs, and confirmation it's available in
this project's existing ingestion (ccxt crypto, Alpaca ETF, or -- if
neither -- an honest statement that new data infrastructure is needed
first, and a pointer to `docs/DEFERRED.md` if this family is blocked on
that.)>

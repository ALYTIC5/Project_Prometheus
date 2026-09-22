# CHANDELIER_EXIT

**Registered:** 2026-09-22, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #15: Chandelier Exit trailing stop as a standalone
signal. Long whenever close is above a trailing stop set `multiplier`
ATRs below the highest high of the lookback window, flat otherwise.

Implemented as the simple, commonly-used STATELESS form: the stop is
recomputed fresh every bar from the window's own current high, not
ratcheted/remembered across bars. Some descriptions of Chandelier Exit
use a stop that only ever moves in the trade's favor (a stateful
variant) -- that is a real, separate construction this family does not
claim to be, stated explicitly to avoid overclaiming.

## Source

Chuck LeBeau, publicly documented and widely cited in technical-analysis
literature (originally popularized via LeBeau's newsletter/software
work, no single peer-reviewed paper).

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `chandelier_lookback`, `chandelier_multiplier` | lookback `14, 22`; multiplier `2.0, 3.0` | LeBeau's own default (22-day lookback, 3.0x ATR multiplier), plus a shorter-lookback and a tighter-multiplier variant. |

## Expected horizon

The lookback.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV high/low/close -- already available.

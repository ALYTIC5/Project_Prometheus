# RSI(2) Connors grid addition (FAMILY_RSI)

**Registered:** 2026-09-21, before any backtest of this grid has run.

## Note on scope

This is not a new family -- it reuses the existing `FAMILY_RSI`
(`prometheus/strategy/spec.py`), which already parameterizes
`rsi_lookback`/`rsi_oversold` generically. It is documented here as its
own registration, per `docs/strategies/README.md`'s own rule ("If a
later experiment wants a different range, that is a new registration,
not an edit to this one after the fact") -- `rsi_lookback=2` with an
extreme oversold threshold is a genuinely distinct, separately-cited
parameter regime from the existing RSI grid's `(7, 14, 21)` lookbacks
and classic 20-30 oversold zone, not a widening of it.

## Hypothesis

STRATEGIES_100.md #21: "RSI(2) Connors" -- "Classic short-term ETF
edge." A very short (2-period) RSI reaching an extreme reading is a
stronger, faster-firing mean-reversion signal than the classic 14-period
RSI, at the cost of far more noise -- hence the much lower (more
extreme) oversold threshold than Wilder's classic 30.

## Source

Larry Connors, "Short-Term Trading Strategies That Work" (2008) -- his
own published 2-period RSI construction with extreme oversold zones.

## Parameters

| Field (StrategySpec) | Grid values | Rationale |
|---|---|---|
| `rsi_lookback` | fixed `2` | Connors' own defining parameter -- not swept, since "RSI(2)" is the construction's own name. |
| `rsi_oversold` | `10.0, 5.0` | Connors' own two most commonly cited extreme oversold variants. |

## Expected horizon

Fixed at 2, matching `rsi_lookback` per this project's own "a
mean-reversion signal's own lookback is its horizon claim" convention.

## Benchmark

This family's own single symbol's €1,000 buy-and-hold.

## Data requirements

OHLCV close only -- already available.

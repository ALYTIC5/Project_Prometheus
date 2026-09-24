# ACCELERATING_DUAL_MOMENTUM

**Registered:** 2026-09-24, before any backtest of this family has run.

## Hypothesis

STRATEGIES_100.md #56: Accelerating Dual Momentum. The same absolute/
relative momentum switch DUAL_MOMENTUM_GEM uses (hold the strongest
equity leg only if its own momentum is positive, else the defensive
leg), scored on the AVERAGE of 1/3/6-month trailing returns rather than
a single 12-month return -- reacts faster to regime changes.

## Source

Chris Ludlow & Steve Hanly, "Using Combined Momentum Signals to
Generate Better Risk Adjusted Returns" (2018). QQQ substitutes for the
paper's own preferred aggressive-growth equity vehicle (the paper's own
motivation is a faster-reacting, more concentrated growth exposure than
plain SPY).

## Parameters

No swept parameters -- the 1/3/6-month sub-lookbacks (21/63/126 trading
days) are fixed by the construction's own definition, matching
DUAL_MOMENTUM_GEM's own single-grid-entry precedent.

## Universe

`(QQQ, EFA, IEF)` -- last position is always the defensive leg, same
convention as DUAL_MOMENTUM_GEM.

## Expected horizon

Monthly (21 trading days).

## Benchmark

Equal-weight buy-and-hold of the same universe.

## Data requirements

OHLCV close, all symbols already ingested.

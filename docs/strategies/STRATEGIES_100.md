# 100 Strategies for Prometheus

## Data tags

| Tag | Meaning |
|---|---|
| ✅ | Testable now on your daily ETF + crypto OHLCV |
| 🔄 | Cross-sectional — needs a universe; works on your ~30 ETFs |
| ⏳ | Needs options snapshots — collecting forward, not testable yet |
| ❌ | Needs data you don't have (intraday, fundamentals, constituents, futures) |

**Read before implementing:** many of these are near-duplicates of each other.
SMA / EMA / DEMA / TEMA / Hull crossovers are largely the same signal. If the
system treats them as independent discoveries, one real effect will show up as
five "winners." The prompt at the bottom adds correlation clustering to stop
that.

---

## 1. Trend / time-series momentum (20)

| # | Strategy | Data | Note |
|---|---|---|---|
| 1 | EMA crossover | ✅ | |
| 2 | Triple moving-average alignment | ✅ | |
| 3 | DEMA / TEMA crossover | ✅ | Near-duplicate of 1 |
| 4 | Hull moving-average trend | ✅ | Near-duplicate of 1 |
| 5 | KAMA (Kaufman adaptive MA) trend | ✅ | Adapts to noise |
| 6 | MACD signal-line cross | ✅ | |
| 7 | MACD histogram zero-cross | ✅ | |
| 8 | Time-series momentum, 12-1 month | ✅ | Moskowitz, Ooi & Pedersen 2012 |
| 9 | Turtle system (20/55 breakout, 10/20 exit) | ✅ | |
| 10 | ADX + DI crossover | ✅ | |
| 11 | Aroon oscillator cross | ✅ | |
| 12 | Parabolic SAR | ✅ | |
| 13 | Supertrend | ✅ | |
| 14 | Ichimoku cloud breakout | ✅ | Many parameters — overfit risk |
| 15 | Vortex indicator | ✅ | |
| 16 | Linear regression slope | ✅ | |
| 17 | Keltner channel breakout | ✅ | |
| 18 | Chandelier-exit trend following | ✅ | |
| 19 | Price above/below 200-day SMA filter | ✅ | Simple and robust baseline |
| 20 | Moving-average ribbon expansion | ✅ | |

## 2. Mean reversion (18)

| # | Strategy | Data | Note |
|---|---|---|---|
| 21 | RSI(2) Connors | ✅ | Classic short-term ETF edge |
| 22 | RSI(14) overbought/oversold | ✅ | |
| 23 | Stochastic oscillator | ✅ | |
| 24 | Williams %R | ✅ | Near-duplicate of 23 |
| 25 | CCI reversion | ✅ | |
| 26 | Rolling z-score of price | ✅ | |
| 27 | Internal bar strength (IBS) | ✅ | Close position in day's range |
| 28 | N-day low reversal | ✅ | |
| 29 | Consecutive down-days | ✅ | |
| 30 | Distance-from-200-SMA reversion | ✅ | |
| 31 | Ultimate oscillator | ✅ | |
| 32 | Money Flow Index | ✅ | Uses volume |
| 33 | Keltner channel reversion | ✅ | Inverse of 17 |
| 34 | Bollinger %B reversion | ✅ | Variant of your existing BOLLINGER |
| 35 | Gap-fade (open vs prior close) | ✅ | Uses daily open |
| 36 | Short-term reversal, 1-week | 🔄 | |
| 37 | Overextension from VWAP | ❌ | Needs intraday |
| 38 | Opening-gap reversion intraday | ❌ | Needs intraday |

## 3. Volatility (10)

| # | Strategy | Data | Note |
|---|---|---|---|
| 39 | Bollinger squeeze breakout | ✅ | |
| 40 | ATR breakout | ✅ | |
| 41 | NR7 (narrowest range of 7) | ✅ | Toby Crabel |
| 42 | Inside-bar breakout | ✅ | |
| 43 | Realised-volatility regime switch | ✅ | |
| 44 | Volatility-targeting overlay | ✅ | Wraps any other strategy |
| 45 | Vol-of-vol filter | ✅ | |
| 46 | Low-volatility anomaly | 🔄 | Rank ETFs by vol |
| 47 | Opening range breakout | ❌ | Needs intraday |
| 48 | VIX term-structure | ❌ | Needs VIX futures |

## 4. Cross-sectional rotation — your ETF universe (16)

This is where your sector-rotation video lives. Your 11 SPDR sectors plus
bonds, gold and commodities make this the strongest honestly-testable family.

| # | Strategy | Data | Note |
|---|---|---|---|
| 49 | Sector momentum rotation (top N of 11) | 🔄 | The video idea, price-only |
| 50 | Dual momentum (GEM) | 🔄 | Gary Antonacci |
| 51 | Relative-strength top-3 ranking | 🔄 | |
| 52 | Sector mean reversion (buy worst) | 🔄 | Inverse of 49 |
| 53 | GTAA 10-month SMA timing | 🔄 | Mebane Faber 2007 |
| 54 | Defensive Asset Allocation | 🔄 | Keller & Keuning |
| 55 | Protective Asset Allocation | 🔄 | Keller & Keuning |
| 56 | Accelerating dual momentum | 🔄 | |
| 57 | Risk parity (inverse volatility) | 🔄 | |
| 58 | Minimum variance | 🔄 | |
| 59 | Equal-weight rebalance | 🔄 | Important baseline |
| 60 | 52-week-high proximity | 🔄 | George & Hwang 2004 |
| 61 | Cross-asset trend (equity/bond/gold) | 🔄 | |
| 62 | Residual momentum (beta-adjusted) | 🔄 | Approximate with SPY beta |
| 63 | Breadth-based rotation | ❌ | Needs index constituents |
| 64 | Earnings-revision momentum | ❌ | Needs fundamentals |

## 5. Pairs and statistical arbitrage (8)

| # | Strategy | Data | Note |
|---|---|---|---|
| 65 | Cointegration pairs (e.g. GLD/SLV) | ✅ | |
| 66 | Distance-method pairs | ✅ | |
| 67 | Ratio mean reversion (SPY/TLT) | ✅ | |
| 68 | Kalman-filter dynamic hedge ratio | ✅ | |
| 69 | Sector-vs-market spread | ✅ | |
| 70 | BTC/ETH ratio reversion | ✅ | |
| 71 | Energy sector vs oil (XLE/USO) | ✅ | |
| 72 | Crypto cross-exchange basis | ❌ | Needs multi-venue data |

## 6. Macro and regime (8)

| # | Strategy | Data | Note |
|---|---|---|---|
| 73 | Stock/bond rotation on momentum | ✅ | |
| 74 | Risk-on/off via HYG/LQD ratio | ✅ | Credit spread proxy |
| 75 | Gold/equity switch | ✅ | |
| 76 | Dollar trend overlay (UUP) | ✅ | |
| 77 | Yield-curve proxy (TLT/IEF) | ✅ | |
| 78 | Hidden Markov regime switching | ✅ | Easy to overfit — regime layer must itself be validated |
| 79 | Correlation-breakdown risk-off | 🔄 | |
| 80 | Macro surprise index | ❌ | Needs economic release data |

## 7. Calendar and seasonality (8)

| # | Strategy | Data | Note |
|---|---|---|---|
| 81 | Turn-of-month effect | ✅ | |
| 82 | Day-of-week effect | ✅ | Heavily data-mined historically |
| 83 | Halloween / Sell-in-May | ✅ | Bouman & Jacobsen 2002 |
| 84 | Pre-holiday effect | ✅ | |
| 85 | Overnight vs intraday return split | ✅ | Uses daily open and close |
| 86 | Month-end rebalancing flows | ✅ | |
| 87 | Pre-FOMC drift | ✅ | Needs FOMC calendar (free, static); Lucca & Moench 2015 |
| 88 | Crypto weekend effect | ✅ | |

## 8. Volume-based (4)

| # | Strategy | Data | Note |
|---|---|---|---|
| 89 | On-Balance Volume trend | ✅ | |
| 90 | Chaikin money flow | ✅ | |
| 91 | Volume-confirmed breakout | ✅ | |
| 92 | Price/volume divergence | ✅ | |

## 9. Machine learning model families (4)

Read this: on ~2,000 daily bars, ML models overfit very easily. Random forest
already in your system will mostly fail PBO. That's the harness working, not
the model being wrong. Expect most of these to be rejected.

| # | Strategy | Data | Note |
|---|---|---|---|
| 93 | Gradient boosting (LightGBM) | ✅ | Strictest PBO scrutiny |
| 94 | Regularised logistic regression | ✅ | Often beats trees on small data |
| 95 | k-NN pattern matching | ✅ | |
| 96 | Stacked ensemble of rule strategies | ✅ | Combines survivors, doesn't find new edges |

Deliberately excluded: LSTM and transformers. Far too data-hungry for daily
bars — they will overfit almost by construction.

## 10. Options-derived — collecting forward (4)

| # | Strategy | Data | Note |
|---|---|---|---|
| 97 | Price vs positioning divergence | ⏳ | **Your "follow the big money" video** |
| 98 | Put/call ratio contrarian | ⏳ | |
| 99 | IV rank mean reversion | ⏳ | |
| 100 | Open-interest change momentum | ⏳ | |

---

## Count

| Tag | Count |
|---|---|
| ✅ Testable now | 72 |
| 🔄 Needs universe (you have it) | 17 |
| ⏳ Options, waiting on history | 4 |
| ❌ Missing data | 7 |

**89 are testable today.**

---

# THE CLAUDE CODE PROMPT

```
Add new strategy families to the research engine. Read CLAUDE.md and
docs/strategies/STRATEGIES_100.md.

Do NOT implement all 100 at once. Adding strategies raises the cumulative trial
count, and Deflated Sharpe tightens for EVERY strategy as that count grows.
That is correct behaviour and must not be worked around.

## Step 0 — Report before building

  - List strategy families currently in StrategySpec.
  - Report the current cumulative trial count and the DSR significance
    threshold it implies.
  - Confirm the null suite exists (coin flip, random entry/exit, pure noise,
    1000 seeds, asserting no positive Sharpe after costs at p<0.05). If it does
    NOT exist, STOP and build it first. Adding 89 strategies to an engine that
    has never been proven unable to make noise look profitable is building on
    sand.
  - Confirm the placebo component test exists for the ablation harness.
  Report all four, then wait for my go-ahead.

## Step 1 — Correlation clustering (build before adding strategies)

  research/clustering.py — compute pairwise correlation of strategy RETURN
  STREAMS across the backtest window. Cluster strategies above a correlation
  threshold (configurable, in research policy).

  A cluster counts as ONE discovery for promotion purposes. If SMA, EMA, DEMA
  and Hull crossovers all "pass," that is one real effect found five ways, not
  five edges. Only the simplest member of a cluster (fewest parameters) is
  eligible for CHAMPION; the rest are marked as redundant variants and kept in
  lineage.

  Surface clusters on the dashboard so redundancy is visible.

## Step 2 — Pre-registration

  Every new family gets a docs/strategies/<family>.md written BEFORE its first
  backtest: the hypothesis, the source, the parameter ranges, and the expected
  horizon. Parameter ranges are fixed at registration. Widening them after
  seeing results is a RESEARCH_VIOLATION under Law 7.

## Step 3 — Implement in batches, in this order

  Stop after each batch, report results, wait for approval.

  Batch A — Cross-sectional rotation (#49-62)
    The strongest honestly-testable family on the ETF universe. Implement a
    cross-sectional ranking primitive first; most of these share it.
    Include #59 equal-weight as the baseline every rotation strategy must beat.

  Batch B — Mean reversion (#21-36)
    RSI(2) and IBS are the most-cited short-horizon ETF edges.

  Batch C — Trend (#1-20)
    Expect heavy clustering. Most of these collapse to 2-3 real effects.

  Batch D — Volatility, pairs, macro (#39-46, #65-71, #73-79)
    #44 volatility targeting is an OVERLAY that wraps other strategies, not a
    standalone family. Model it as a composable transform.
    #78 HMM: the regime classifier itself must be validated out of sample,
    or it becomes another overfit layer.

  Batch E — Calendar and volume (#81-92)
    Calendar effects are among the most data-mined in finance. Expect DSR to
    reject most of them — correctly.

  Batch F — ML (#93-96)
    Last. Strictest scrutiny. Every model gets its features computed ONLY
    through PointInTimeFrame.as_of(). Any feature normalisation (z-scoring,
    scaling) must be fit on the training fold only — fitting on the full
    series is look-ahead and the truncation-proof test must cover it.

  Batch G — Options (#97-100)
    Implement the feature code now, register with has_history = FALSE, and let
    the system refuse to promote until enough forward snapshots exist.

  Skip every ❌ strategy. Document each in docs/strategies/DEFERRED.md with the
  data source it would need.

## Step 4 — Per-family requirements

  Every family must:
  - Declare expected_horizon, so Prompt 5's split sizing and decay test apply.
  - Declare its matching benchmark (SPY for equity rotation, BTC for crypto,
    60/40 for multi-asset). Per-asset-class, never a single global benchmark.
  - Pass the null suite with its own signal replaced by noise.
  - Record parameter count, so the complexity penalty applies.
  - Carry at least one citation or stated rationale in its registration doc.

## Step 5 — Report honestly after each batch

  For each batch: how many strategies, how many parameter combinations, the new
  cumulative trial count, the new DSR threshold, how many survived, how many
  clusters they collapsed into, and how many beat their benchmark after costs.

  "Zero survived" is a valid and useful result. Report it plainly.
```

---

## What to expect

Most of these will fail. That's the point. A quant shop testing 100 classic
strategies on daily ETF data would expect perhaps a handful to survive honest
out-of-sample testing, and several of those to collapse into the same cluster.

If dozens pass, be suspicious of the engine before you celebrate the results.

---

## Session log: Step 0 + Step 1 (2026-09-21)

**Step 0 report** (given to the user, reproduced here for the record):

- Families in `StrategySpec` at the time this prompt was received: 17
  (13 classic + 4 ML -- see `prometheus/strategy/spec.py`'s own module
  docstring for the full, current list, which has continued to grow
  independently of this prompt).
- Cumulative trial count: `SELECT COUNT(*) FROM results` = **1,530**
  (confirmed live in production).
- DSR at that trial count (verified against the real
  `deflated_sharpe_ratio` function, not estimated): a raw Sharpe of 0.5
  deflates to ~0.00 (probability of real skill); 1.0 -> ~0.67; 1.5+
  saturates near 1.0. Today's real bar is roughly "need a ~1.0+ Sharpe."
- Null suite: confirmed exists and correct
  (`tests/test_null_strategies.py`, 1000 seeds, coin-flip/random-entry-
  exit/pure-lagged-noise, p<0.05).
- Placebo test: confirmed exists and correct
  (`tests/test_ablation_placebo.py`).

Go-ahead received. Step 1 (`research/clustering.py`, real correlation
clustering, `GET /clusters/`, `ClustersSection.tsx`) shipped -- see that
module's own docstring for what's built and
`docs/DEFERRED.md`'s "Correlation clustering not yet gating CHAMPION
eligibility" entry for the one piece (promotion-eligibility gating)
deliberately left for separate, more carefully reviewed follow-up.

Batches A-G have **not** started. Each still needs its own explicit
go-ahead per this prompt's own text ("Stop after each batch, report
results, wait for approval").

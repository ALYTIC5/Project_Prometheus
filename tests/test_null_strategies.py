"""Falsification before generation (CLAUDE.md, non-negotiable): CLAUDE.md's
own words -- this and the Prompt 6 placebo test are "the two places this
project can quietly become worthless without anyone noticing." Four null
strategies, each with no real edge by construction, run across 1000 seeds;
none may look profitable after costs.

PROMPTS.md's literal text asks for "no positive Sharpe... at p<0.05".
Sharpe does not exist anywhere in this codebase -- backtest/engine.py's
own docstring establishes the precedent (no hand-rolled Sharpe/PBO/DSR
until cpz-quant/Prompt 5), and CLAUDE.md forbids reimplementing that
domain from scratch. Substituted here: total_return_pct (already real,
already computed by every backtest) as the test statistic, with a
one-sample z-test of the 1000-seed distribution's mean against zero at
the same p<0.05 threshold (z=1.96 two-tailed / 1.645 one-tailed -- a
standard statistical constant, not an invented validation threshold).
This is the third instance of this exact substitution in this session
(after backtest/benchmark.py's BenchmarkResult and experiments/lineage.py's
EXCESS_RETURN_PCT) -- same reasoning each time: the distribution's shape
under falsification is what matters, and total_return_pct after real
costs answers "does this look profitable" just as directly as Sharpe
would, without pretending to a risk-adjustment the codebase can't
honestly compute yet.
"""
from __future__ import annotations

import random
import statistics
from datetime import UTC, datetime, timedelta

import polars as pl

from prometheus.backtest.benchmark import compute_benchmark_curve
from prometheus.backtest.costs import apply_cost
from prometheus.backtest.engine import STARTING_CAPITAL, run_backtest, run_backtest_from_positions
from prometheus.core.seeds import rng_for
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.spec import StrategySpec

_SYMBOL = "BTC/USDT"
_START = datetime(2023, 1, 1, tzinfo=UTC)
_N_BARS = 150
_N_SEEDS = 1000
_SPEC = StrategySpec(
    symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
)

# Standard normal one-tailed p<0.05 critical value -- generic frequentist
# statistics, not a business/validation threshold CLAUDE.md's "don't
# invent thresholds" rule is aimed at.
_Z_CRITICAL_ONE_TAILED_P05 = 1.645


def _bar_row(symbol: str, i: int, close: float) -> dict:
    event_time = _START + timedelta(days=i)
    return {
        "symbol": symbol,
        "timeframe": "1d",
        "event_time": event_time,
        "available_at": event_time + timedelta(minutes=5),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
    }


def _trending_bars(n: int) -> list[dict]:
    """A real, non-degenerate price series (small deterministic upward
    drift) -- used wherever a null strategy needs actual prices to trade
    against but its edge (or lack of one) must come from POSITION
    randomness, not price randomness."""
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.0015
        rows.append(_bar_row(_SYMBOL, i, price))
    return rows


def _random_walk_bars(n: int, rng: random.Random) -> list[dict]:
    """Pure noise -- no real signal by construction. Used only for the
    lagged-noise null, which must run through the ACTUAL SMA-crossover
    engine (not a hand-rolled position series) to prove the engine itself
    doesn't fabricate profit from noise."""
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1 + rng.uniform(-0.02, 0.02)
        rows.append(_bar_row(_SYMBOL, i, price))
    return rows


def _run_positions(bars: pl.DataFrame, positions: list[float]) -> float:
    """The null suite needs positions it controls directly (coin-flip,
    turnover-matched-random), not ones an indicator would produce --
    engine.run_backtest_from_positions (PROMPT 6) is exactly that seam,
    promoted out of run_backtest's own loop so this suite, the overfit-
    acceptance test, and experiments/ablation.py all share one copy of
    the accounting instead of three near-identical ones."""
    pit = PointInTimeFrame(bars)
    result = run_backtest_from_positions(pit, _SYMBOL, positions, bars["available_at"][-1])
    return result.total_return_pct


def _turnover_matched_positions(n_bars: int, n_transitions: int, rng: random.Random) -> list[float]:
    n_transitions = min(n_transitions, n_bars - 1)
    flip_points = set(rng.sample(range(1, n_bars), n_transitions))
    positions = []
    current = 0.0
    for i in range(n_bars):
        if i in flip_points:
            current = 1.0 - current
        positions.append(current)
    return positions


def _assert_not_significantly_positive(label: str, returns: list[float]) -> None:
    mean = statistics.mean(returns)
    stdev = statistics.stdev(returns)
    n = len(returns)
    z = (mean / (stdev / (n**0.5))) if stdev else 0.0
    print(f"\n{label}: n={n} mean={mean:.4f}% stdev={stdev:.4f}% z={z:.3f}")
    assert z < _Z_CRITICAL_ONE_TAILED_P05, (
        f"{label}: null distribution is significantly positive after costs "
        f"(z={z:.3f} >= {_Z_CRITICAL_ONE_TAILED_P05}) -- if a coin flip can look "
        f"profitable here, everything built on top of this engine is fiction"
    )


def test_never_crossing_strategy_never_trades() -> None:
    """Every bar has the IDENTICAL close -- fast SMA == slow SMA always,
    so a crossover strategy's signal (`fast > slow`) is false for every
    bar: this is a genuinely null strategy, not a coincidentally-flat one.
    """
    rows = [_bar_row(_SYMBOL, i, 100.0) for i in range(60)]
    pit = PointInTimeFrame(pl.DataFrame(rows))

    result = run_backtest(pit, _SPEC, rows[-1]["available_at"])

    assert result.turnover == 0.0
    assert result.total_return_pct == 0.0
    assert result.max_drawdown_pct == 0.0
    # No trade, no cost -- equity is exactly the starting capital, not
    # approximately: a real bug that fabricated any drift would show up
    # here as a nonzero difference, not just a rounding error.
    assert all(equity == STARTING_CAPITAL for _, equity in result.equity_curve)


def test_benchmark_pays_exactly_one_entry_cost_when_price_never_moves() -> None:
    """The buy-and-hold benchmark on flat prices should show a return of
    exactly -TOTAL_COST_BPS (one entry cost, nothing else) -- proves the
    benchmark path isn't silently re-charging costs every bar."""
    rows = [_bar_row(_SYMBOL, i, 100.0) for i in range(30)]
    pit = PointInTimeFrame(pl.DataFrame(rows))

    result = compute_benchmark_curve(
        pit, [_SYMBOL],
        window_start=None,
        window_end=rows[-1]["available_at"],
        cost_model=apply_cost,
    )

    entry_cost = apply_cost(STARTING_CAPITAL)
    expected_equity = STARTING_CAPITAL - entry_cost
    assert all(equity == expected_equity for _, equity in result.equity_curve)
    assert result.final_value == expected_equity
    assert result.max_drawdown_pct == 0.0


def test_a_strategy_tied_with_the_benchmark_does_not_beat_it() -> None:
    """CLAUDE.md's own framing: 'if a strategy cannot beat this after
    costs, it is not an edge.' The decision rule (prometheus.experiments.
    runner) is a strict `>`: an exact tie must not register as beating the
    benchmark."""
    strategy_return_pct = 3.5
    benchmark_return_pct = 3.5

    beats_benchmark = strategy_return_pct > benchmark_return_pct
    assert beats_benchmark is False


def test_buy_and_hold_produces_a_positive_return_on_a_rising_market() -> None:
    """Sanity check on the benchmark itself, per PROMPTS.md: buy-and-hold
    must show a positive return net of costs when the underlying genuinely
    rose -- proves the benchmark path isn't broken in a way that would
    silently make every null-suite comparison meaningless."""
    rows = _trending_bars(_N_BARS)
    pit = PointInTimeFrame(pl.DataFrame(rows))
    result = compute_benchmark_curve(
        pit, [_SYMBOL],
        window_start=None,
        window_end=rows[-1]["available_at"],
        cost_model=apply_cost,
    )
    assert result.final_value > STARTING_CAPITAL


def _fixed_zero_drift_bars() -> pl.DataFrame:
    """One fixed, zero-drift random-walk price series, shared by the
    position-randomizing nulls (1-3) below. A FIXED seed well outside the
    0..999 range the nulls' own randomness uses (999_999) -- the price
    path must not vary with the seed being tested, or a null that happens
    to be net-long more often would look "profitable" purely because the
    shared underlying drifted up, not because of anything the null
    strategy did. This was a real bug caught by actually running this
    suite: an earlier version used a deterministic uptrend for these
    three nulls, and the turnover-matched null failed at z=52 -- not
    because random timing has an edge, but because "sometimes long on a
    market that only goes up" always wins.
    """
    return pl.DataFrame(_random_walk_bars(_N_BARS, rng_for(999_999)))


def test_null_always_flat() -> None:
    """Never holds a position -- zero return, zero cost, every seed. No
    randomness changes the outcome; the seed loop exists for shape
    uniformity with the other three nulls, not because this one needs it.
    """
    bars = _fixed_zero_drift_bars()
    returns = [_run_positions(bars, [0.0] * _N_BARS) for _ in range(_N_SEEDS)]
    assert all(r == 0.0 for r in returns)
    _assert_not_significantly_positive("always-flat", returns)


def test_null_coin_flip_signal() -> None:
    """Each bar's position is an independent coin flip -- real (trending)
    price data, zero real signal in the position series."""
    bars = _fixed_zero_drift_bars()
    returns = []
    for seed in range(_N_SEEDS):
        rng = rng_for(seed)
        positions = [1.0 if rng.random() < 0.5 else 0.0 for _ in range(_N_BARS)]
        returns.append(_run_positions(bars, positions))
    _assert_not_significantly_positive("coin-flip", returns)


def test_null_random_entry_exit_at_matched_turnover() -> None:
    """Same trading ACTIVITY (turnover) as a real SMA-crossover spec on
    the same data, but the TIMING of entries/exits is randomized -- proves
    matched activity alone isn't what a real strategy is credited for."""
    bars_df = _fixed_zero_drift_bars()
    reference_result = run_backtest(
        PointInTimeFrame(bars_df), _SPEC, bars_df["available_at"][-1]
    )
    n_transitions = max(round(reference_result.turnover), 1)

    returns = []
    for seed in range(_N_SEEDS):
        rng = rng_for(seed)
        positions = _turnover_matched_positions(_N_BARS, n_transitions, rng)
        returns.append(_run_positions(bars_df, positions))
    _assert_not_significantly_positive("random-entry-exit-matched-turnover", returns)


def test_null_pure_lagged_noise() -> None:
    """A random-walk price series (no real signal by construction) run
    through the ACTUAL SMA-crossover run_backtest path, not a hand-rolled
    position series -- proves the ENGINE itself doesn't fabricate profit
    from noise, not just that a synthetic position generator was written
    correctly."""
    returns = []
    for seed in range(_N_SEEDS):
        rng = rng_for(seed)
        rows = _random_walk_bars(_N_BARS, rng)
        pit = PointInTimeFrame(pl.DataFrame(rows))
        result = run_backtest(pit, _SPEC, rows[-1]["available_at"])
        returns.append(result.total_return_pct)
    _assert_not_significantly_positive("pure-lagged-noise", returns)

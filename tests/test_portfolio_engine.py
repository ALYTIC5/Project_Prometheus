"""tests/test_portfolio_engine.py"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from prometheus.backtest.portfolio_engine import (
    run_portfolio_backtest,
    trailing_return,
    weights_for_dual_momentum_gem,
    weights_for_equal_weight,
    weights_for_gtaa_sma,
    weights_for_top_n_momentum,
)
from prometheus.data.schema import PointInTimeFrame
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
    ROTATION_FAMILY_EQUAL_WEIGHT,
    ROTATION_FAMILY_GTAA_SMA,
    ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
    ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)

# I2 (final-review fix wave): every fixture in this file used to build
# bars with bare midnight `available_at` timestamps, which is NOT the
# shape production data has -- data/ingest_etf.py stamps
# `available_at = event_time + 5 minutes` on every real ETF bar. A
# midnight-cutoff bug in trailing_return/weights_for_gtaa_sma was
# therefore invisible to every test here while breaking the first
# rebalance of every ranking family in production. This lag is applied
# to every bar below so the tests actually exercise the real timestamp
# shape; it matches ingest_etf._INGESTION_LAG deliberately, and its
# exact value must not matter to any assertion (that is the point --
# a bar dated `as_of` counts for `as_of` whatever time of day it
# became available).
_INGESTION_LAG = timedelta(minutes=5)


def _lagged(days_from: datetime, index: int) -> datetime:
    """The `available_at` a production bar `index` days after
    `days_from` would carry."""
    return days_from + timedelta(days=index) + _INGESTION_LAG


def _lagged_days(start: datetime, count: int) -> list[datetime]:
    return [_lagged(start, i) for i in range(count)]


def test_weights_for_equal_weight_splits_evenly() -> None:
    weights = weights_for_equal_weight(["A", "B", "C"])
    assert weights == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_weights_for_equal_weight_empty_universe_is_empty() -> None:
    assert weights_for_equal_weight([]) == {}


def _synthetic_pit(
    prices: dict[str, list[float | None]], start: datetime
) -> PointInTimeFrame:
    """Production-shaped bars: `event_time` at midnight of each day,
    `available_at` five minutes later (see _INGESTION_LAG above). A
    `None` close means that symbol simply has NO bar that day -- a real
    data gap, which is what promoted-minor #3 is about."""
    rows = []
    for symbol, closes in prices.items():
        for i, close in enumerate(closes):
            if close is None:
                continue
            event_time = start + timedelta(days=i)
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": "1d",
                    "event_time": event_time,
                    "available_at": event_time + _INGESTION_LAG,
                    "open": close, "high": close, "low": close, "close": close,
                    "volume": 1000.0,
                }
            )
    return PointInTimeFrame(pl.DataFrame(rows))


def _end_of_day(start: datetime, index: int) -> datetime:
    """An `as_of_cutoff` late on the `index`-th day -- a real evaluation
    time, after that day's own bar has become available. A midnight
    cutoff would silently drop the final day's lagged bar."""
    return start + timedelta(days=index, hours=23)


def test_equal_weight_two_symbols_no_rebalance_drift_matches_hand_calc() -> None:
    # A: flat at 100 the whole time. B: 100 -> 110 (a +10% move on day 5).
    # rebalance_frequency_days larger than the window -- exactly ONE
    # rebalance at the start, no mid-window rebalance -- isolates pure
    # buy-and-hold-of-equal-weight drift with a hand-computable answer:
    # start $1000 equally split ($500/$500), zero cost model, B's leg
    # grows 10% -> $550, A's leg flat -> $500, total $1050 = +5.0%.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {"A": [100.0] * 6, "B": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]}, start
    )
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2019, 1, 1), None),
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,  # longer than the 6-day window
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, _end_of_day(start, 5),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(5.0, abs=0.01)


def test_equal_weight_excludes_symbol_before_its_listed_at() -> None:
    # B isn't "listed" (per membership) until day 3 -- a rebalance at
    # day 0 must be 100% A, not split with a not-yet-eligible B.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit({"A": [100.0] * 4, "B": [100.0] * 4}, start)
    membership = {
        "A": (date(2019, 1, 1), None),
        "B": (date(2020, 1, 4), None),  # listed after this whole window
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, _end_of_day(start, 3),
        cost_model=lambda notional: 0.0,
    )
    # Flat prices throughout, whichever symbols were actually held --
    # the real assertion is that this doesn't raise and returns ~0%,
    # proving B's exclusion didn't leave a dangling/NaN allocation.
    assert result.total_return_pct == pytest.approx(0.0, abs=0.01)


def test_trailing_return_none_when_insufficient_history() -> None:
    bars = pl.DataFrame(
        {"available_at": _lagged_days(datetime(2020, 1, 1), 2), "close": [100.0, 101.0]}
    )
    assert trailing_return(bars, date(2020, 1, 2), lookback_days=10) is None


def test_trailing_return_computes_pct_change_over_lookback() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 5)
    closes = [100.0, 101.0, 102.0, 103.0, 110.0]
    bars = pl.DataFrame({"available_at": dates, "close": closes})
    # From day 1 (100.0) to day 5 (110.0), lookback_days=4 (index span).
    assert trailing_return(bars, date(2020, 1, 5), lookback_days=4) == pytest.approx(0.10)


def test_trailing_return_counts_the_bar_dated_as_of_despite_its_availability_lag() -> None:
    """I2: the day-5 bar became available at 00:05 on day 5 -- five
    minutes into its OWN decision date, exactly as production ETF bars
    do. It must count toward the `lookback_days + 1` bars this
    computation needs. Under the previous midnight cutoff this returned
    None (only 4 of the 5 bars were visible), which is what silently
    no-opped the first rebalance of every ranking family in
    production while every midnight-stamped test fixture still passed."""
    bars = pl.DataFrame(
        {
            "available_at": _lagged_days(datetime(2020, 1, 1), 5),
            "close": [100.0, 101.0, 102.0, 103.0, 110.0],
        }
    )
    assert trailing_return(bars, date(2020, 1, 5), lookback_days=4) == pytest.approx(0.10)
    # And still Law-1 honest: a bar dated AFTER the decision date is
    # never visible, however small its own availability lag.
    assert trailing_return(bars, date(2020, 1, 4), lookback_days=4) is None


def test_weights_for_top_n_momentum_picks_best_n_equal_weighted() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 2)
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),  # +5%
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),  # +20% best
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=2,
    )
    assert set(weights) == {"A", "C"}  # top 2 by return: C then A
    assert weights["A"] == pytest.approx(0.5)
    assert weights["C"] == pytest.approx(0.5)


def test_weights_for_top_n_momentum_worst_picks_bottom_n() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 2)
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
        "B": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),
        "C": pl.DataFrame({"available_at": dates, "close": [100.0, 120.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A", "B", "C"], bars_by_symbol, date(2020, 1, 2),
        lookback_days=1, top_n=1, worst=True,
    )
    assert set(weights) == {"B"}  # worst performer
    assert weights["B"] == pytest.approx(1.0)


def test_weights_for_top_n_momentum_fewer_eligible_than_top_n_uses_all_eligible() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 2)
    bars_by_symbol = {
        "A": pl.DataFrame({"available_at": dates, "close": [100.0, 105.0]}),
    }
    weights = weights_for_top_n_momentum(
        ["A"], bars_by_symbol, date(2020, 1, 2), lookback_days=1, top_n=3,
    )
    assert weights == {"A": pytest.approx(1.0)}


def test_gem_picks_stronger_positive_equity_leg() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 2)
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 110.0]}),  # +10%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 103.0]}),  # +3%
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"SPY": pytest.approx(1.0)}


def test_gem_falls_back_to_defensive_when_both_equity_legs_negative() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 2)
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 95.0]}),   # -5%
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0, 90.0]}),   # -10%, worse
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 101.0]}),  # defensive
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 2), lookback_days=1,
    )
    assert weights == {"TLT": pytest.approx(1.0)}


def test_gem_missing_defensive_leg_history_returns_empty() -> None:
    # If even the defensive leg lacks lookback history, no honest
    # decision can be made this cycle -- empty (100% cash), not a crash.
    dates = _lagged_days(datetime(2020, 1, 1), 1)
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "EFA": pl.DataFrame({"available_at": dates, "close": [100.0]}),
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0]}),
    }
    weights = weights_for_dual_momentum_gem(
        ["SPY", "EFA", "TLT"], bars_by_symbol, date(2020, 1, 1), lookback_days=5,
    )
    assert weights == {}


def test_gem_dispatch_guard_fires_when_defensive_leg_ineligible() -> None:
    # TLT (the real defensive leg, spec.universe[-1]) is never "listed"
    # per membership -- it must never be silently swapped in for by
    # eligible[-1] once _eligible_symbols drops it. SPY's own trailing
    # return is negative at the rebalance, so if the guard were absent,
    # `weights_for_dual_momentum_gem` would be called with
    # eligible == ["SPY", "EFA"] and would mis-treat EFA (a real equity
    # leg, +8% and rising) as the "defensive" fallback, returning
    # {"EFA": 1.0} -- a real, nonzero position built on a
    # misidentification. `_weights_for`'s guard must instead recognize
    # TLT's absence from `eligible` and return {} (100% cash) before
    # ever calling the family function, so the final result is flat
    # despite EFA's large, real price move.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "SPY": [100.0, 95.0, 90.0],   # -5% at rebalance, then further down
            "EFA": [100.0, 108.0, 110.0],  # +8% at rebalance, then further up
            "TLT": [100.0, 101.0, 102.0],
        },
        start,
    )
    membership = {
        "SPY": (date(2019, 1, 1), None),
        "EFA": (date(2019, 1, 1), None),
        "TLT": (date(2020, 6, 1), None),  # listed well after this whole window
    }
    spec = RotationSpec(
        family=ROTATION_FAMILY_DUAL_MOMENTUM_GEM,
        universe=("SPY", "EFA", "TLT"),
        timeframe="1d",
        lookback_days=1,
        rebalance_frequency_days=100,  # exactly one rebalance in this window
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, membership, _end_of_day(start, 2),
        cost_model=lambda notional: 0.0,
    )
    # If the guard were absent/wrong, EFA's real +10% move (108 -> 110
    # post-rebalance) would show up as a nonzero return. Flat 0% proves
    # the rebalance was honestly skipped instead.
    assert result.total_return_pct == pytest.approx(0.0, abs=0.01)


def test_gtaa_sma_holds_only_assets_above_their_own_sma() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 4)
    bars_by_symbol = {
        # Anchor-inclusive SMA(3) as of day 4 (closes[-3:] = last 3
        # closes, including the anchor bar itself): mean(100,100,110)
        # ~= 103.33, close=110 -> above -> IN.
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 110.0]}),
        # Anchor-inclusive SMA(3): mean(100,100,90) ~= 96.67, close=90
        # -> below -> OUT.
        "TLT": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(
        ["SPY", "TLT"], bars_by_symbol, date(2020, 1, 4), lookback_days=3,
    )
    # Each asset's SLICE is always 1/N of capital -- an OUT asset's slice
    # is simply absent (cash), never redistributed to the IN asset.
    assert weights == {"SPY": pytest.approx(0.5)}


def test_gtaa_sma_all_out_returns_empty_weights() -> None:
    dates = _lagged_days(datetime(2020, 1, 1), 4)
    bars_by_symbol = {
        "SPY": pl.DataFrame({"available_at": dates, "close": [100.0, 100.0, 100.0, 90.0]}),
    }
    weights = weights_for_gtaa_sma(["SPY"], bars_by_symbol, date(2020, 1, 4), lookback_days=3)
    assert weights == {}


def test_gtaa_sma_uses_anchor_inclusive_window_not_anchor_exclusive() -> None:
    # Chosen so the code's actual anchor-inclusive SMA (closes[-3:],
    # which includes the anchor/close bar itself) and a hypothetical
    # anchor-exclusive SMA (the 3 bars strictly BEFORE the anchor)
    # disagree on the IN/OUT verdict -- pinning down which convention
    # is actually implemented, rather than relying on both agreeing.
    dates = _lagged_days(datetime(2020, 1, 1), 4)
    # closes: day1=50, day2=110, day3=110, day4(anchor/close)=105.
    bars_by_symbol = {
        "GLD": pl.DataFrame({"available_at": dates, "close": [50.0, 110.0, 110.0, 105.0]}),
    }
    weights = weights_for_gtaa_sma(["GLD"], bars_by_symbol, date(2020, 1, 4), lookback_days=3)
    # Anchor-inclusive SMA(3) = mean(110, 110, 105) = 325/3 ~= 108.33.
    # close=105 is NOT above 108.33 -> OUT -> {} (this is what the
    # code, correctly, computes).
    #
    # An anchor-exclusive SMA(3) would instead be mean(50, 110, 110)
    # = 270/3 = 90.0. close=105 IS above 90.0 -> would be IN ->
    # {"GLD": 1.0}. A regression to that convention would fail this
    # assertion.
    assert weights == {}


# --------------------------------------------------------------------
# End-to-end family dispatch through run_portfolio_backtest itself
# (promoted-minor #4, final-review fix wave).
#
# Every test above this block exercises a family's weight function in
# isolation; the only family with real end-to-end coverage was GEM (and
# only via its dispatch guard). That gap is exactly how I2's
# midnight-cutoff bug survived per-task review: nothing drove a ranking
# family's FIRST rebalance through the real engine with real,
# production-shaped (non-midnight) timestamps. Each test below builds a
# small multi-day, multi-symbol universe, runs the real engine, and
# asserts a hand-computed, non-trivial return -- not merely "it doesn't
# crash".
# --------------------------------------------------------------------

_ALWAYS_LISTED = (date(2019, 1, 1), None)


def _membership(*symbols: str) -> dict[str, tuple[date, date | None]]:
    return {symbol: _ALWAYS_LISTED for symbol in symbols}


def test_sector_momentum_rotation_end_to_end_holds_only_the_strongest() -> None:
    # Days 0..3. lookback_days=2 -> warmup 2 -> first (and, at
    # rebalance_frequency_days=100, only) rebalance is at index 2.
    #
    # Trailing returns as of day 2 (anchor-inclusive: closes[-3] -> closes[-1]):
    #   A: 100 -> 120 = +20%  (best, top_n=1 -> 100% of capital)
    #   B: 100 ->  90 = -10%
    #   C: 100 -> 110 = +10%
    # Day 3: A moves 120 -> 132 (+10%). 1,000 fully in A -> 1,100.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "A": [100.0, 100.0, 120.0, 132.0],
            "B": [100.0, 100.0, 90.0, 90.0],
            "C": [100.0, 100.0, 110.0, 110.0],
        },
        start,
    )
    spec = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("A", "B", "C"),
        timeframe="1d",
        lookback_days=2,
        top_n=1,
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, _membership("A", "B", "C"), _end_of_day(start, 3),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(10.0, abs=0.01)


def test_relative_strength_top3_end_to_end_splits_across_the_best_three() -> None:
    # Days 0..3, lookback_days=2, top_n=3 of a 4-symbol universe, one
    # rebalance at index 2. Trailing returns as of day 2:
    #   A +20%, B +10%, C +5%  -> chosen, 1/3 each (333.33)
    #   D -10%                 -> excluded
    # Day 3: A +10% (120 -> 132), B and C flat, D doubles (90 -> 180).
    # 333.33*1.1 + 333.33 + 333.33 = 1,033.33 -> +10/3 %.
    # D's doubling must not appear anywhere in the result.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "A": [100.0, 100.0, 120.0, 132.0],
            "B": [100.0, 100.0, 110.0, 110.0],
            "C": [100.0, 100.0, 105.0, 105.0],
            "D": [100.0, 100.0, 90.0, 180.0],
        },
        start,
    )
    spec = RotationSpec(
        family=ROTATION_FAMILY_RELATIVE_STRENGTH_TOP3,
        universe=("A", "B", "C", "D"),
        timeframe="1d",
        lookback_days=2,
        top_n=3,
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, _membership("A", "B", "C", "D"), _end_of_day(start, 3),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(10.0 / 3.0, abs=0.01)


def test_sector_mean_reversion_end_to_end_holds_the_worst_performer() -> None:
    # Same shape as the momentum test, sort direction flipped: as of
    # day 2, B is the WORST (-20%) and is the single holding. Day 3 it
    # rebounds 80 -> 88 (+10%) -> 1,100. If this family accidentally
    # ranked best-first it would hold A (flat on day 3) and return 0%.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "A": [100.0, 100.0, 120.0, 120.0],
            "B": [100.0, 100.0, 80.0, 88.0],
            "C": [100.0, 100.0, 110.0, 110.0],
        },
        start,
    )
    spec = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MEAN_REVERSION,
        universe=("A", "B", "C"),
        timeframe="1d",
        lookback_days=2,
        top_n=1,
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, _membership("A", "B", "C"), _end_of_day(start, 3),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(10.0, abs=0.01)


def test_gtaa_sma_timing_end_to_end_leaves_an_out_asset_slice_in_cash() -> None:
    # Days 0..4, lookback_days=3 -> warmup 3 -> one rebalance at index 3.
    # Anchor-inclusive SMA(3) as of day 3 (closes of days 1, 2, 3):
    #   A: mean(100, 100, 130) = 110.00, close 130 > 110 -> IN, 1/2 slice
    #   B: mean(100, 100,  90) =  96.67, close  90 < 96.67 -> OUT
    # So 500 into A, 500 stays in cash -- an OUT asset's slice is NEVER
    # redistributed to the IN asset (Faber's own fixed-slice rule).
    # Day 4: A 130 -> 143 (+10%) -> 550 + 500 cash = 1,050 = +5%.
    # B doubles on day 4 (90 -> 180) and must contribute nothing; a
    # redistributing implementation would instead show +10%.
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "A": [100.0, 100.0, 100.0, 130.0, 143.0],
            "B": [100.0, 100.0, 100.0, 90.0, 180.0],
        },
        start,
    )
    spec = RotationSpec(
        family=ROTATION_FAMILY_GTAA_SMA,
        universe=("A", "B"),
        timeframe="1d",
        lookback_days=3,
        rebalance_frequency_days=100,
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, _membership("A", "B"), _end_of_day(start, 4),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(5.0, abs=0.01)


def test_run_portfolio_backtest_raises_when_history_is_shorter_than_lookback() -> None:
    """I1: fewer dates than the spec's own warm-up requires means the
    rebalance loop never fires at all. Returning the fabricated flat
    1,000 curve that produced would be recorded by run_one as a real
    REJECT decision in the append-only `decisions` table (Law 6) --
    permanently uncorrectable. run_backtest has always raised in the
    equivalent situation; this engine must too, so
    experiments.failure.classify_exception can class it
    INSUFFICIENT_DATA."""
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit({"A": [100.0, 101.0, 102.0], "B": [100.0, 101.0, 102.0]}, start)
    spec = RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("A", "B"),
        timeframe="1d",
        lookback_days=10,  # more warm-up than the 3 days of history available
        top_n=1,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )
    with pytest.raises(ValueError, match="not enough bars"):
        run_portfolio_backtest(
            pit, spec, _membership("A", "B"), _end_of_day(start, 2),
            cost_model=lambda notional: 0.0,
        )


def test_symbol_whose_bars_stop_is_released_to_cash_not_frozen_in_the_allocation() -> None:
    """Promoted-minor #3: B is listed for the whole window per
    membership but simply has no bars from day 2 onward -- a real data
    gap, not a delisting.

    Correct (hand-computed): day 0's rebalance splits 1,000 -> A 500,
    B 500. Day 2's drift finds no B bar, so B's 500 is released to
    cash; the day-2 rebalance then sees only A as eligible and puts the
    whole 1,000 into it. A doubles on day 3 -> 2,000 = +100%.

    With B frozen instead (the previous behavior), day 2's rebalance
    would still treat B as eligible, split 1,000 evenly, and A's
    doubling would lift only half the book: +50%. The EQUAL_WEIGHT
    baseline is the spec's own designated benchmark for every other
    rotation family, so a frozen leg here silently distorts every
    family's comparison."""
    start = datetime(2020, 1, 1)
    pit = _synthetic_pit(
        {
            "A": [100.0, 100.0, 100.0, 200.0],
            "B": [100.0, 100.0, None, None],
        },
        start,
    )
    spec = RotationSpec(
        family=ROTATION_FAMILY_EQUAL_WEIGHT,
        universe=("A", "B"),
        timeframe="1d",
        rebalance_frequency_days=2,  # rebalances at index 0 and index 2
        expected_horizon=21,
    )
    result = run_portfolio_backtest(
        pit, spec, _membership("A", "B"), _end_of_day(start, 3),
        cost_model=lambda notional: 0.0,
    )
    assert result.total_return_pct == pytest.approx(100.0, abs=0.01)

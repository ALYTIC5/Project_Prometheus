"""validation/metrics.py + validation/decay.py. Pure functions over
synthetic bars, no DB -- same synthetic-bar pattern as
tests/test_null_strategies.py's _bar_row.

The signal-strength-contract tests below are the regression coverage for
the 2026-09-24 bug: `_with_ic_columns` hardcoded `_fast`/`_slow`, which
only 4 of 47 families' signal_for() output ever carried, so
validate_grid's `except Exception: continue` silently dropped every
other family's validation row in production for days. Parametrized over
EVERY family this codebase registers (via research/templates.py's
seed_specs_by_family(), the same real baseline-grid specs production
uses, plus the four ML families' own small-window test specs) so adding
family 48 without wiring it into EMITS_SIGNAL_STRENGTH fails CI instead
of failing silently in production again."""
from __future__ import annotations

import polars as pl
import pytest

from prometheus.backtest.engine import signal_for
from prometheus.core.seeds import rng_for
from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.spec import EMITS_SIGNAL_STRENGTH, FAMILIES, StrategySpec
from prometheus.validation import metrics as metrics_module
from prometheus.validation.decay import DECAY_HORIZONS, compute_decay
from prometheus.validation.metrics import (
    SignalStrengthContractViolation,
    compute_metrics,
    hit_rate,
    information_coefficient,
    information_coefficient_ratio,
)
from tests.test_ml_signal import _ML_FAMILIES, _ml_spec
from tests.test_null_strategies import _random_walk_bars, _trending_bars
from tests.test_strategy_families import _breakout_spec

_SYMBOL = "BTC/USDT"
_SPEC = StrategySpec(
    symbol=_SYMBOL, timeframe="1d", fast_window=5, slow_window=20, expected_horizon=20
)

# One real, valid spec per registered family -- the actual production
# baseline-grid specs for the 43 classic families (seed_specs_by_family's
# own real consumer is mutations.swap_family; reused here as "a genuinely
# valid spec of this family" rather than hand-authoring 43 more builders),
# plus the four ML families' own small-window test specs (a full 120-250
# bar train_window would make this parametrized test slow for no added
# coverage -- ml_signal.py's _walk_forward_signal is family-agnostic, so a
# small window exercises the identical code path).
_REPRESENTATIVE_SPEC_BY_FAMILY: dict[str, StrategySpec] = {
    family: specs[0] for family, specs in seed_specs_by_family().items()
}
for _family_name, _prefix, _ in _ML_FAMILIES:
    _REPRESENTATIVE_SPEC_BY_FAMILY[_family_name] = _ml_spec(_family_name, _prefix)

_ALL_REGISTERED_FAMILIES = tuple(FAMILIES) + tuple(name for name, _, _ in _ML_FAMILIES)


def test_hit_rate_on_monotonically_rising_curve_is_one() -> None:
    curve = tuple((str(i), 100.0 + i) for i in range(20))
    assert hit_rate(curve) == 1.0


def test_hit_rate_none_below_two_points() -> None:
    assert hit_rate(()) is None
    assert hit_rate((("t0", 100.0),)) is None


def test_information_coefficient_positive_on_a_genuine_trend_signal() -> None:
    """A strongly trending series: the fast-minus-slow spread should be
    persistently positive right alongside persistently positive forward
    returns -- IC should come back positive, not just "not None". Not
    asserting a specific magnitude: a smooth deterministic trend makes
    both the spread and the forward return converge toward a near-constant
    value once past warm-up, which is genuinely noisy for a RANK
    correlation even though the sign is reliably positive."""
    rows = _trending_bars(200)
    bars = pl.DataFrame(rows)
    ic = information_coefficient(bars, _SPEC, horizon=5)
    assert ic is not None
    assert ic > 0.0


def test_information_coefficient_none_on_pure_noise_or_too_short() -> None:
    rows = _random_walk_bars(200, rng_for(123))
    bars = pl.DataFrame(rows)
    # Not asserting a specific value (noise IC is itself noisy) -- only
    # that the function runs cleanly end to end and returns a valid
    # correlation in [-1, 1] or None.
    ic = information_coefficient(bars, _SPEC, horizon=5)
    assert ic is None or -1.0 <= ic <= 1.0

    short_bars = pl.DataFrame(_trending_bars(_SPEC.slow_window + 3))
    assert information_coefficient(short_bars, _SPEC, horizon=5) is None


def test_compute_metrics_runs_end_to_end_without_crashing() -> None:
    rows = _trending_bars(200)
    bars = pl.DataFrame(rows)
    equity_curve = tuple((r["available_at"].isoformat(), 1000.0 + i) for i, r in enumerate(rows))
    metrics = compute_metrics(equity_curve, turnover=3.0, bars=bars, spec=_SPEC)
    assert metrics.turnover == 3.0
    assert metrics.hit_rate == 1.0  # every step +1 -> monotonically rising


def test_compute_decay_reports_every_named_horizon() -> None:
    rows = _trending_bars(300)
    bars = pl.DataFrame(rows)
    profile = compute_decay(bars, _SPEC)
    assert set(DECAY_HORIZONS).issubset(profile.ic_by_horizon.keys())
    assert profile.claimed_horizon == _SPEC.expected_horizon
    # has_power is either a real bool (judged) or None (not enough data) --
    # never silently skipped.
    assert profile.has_power_at_claimed_horizon in (True, False, None)


# --- signal-strength contract, every registered family --------------------


def test_every_registered_family_has_an_emits_signal_strength_declaration() -> None:
    """A family missing from EMITS_SIGNAL_STRENGTH entirely would silently
    default to False in _signaled_or_none's .get() -- catching that here,
    not at runtime, is the whole point of the declared-not-accidental
    contract."""
    missing = [f for f in _ALL_REGISTERED_FAMILIES if f not in EMITS_SIGNAL_STRENGTH]
    assert missing == []


def test_every_family_has_a_representative_test_spec() -> None:
    """Fixture self-check: if a new family is added to FAMILIES/_ML_
    FAMILIES without a real baseline-grid entry (research/generate.py) or
    ML test spec, the family-coverage tests below would silently skip it
    instead of failing -- this makes that impossible."""
    missing = [f for f in _ALL_REGISTERED_FAMILIES if f not in _REPRESENTATIVE_SPEC_BY_FAMILY]
    assert missing == []


@pytest.mark.parametrize(
    "family", [f for f in _ALL_REGISTERED_FAMILIES if EMITS_SIGNAL_STRENGTH.get(f)]
)
def test_declared_true_family_emits_signal_strength_column(family: str) -> None:
    spec = _REPRESENTATIVE_SPEC_BY_FAMILY[family]
    bars = pl.DataFrame(_trending_bars(300))
    signaled = signal_for(bars, spec)
    assert "_signal_strength" in signaled.columns
    assert signaled["_signal_strength"].dtype == pl.Float64


@pytest.mark.parametrize(
    "family", [f for f in _ALL_REGISTERED_FAMILIES if EMITS_SIGNAL_STRENGTH.get(f)]
)
def test_declared_true_family_information_coefficient_never_raises(family: str) -> None:
    """The actual regression case: every one of these 41 families used to
    raise ColumnNotFoundError('_fast') here, caught by runner.py's bare
    `except Exception: continue`, silently dropping the whole validation
    row. Not asserting a specific IC value (real per-family signal
    strength is genuinely noisy on a smooth synthetic trend) -- only that
    it runs to completion and returns a valid correlation or None, never
    an exception."""
    spec = _REPRESENTATIVE_SPEC_BY_FAMILY[family]
    bars = pl.DataFrame(_trending_bars(300))
    ic = information_coefficient(bars, spec, horizon=spec.expected_horizon)
    assert ic is None or -1.0 <= ic <= 1.0
    icir = information_coefficient_ratio(bars, spec, horizon=spec.expected_horizon)
    assert icir is None or isinstance(icir, float)


@pytest.mark.parametrize(
    "family", [f for f in _ALL_REGISTERED_FAMILIES if not EMITS_SIGNAL_STRENGTH.get(f)]
)
def test_declared_false_family_ic_is_none_without_calling_signal_for(family: str) -> None:
    """A declared-False family must short-circuit before ever touching
    signal_for()/its own missing _signal_strength column -- proven here by
    passing bars far too short for ANY family's warm-up: a declared-True
    family would raise or return None from real computation either way,
    so this only distinguishes "never even tried" from "tried and got
    None"."""
    spec = _REPRESENTATIVE_SPEC_BY_FAMILY[family]
    bars = pl.DataFrame(_trending_bars(2))
    assert information_coefficient(bars, spec, horizon=1) is None
    assert information_coefficient_ratio(bars, spec, horizon=1) is None


def test_misconfigured_true_family_raises_contract_violation_not_silent_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VOL_BREAKOUT is a real, declared-False family (Group E: a persist-
    until-exit breakout state machine with no cited continuous form).
    Forcing its declaration to True here simulates the exact bug class
    this contract exists to catch -- signal_for() genuinely does not emit
    _signal_strength for it -- and must raise loudly, never guess None."""
    monkeypatch.setitem(metrics_module.EMITS_SIGNAL_STRENGTH, "VOL_BREAKOUT", True)
    spec = _breakout_spec()
    bars = pl.DataFrame(_trending_bars(200))
    with pytest.raises(SignalStrengthContractViolation):
        information_coefficient(bars, spec, horizon=spec.expected_horizon)


def test_metric_failure_persists_partial_result_not_a_dropped_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Step 3 fix: a metric that fails to compute must never take
    risk/turnover/hit_rate down with it -- those already computed cleanly
    and must survive in the returned ValidationMetrics, with the failure
    named in metric_failures instead of the whole row vanishing into
    runner.py's `except Exception: continue`."""
    monkeypatch.setitem(metrics_module.EMITS_SIGNAL_STRENGTH, "VOL_BREAKOUT", True)
    spec = _breakout_spec()
    rows = _trending_bars(200)
    bars = pl.DataFrame(rows)
    equity_curve = tuple((r["available_at"].isoformat(), 1000.0 + i) for i, r in enumerate(rows))

    result = compute_metrics(equity_curve, turnover=3.0, bars=bars, spec=spec)

    assert result.turnover == 3.0
    assert result.hit_rate == 1.0
    assert result.risk is not None
    assert result.information_coefficient is None
    assert result.icir is None
    assert "information_coefficient" in result.metric_failures
    assert "icir" in result.metric_failures
    assert "SignalStrengthContractViolation" in result.metric_failures["information_coefficient"]

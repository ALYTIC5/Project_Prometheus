"""validation/regime.py -- classify_current_regime. Pure function, no DB."""
from __future__ import annotations

import polars as pl

from prometheus.core.seeds import rng_for
from prometheus.validation.regime import classify_current_regime
from tests.test_null_strategies import _random_walk_bars, _trending_bars

_VALID_LABELS = {
    "BULL",
    "BEAR",
    "HIGH_VOL",
    "LOW_VOL",
    "TRENDING",
    "RANGING",
    "CRISIS",
    "UNKNOWN",
}


def test_unknown_below_minimum_history() -> None:
    bars = pl.DataFrame(_trending_bars(10))
    assert classify_current_regime(bars) == "UNKNOWN"


def test_returns_a_valid_label_on_real_history() -> None:
    bars = pl.DataFrame(_trending_bars(200))
    label = classify_current_regime(bars)
    assert label in _VALID_LABELS
    assert label != "UNKNOWN"


def test_returns_a_valid_label_on_noisy_history() -> None:
    bars = pl.DataFrame(_random_walk_bars(200, rng_for(5)))
    label = classify_current_regime(bars)
    assert label in _VALID_LABELS

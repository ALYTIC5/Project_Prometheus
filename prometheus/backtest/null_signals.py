"""prometheus/backtest/null_signals.py -- known-null replacements for a
strategy's own signal, used to run canaries (validation/canaries.py).

Each transform takes signal_for()'s output frame and returns the same
frame with `position` (and `_signal_strength`, when present) replaced by a
series that carries no information about future returns, while keeping
the strategy's own trading profile as close as possible -- a canary that
trades far more than a real strategy would be rejected on costs alone and
prove nothing:

- circular_shift: the strategy's own positions rotated in time by a seeded
  offset. Same positions, same turnover (bar one wrap), timing destroyed.
- matched_turnover: random entries/exits with the same number of position
  changes as the strategy's own series.
- lagged_noise: a 5/20 moving-average crossover on a seeded random walk --
  a real indicator driven by pure noise.

Pure and deterministic: same frame, kind and seed always give the same
output (the deterministic-core rule).
"""
from __future__ import annotations

import random
from itertools import pairwise

import polars as pl

from prometheus.core.seeds import rng_for

NULL_KINDS = ("circular_shift", "matched_turnover", "lagged_noise")

_NOISE_FAST = 5
_NOISE_SLOW = 20


def turnover_matched_positions(
    n_bars: int, n_transitions: int, rng: random.Random, *, level: float = 1.0
) -> list[float]:
    n_transitions = max(0, min(n_transitions, n_bars - 1))
    flip_points = set(rng.sample(range(1, n_bars), n_transitions)) if n_bars > 1 else set()
    positions: list[float] = []
    current = 0.0
    for i in range(n_bars):
        if i in flip_points:
            current = level - current
        positions.append(current)
    return positions


def lagged_noise_positions(n_bars: int, rng: random.Random, *, level: float = 1.0) -> list[float]:
    price = 100.0
    closes: list[float] = []
    for _ in range(n_bars):
        price *= 1 + rng.uniform(-0.02, 0.02)
        closes.append(price)
    positions: list[float] = []
    for i in range(n_bars):
        if i + 1 < _NOISE_SLOW:
            positions.append(0.0)
            continue
        fast = sum(closes[i + 1 - _NOISE_FAST : i + 1]) / _NOISE_FAST
        slow = sum(closes[i + 1 - _NOISE_SLOW : i + 1]) / _NOISE_SLOW
        positions.append(level if fast > slow else 0.0)
    return positions


def _rotate(values: list[float], shift: int) -> list[float]:
    return values[-shift:] + values[:-shift] if shift else list(values)


def apply_null(signaled: pl.DataFrame, kind: str, seed: int) -> pl.DataFrame:
    if kind not in NULL_KINDS:
        raise ValueError(f"unknown null kind {kind!r}, expected one of {NULL_KINDS}")
    positions = [
        float(p) if p is not None and p == p else 0.0 for p in signaled["position"].to_list()
    ]
    n = len(positions)
    rng = rng_for(seed)
    level = max((abs(p) for p in positions), default=0.0) or 1.0
    has_strength = "_signal_strength" in signaled.columns

    if kind == "circular_shift":
        shift = rng.randint(n // 4, max(n // 4, (3 * n) // 4)) if n >= 4 else 0
        new_positions = _rotate(positions, shift)
        if has_strength:
            strength = [
                float(s) if s is not None and s == s else 0.0
                for s in signaled["_signal_strength"].to_list()
            ]
            new_strength = _rotate(strength, shift)
    else:
        if kind == "matched_turnover":
            transitions = sum(1 for a, b in pairwise(positions) if a != b)
            new_positions = turnover_matched_positions(n, max(transitions, 1), rng, level=level)
        else:
            new_positions = lagged_noise_positions(n, rng, level=level)
        new_strength = list(new_positions)

    out = signaled.with_columns(pl.Series("position", new_positions, dtype=pl.Float64))
    if has_strength:
        out = out.with_columns(pl.Series("_signal_strength", new_strength, dtype=pl.Float64))
    return out

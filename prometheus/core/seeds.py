"""Deterministic seed derivation.

CLAUDE.md: "every backtest takes an explicit seed and is bit-reproducible
from (data_version, code_sha, config_hash, seed)." `derive_seed` is a
stable hash — never Python's built-in `hash()`, which is salted per
process by design and would make identical inputs produce a different
seed on every run, defeating the whole point.
"""
from __future__ import annotations

import hashlib
import random


def derive_seed(*parts: str) -> int:
    """A deterministic, process-independent seed from arbitrary string
    parts (e.g. symbol, timeframe, a StrategySpec's config_hash)."""
    joined = "|".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def rng_for(seed: int) -> random.Random:
    return random.Random(seed)

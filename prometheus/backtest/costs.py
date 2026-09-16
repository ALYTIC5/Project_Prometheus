"""An explicit, real-world cost model -- Binance's own published spot
taker fee, not an invented validation threshold -- applied identically to
a strategy AND the buy-and-hold benchmark (Law 8's explicit requirement)
through this one function, so the two can never drift apart.

The two real numbers now live in config/costs.yaml (PROMPT 3), loaded and
content-hashed the same way core.config.ResearchPolicy loads and hashes
config/research_policy.yaml -- moved, not changed. ADV-based slippage and
a market-impact term are deliberately NOT modeled: both are real
quantitative work with no trailing-volume data pipeline in this codebase
to feed them, and no second venue to differentiate against yet (see
docs/DEFERRED.md).
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# The type any pluggable cost function must satisfy -- notional in, cost
# out, same currency units. backtest/benchmark.py's compute_benchmark_curve
# and backtest/engine.py's run_backtest both take one of these as a
# parameter (defaulting to apply_cost below) so a real per-venue model can
# be swapped in later without changing either signature.
CostModel = Callable[[float], float]

DEFAULT_COST_CONFIG_PATH = "config/costs.yaml"


class CostConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    taker_fee_bps: float
    slippage_bps: float


def _content_hash(raw_yaml: str) -> str:
    return hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def load_cost_config(path: str = DEFAULT_COST_CONFIG_PATH) -> tuple[CostConfig, str]:
    """Returns (config, content_hash) -- the hash is what
    experiments/runner.py stamps onto every result and snapshots via
    experiments.violations.record_config_snapshot, the same treatment
    config/universe.yaml already gets."""
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return CostConfig(**data), _content_hash(raw)


def make_cost_model(config: CostConfig) -> CostModel:
    """A CostModel closure over a loaded config -- the same formula
    apply_cost below computes, parameterized instead of hardcoded."""
    total_bps = config.taker_fee_bps + config.slippage_bps

    def _cost_model(notional: float) -> float:
        return notional * (total_bps / 10_000)

    return _cost_model


_DEFAULT_CONFIG, _DEFAULT_CONFIG_HASH = load_cost_config()

# The zero-argument default every existing call site (benchmark.py,
# engine.py) already imports -- bound once at import time from
# config/costs.yaml, so nothing else needs to change to pick up the move.
apply_cost: CostModel = make_cost_model(_DEFAULT_CONFIG)

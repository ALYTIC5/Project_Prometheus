"""Pure-logic tests for prometheus.api.routes.strategies._resolve_lineage
-- no DB needed, since it operates entirely on StrategySpec objects
already held in memory (real config_hash()/parent_id fields, not fixtures
standing in for a shape that doesn't exist)."""
from __future__ import annotations

from prometheus.api.routes.strategies import _resolve_lineage
from prometheus.strategy.spec import StrategySpec


def _spec(*, parent_id: str | None = None, fast: int = 5, slow: int = 20) -> StrategySpec:
    return StrategySpec(
        symbol="BTC/USDT",
        timeframe="1d",
        fast_window=fast,
        slow_window=slow,
        expected_horizon=5,
        parent_id=parent_id,
    )


def test_root_spec_has_no_parent_and_generation_zero() -> None:
    root = _spec()
    result = _resolve_lineage({"MOMENTUM-001": root})
    assert result["MOMENTUM-001"] == (None, 0)


def test_child_resolves_real_parent_and_generation_one() -> None:
    root = _spec()
    child = _spec(parent_id=root.config_hash(), fast=6, slow=21)
    result = _resolve_lineage({"MOMENTUM-001": root, "MOMENTUM-002": child})
    assert result["MOMENTUM-001"] == (None, 0)
    assert result["MOMENTUM-002"] == ("MOMENTUM-001", 1)


def test_grandchild_chain_counts_generation_correctly() -> None:
    root = _spec()
    child = _spec(parent_id=root.config_hash(), fast=6, slow=21)
    grandchild = _spec(parent_id=child.config_hash(), fast=7, slow=22)
    result = _resolve_lineage(
        {"MOMENTUM-001": root, "MOMENTUM-002": child, "MOMENTUM-003": grandchild}
    )
    assert result["MOMENTUM-001"] == (None, 0)
    assert result["MOMENTUM-002"] == ("MOMENTUM-001", 1)
    assert result["MOMENTUM-003"] == ("MOMENTUM-002", 2)


def test_unknown_parent_hash_resolves_to_root_honestly() -> None:
    """A spec whose parent_id matches nothing in today's strategies (the
    parent was deleted, or predates this feature) is a real, valid state
    -- not an error. It must resolve as its own root (parent None,
    generation 0), not raise or silently invent a fake parent."""
    orphan = _spec(parent_id="0" * 64)
    result = _resolve_lineage({"MOMENTUM-005": orphan})
    assert result["MOMENTUM-005"] == (None, 0)

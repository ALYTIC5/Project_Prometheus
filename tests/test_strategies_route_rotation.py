"""C1 (final-review fix wave): api/routes/strategies.py must survive a
RotationSpec row in the shared `strategies` table.

`experiments.runner.run_one` inserts BOTH spec models into that one
table, and this route used to parse every row with
`StrategySpec.model_validate()`. A RotationSpec's dumped JSON has no
`symbol` and carries `universe`/`top_n`/`rebalance_frequency_days`
instead, so that call raises ValidationError (StrategySpec is
`extra="forbid"` with a required `symbol`) -- which means GET
/strategies/ and GET /strategies/{id} would 500 for the WHOLE table the
moment a single rotation strategy exists, not just for that row.

No DB needed: `_enrich`'s only use of its `session` is two
`execute(...).fetchall()` calls, so a tiny stand-in exercises the real
function end to end -- the same "test the real logic, don't mock the
thing under test" posture tests/test_strategy_lineage.py already takes
for this module's other pure helper. tests/test_api_routes.py covers
the same case through a real HTTP request against a real Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from prometheus.api.routes.strategies import _enrich, spec_for_row
from prometheus.strategy.rotation_spec import (
    ROTATION_FAMILY_SECTOR_MOMENTUM,
    RotationSpec,
)
from prometheus.strategy.spec import StrategySpec


def _rotation_spec() -> RotationSpec:
    return RotationSpec(
        family=ROTATION_FAMILY_SECTOR_MOMENTUM,
        universe=("XLK", "XLF", "XLE"),
        timeframe="1d",
        lookback_days=126,
        top_n=3,
        rebalance_frequency_days=21,
        expected_horizon=21,
    )


def _momentum_spec() -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM",
        symbol="BTC/USDT",
        timeframe="1d",
        fast_window=10,
        slow_window=50,
        expected_horizon=50,
    )


@dataclass(frozen=True)
class _StrategyRow:
    """The exact column set `_SELECT_ALL`/`_SELECT_ONE` return."""

    id: str
    family: str
    spec: dict[str, Any]
    status: str
    created_at: datetime


@dataclass(frozen=True)
class _AssetClassRow:
    symbol: str
    asset_class: str


class _StubResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class _StubSession:
    """Answers the two queries `_enrich` issues: the latest-validation
    join (no validation rows for these strategies yet -- the honest
    state for a freshly inserted one) and the asset_class lookup."""

    def __init__(self, asset_classes: dict[str, str]) -> None:
        self._asset_classes = asset_classes
        self.queried_symbols: tuple[str, ...] = ()

    async def execute(self, _statement: Any, params: Any = None) -> _StubResult:
        # The latest-validation query is scoped by strategy ids (params
        # {"ids": ...}); only the asset_class lookup carries "symbols".
        if params is None or "symbols" not in params:
            return _StubResult([])
        self.queried_symbols = tuple(params["symbols"])
        return _StubResult(
            [
                _AssetClassRow(symbol=symbol, asset_class=asset_class)
                for symbol, asset_class in self._asset_classes.items()
                if symbol in params["symbols"]
            ]
        )


def test_spec_for_row_dispatches_on_family() -> None:
    rotation = _rotation_spec()
    assert spec_for_row(rotation.family, rotation.model_dump()) == rotation
    momentum = _momentum_spec()
    assert spec_for_row(momentum.family, momentum.model_dump()) == momentum


async def test_enrich_handles_a_rotation_row_alongside_a_single_symbol_row() -> None:
    rotation = _rotation_spec()
    momentum = _momentum_spec()
    created_at = datetime(2026, 9, 21, tzinfo=UTC)
    rows = [
        _StrategyRow(
            id="SECTOR_MOMENTUM_ROTATION-001",
            family=rotation.family,
            spec=rotation.model_dump(),
            status="PROMISING",
            created_at=created_at,
        ),
        _StrategyRow(
            id="MOMENTUM-001",
            family=momentum.family,
            spec=momentum.model_dump(),
            status="PROMISING",
            created_at=created_at,
        ),
    ]
    session = _StubSession(
        {"XLK": "etf", "XLF": "etf", "XLE": "etf", "BTC/USDT": "crypto"}
    )

    enriched = await _enrich(rows, session)

    assert [e["id"] for e in enriched] == [
        "SECTOR_MOMENTUM_ROTATION-001",
        "MOMENTUM-001",
    ]
    # The rotation row's universe is looked up too, not just the single
    # symbol -- otherwise its asset_class could never be resolved.
    assert set(session.queried_symbols) == {"XLK", "XLF", "XLE", "BTC/USDT"}
    assert enriched[0]["asset_class"] == "etf"
    assert enriched[1]["asset_class"] == "crypto"
    # The full universe still reaches the dashboard verbatim, in `spec`
    # (a tuple in-process here, a JSON array once it has been through
    # Postgres -- `spec` is passed through untouched either way).
    assert list(enriched[0]["spec"]["universe"]) == ["XLK", "XLF", "XLE"]
    for entry in enriched:
        assert entry["generation"] == 0
        assert entry["parent"] is None


async def test_enrich_asset_class_is_none_for_a_mixed_or_unknown_universe() -> None:
    """An honest unknown, not an arbitrary pick of the first member's
    class: a universe whose members disagree has no single asset_class,
    and neither does one no universe_membership row covers yet."""
    rotation = _rotation_spec()
    rows = [
        _StrategyRow(
            id="SECTOR_MOMENTUM_ROTATION-002",
            family=rotation.family,
            spec=rotation.model_dump(),
            status="PROMISING",
            created_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
    ]

    mixed = await _enrich(rows, _StubSession({"XLK": "etf", "XLF": "equity", "XLE": "etf"}))
    assert mixed[0]["asset_class"] is None

    unknown = await _enrich(rows, _StubSession({}))
    assert unknown[0]["asset_class"] is None


async def test_enrich_rejects_a_spec_that_matches_neither_model() -> None:
    """`family` is the table's own discriminator and is authoritative --
    a row whose stored spec cannot be parsed as that family's model is a
    real corruption and must surface, not be silently coerced into a
    half-populated response."""
    rows = [
        _StrategyRow(
            id="MOMENTUM-002",
            family="MOMENTUM",
            spec={"not": "a spec"},
            status="PROMISING",
            created_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
    ]
    with pytest.raises(ValidationError):
        await _enrich(rows, _StubSession({}))

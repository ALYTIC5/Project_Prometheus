from __future__ import annotations

from prometheus.research.prioritisation import ParentContext, expected_information_value
from prometheus.strategy.spec import StrategySpec

_SPEC = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=10, slow_window=20, expected_horizon=20,
)


def test_champion_parent_scores_higher_than_retired_parent() -> None:
    champion = expected_information_value(_SPEC, ParentContext(parent_status="CHAMPION", mode=None))
    retired = expected_information_value(_SPEC, ParentContext(parent_status="RETIRED", mode=None))
    assert champion > retired


def test_no_parent_scores_at_the_midpoint() -> None:
    no_parent = expected_information_value(_SPEC, ParentContext(parent_status=None, mode=None))
    champion = expected_information_value(_SPEC, ParentContext(parent_status="CHAMPION", mode=None))
    retired = expected_information_value(_SPEC, ParentContext(parent_status="RETIRED", mode=None))
    assert retired < no_parent < champion


def test_diversification_mode_boosts_score() -> None:
    plain = expected_information_value(_SPEC, ParentContext(parent_status=None, mode=None))
    diversified = expected_information_value(
        _SPEC, ParentContext(parent_status=None, mode="diversification")
    )
    assert diversified > plain


def test_exploration_mode_gets_no_boost() -> None:
    plain = expected_information_value(_SPEC, ParentContext(parent_status=None, mode=None))
    explored = expected_information_value(
        _SPEC, ParentContext(parent_status=None, mode="exploration")
    )
    assert explored == plain


def test_unknown_status_falls_back_to_midpoint() -> None:
    unknown = expected_information_value(
        _SPEC, ParentContext(parent_status="NOT_A_REAL_STATUS", mode=None)
    )
    no_parent = expected_information_value(_SPEC, ParentContext(parent_status=None, mode=None))
    assert unknown == no_parent

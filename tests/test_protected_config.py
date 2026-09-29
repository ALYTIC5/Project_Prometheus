"""config/protected.yaml (BUILD_PLAN P0): parses, resolves its references
into config/holdout.yaml, keeps live trading off, and every risk limit is at
least as strict as the plan's ceiling."""
from __future__ import annotations

from datetime import date

from prometheus.core.protected import load_protected
from prometheus.validation.discovery_gate import ALPHA
from prometheus.validation.holdout import load_holdout_config

_PLAN_CEILINGS = {
    "max_position_pct": 20,
    "max_gross_exposure_pct": 100,
    "max_leverage": 1,
    "max_daily_loss_pct": 3,
    "max_drawdown_pct": 15,
}


def test_live_trading_is_off() -> None:
    assert load_protected()["live_trading_enabled"] is False


def test_risk_limits_never_looser_than_the_plan() -> None:
    risk = load_protected()["risk"]
    assert set(risk) == set(_PLAN_CEILINGS)
    for key, ceiling in _PLAN_CEILINGS.items():
        assert 0 < risk[key] <= ceiling, key


def test_vault_dates_are_references_not_copies() -> None:
    holdout, _ = load_holdout_config()
    vault = load_protected()["vault"]
    assert vault["epoch_1_start"] == holdout.holdout_start == date(2026, 9, 16)
    assert vault["epoch_1_evaluation"] == holdout.vault_opens == date(2027, 3, 16)
    assert 0 < vault["symbol_vault_fraction"] < 1
    assert 0 <= vault["symbol_vault_seed"] < 2**64


def test_gate_alpha_matches_the_code() -> None:
    assert load_protected()["gate"]["lord_alpha"] == ALPHA


def test_vault_pass_rules_start_empty() -> None:
    assert load_protected()["vault_pass_rules"] == {}

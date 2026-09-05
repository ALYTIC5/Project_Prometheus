"""Law 4: risk limits are outside the loop. No generated code, LLM
output, or config mutation may alter them once the process has started.
"""
import pytest
from pydantic import ValidationError

from core.config import RISK_LIMITS, RiskLimits


def test_setting_any_attribute_raises() -> None:
    for field_name in RiskLimits.model_fields:
        with pytest.raises((ValidationError, TypeError)):
            setattr(RISK_LIMITS, field_name, object())


def test_env_change_after_import_does_not_change_running_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RISK_LIMITS.MAX_LEVERAGE
    monkeypatch.setenv("MAX_LEVERAGE", "999999")
    # RISK_LIMITS was constructed once at import time; env changes after
    # that must not reach the already-running instance.
    assert RISK_LIMITS.MAX_LEVERAGE == original


def test_missing_env_var_raises_on_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAX_LEVERAGE", raising=False)
    with pytest.raises(ValidationError):
        RiskLimits()


def test_kill_switch_is_bool_not_stringly_typed() -> None:
    assert isinstance(RISK_LIMITS.KILL_SWITCH, bool)

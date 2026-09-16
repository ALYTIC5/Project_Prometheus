"""experiments/violations.py. Two of ResearchViolation's four members have
no detector yet -- see violations.py's module docstring for why fabricating
one would be worse than having none. Missing infrastructure gets skipif
(see the @pytest.mark.db tests below, added once the detectors query real
data); missing code gets xfail(strict=True), matching tests/laws/
test_holdout_sacred.py's existing pattern for the same underlying gap.
"""
from __future__ import annotations

import pytest


@pytest.mark.xfail(
    reason=(
        "no holdout_access_log table -- validation/holdout.py not implemented yet, "
        "PROMPTS.md PROMPT 5 (validation and falsification)"
    ),
    strict=True,
)
def test_holdout_repeated_access_detected() -> None:
    raise NotImplementedError("validation/holdout.py not implemented yet — PROMPT 5")


@pytest.mark.xfail(
    reason=(
        "backtest/costs.py is hardcoded constants, not a versioned config/costs.yaml -- "
        "PROMPTS.md PROMPT 3 named one but it was never built"
    ),
    strict=True,
)
def test_cost_config_loosened_detected() -> None:
    raise NotImplementedError("config/costs.yaml versioning not implemented yet — PROMPT 3")

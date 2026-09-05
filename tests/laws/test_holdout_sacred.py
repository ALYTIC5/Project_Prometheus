"""Law 3: the holdout is sacred. Real implementation lands with the
validation layer's holdout access control.
"""
import pytest


@pytest.mark.xfail(
    reason=(
        "validation/holdout.py not implemented yet — PROMPTS.md PROMPT 3 "
        "(validation and falsification)"
    ),
    strict=True,
)
def test_second_holdout_access_raises() -> None:
    raise NotImplementedError("validation/holdout.py not implemented yet — PROMPT 3")

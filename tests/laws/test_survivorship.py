"""Law 2: no survivorship bias. Real implementation lands with the
universe reconstruction module.
"""
import pytest


@pytest.mark.xfail(
    reason="data/universe.py as_of() not implemented yet — PROMPTS.md PROMPT 1 (data layer)",
    strict=True,
)
def test_universe_as_of_includes_delisted_symbols() -> None:
    raise NotImplementedError("data/universe.py not implemented yet — PROMPT 1")

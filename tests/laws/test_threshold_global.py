"""Law 7: thresholds change globally or not at all. Real implementation
lands with validation/scoring.py's policy-versioned weights.
"""
import pytest


@pytest.mark.xfail(
    reason=(
        "validation/scoring.py threshold/weight versioning not implemented yet — "
        "PROMPTS.md PROMPT 3 (validation and falsification)"
    ),
    strict=True,
)
def test_threshold_change_requires_full_corpus_reevaluation() -> None:
    raise NotImplementedError("validation/scoring.py not implemented yet — PROMPT 3")

"""Law 1: no look-ahead. Real implementation lands with the point-in-time
data layer.
"""
import pytest


@pytest.mark.xfail(
    reason="point-in-time accessor not implemented yet — PROMPTS.md PROMPT 1 (data layer)",
    strict=True,
)
def test_truncated_dataset_matches_full_dataset_features() -> None:
    raise NotImplementedError("data/point_in_time not implemented yet — PROMPT 1")

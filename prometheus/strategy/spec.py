"""One concrete, fully-parameterized strategy type: SMA crossover.

Deterministic, no free text, no LLM -- CLAUDE.md's own stated null
hypothesis is that LLM-generated research loses to static baselines until
proven otherwise, so the first strategy type here is not an LLM's output.
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str = "MOMENTUM"
    symbol: str
    timeframe: str
    fast_window: int
    slow_window: int

    @field_validator("slow_window")
    @classmethod
    def _slow_after_fast(cls, value: int, info: ValidationInfo) -> int:
        fast = info.data.get("fast_window")
        if fast is not None and value <= fast:
            raise ValueError("slow_window must be greater than fast_window")
        return value

    def config_hash(self) -> str:
        """Deterministic identity for this exact spec -- same pattern as
        prometheus.data.versioning.compute_content_hash: a stable hash of
        the canonical content, not Python's salted-per-process hash()."""
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()

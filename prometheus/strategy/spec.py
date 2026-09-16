"""One concrete, fully-parameterized strategy type: SMA crossover.

Deterministic, no free text, no LLM -- CLAUDE.md's own stated null
hypothesis is that LLM-generated research loses to static baselines until
proven otherwise, so the first strategy type here is not an LLM's output.

Generalized (PROMPT 3) with the fields that have real, non-decorative
content today: parent_id (spec-level lineage -- which spec this was
mutated from; distinct from experiments.parent_experiment_id, which
already tracks *experiment* lineage), description, source (provenance),
and expected_horizon (required -- real input to Prompt 5's
validation/decay.py, not decoration).

Deliberately NOT added: strategy_id (stays a DB-assigned id from
core.ids.next_strategy_id, generated at persistence time -- inside the
frozen, hashed spec it would be circular, since the id doesn't exist
until after the spec is first persisted), universe (redundant with
symbol until an engine can actually trade more than one -- see
docs/DEFERRED.md), features/signals/entry_rules/exit_rules/
position_sizing/risk_rules (the DSL surface -- strategy/dsl.py is
deliberately deferred to Prompt 9, and empty placeholder fields with no
consumer would be exactly the decorative scaffolding CLAUDE.md's
engineering rules forbid), lineage (redundant with parent_id here and
with the real experiment-lineage tracking in experiments/lineage.py).
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# The fields that determine backtest behavior -- what config_hash()
# identifies. Deliberately excludes parent_id/description/source/
# expected_horizon: those are metadata and provenance, not identity. Two
# mutations from different parents that land on the same executable
# parameters ARE the same strategy for dedup purposes ("this fingerprint
# prevents rediscovering the same strategy forever") -- hashing the whole
# model would break that the moment lineage or wording differs.
_IDENTITY_FIELDS = ("family", "symbol", "timeframe", "fast_window", "slow_window")


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str = "MOMENTUM"
    symbol: str
    timeframe: str
    fast_window: int
    slow_window: int

    # How many bars ahead this strategy's signal is claimed to matter.
    # Required, no default: CLAUDE.md's own rule is "don't invent
    # thresholds silently" -- a generator must state its own horizon
    # claim, not receive a silently-chosen one.
    expected_horizon: int

    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"

    @field_validator("slow_window")
    @classmethod
    def _slow_after_fast(cls, value: int, info: ValidationInfo) -> int:
        fast = info.data.get("fast_window")
        if fast is not None and value <= fast:
            raise ValueError("slow_window must be greater than fast_window")
        return value

    @property
    def parameters(self) -> dict[str, float]:
        """A generic, family-agnostic view of this spec's tunable
        parameters -- computed from fast_window/slow_window, not a
        separately stored field, so there is nothing to desync. Prompt 7's
        complexity-counting code can call this without knowing this
        family's specific field names."""
        return {"fast_window": float(self.fast_window), "slow_window": float(self.slow_window)}

    def config_hash(self) -> str:
        """Deterministic identity for this exact spec's BEHAVIOR (see
        _IDENTITY_FIELDS) -- same pattern as
        prometheus.data.versioning.compute_content_hash: a stable hash of
        canonical content, not Python's salted-per-process hash()."""
        canonical = self.model_dump(include=set(_IDENTITY_FIELDS))
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

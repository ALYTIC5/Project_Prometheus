"""Two config classes, deliberately kept apart.

RiskLimits: env-only, frozen, constructed once at import time. There is
no code path — anywhere in this file — that lets a ResearchPolicy value
reach a RiskLimits field. That separation is what makes Law 4
structurally true instead of merely a convention.

ResearchPolicy: YAML-backed, hot-reloadable, versioned. It never touches
os.environ and never constructs a RiskLimits.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RESEARCH_POLICY_PATH = Path("config/research_policy.yaml")


class RiskLimits(BaseSettings):
    """Hard limits. Read once from the environment. Frozen for the life
    of the process — Law 4. Import of this module raises if any field
    is missing from the environment; there is no default fallback,
    because a silently-defaulted risk limit is worse than a crash.
    """

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    MAX_POSITION_PCT: float
    MAX_GROSS_EXPOSURE_PCT: float
    MAX_LEVERAGE: float
    MAX_DAILY_LOSS_PCT: float
    MAX_DRAWDOWN_PCT: float
    KILL_SWITCH: bool

    @field_validator(
        "MAX_POSITION_PCT",
        "MAX_GROSS_EXPOSURE_PCT",
        "MAX_LEVERAGE",
        "MAX_DAILY_LOSS_PCT",
        "MAX_DRAWDOWN_PCT",
    )
    @classmethod
    def _must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("risk limit must be > 0")
        return value


RISK_LIMITS = RiskLimits()  # raises at import time if env is incomplete


class ResearchPolicy(BaseModel):
    """Research-tunable policy, loaded from YAML. Deliberately ships with
    no numeric threshold fields yet — CLAUDE.md is explicit that inventing
    thresholds is how the previous blueprint went wrong. PROMPT 3
    (validation/scoring.py) adds real fields with justification. For now
    this class exists to prove the load/hash/version-row machinery works,
    and to give later prompts one place to hang policy fields off.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1


def _content_hash(raw_yaml: str) -> str:
    return hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def load_research_policy(
    path: Path = DEFAULT_RESEARCH_POLICY_PATH,
    session: Any | None = None,
) -> ResearchPolicy:
    """Load ResearchPolicy from YAML. If `session` is given (an
    `AsyncSession`-like object with `.add()`), writes a `PolicyVersion`
    row with the content hash — every load is versioned, per CLAUDE.md.
    Import-local to avoid a hard dependency from config.py -> db.py at
    module-load time (config must be importable with no DB available).
    """
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    policy = ResearchPolicy(**data)
    if session is not None:
        from prometheus.core.db import PolicyVersion

        session.add(
            PolicyVersion(content_hash=_content_hash(raw), raw_yaml=raw)
        )
    return policy

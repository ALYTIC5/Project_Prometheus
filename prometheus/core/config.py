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
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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


class QueueSettings(BaseSettings):
    """Timing for prometheus.experiments.queue -- heartbeat cadence, stale-
    claim reaping, and retry backoff. Every field is required with no
    default (CLAUDE.md: "inventing numeric thresholds is how the previous
    blueprint went wrong"), unlike RiskLimits this is NOT instantiated at
    import time -- core.config must stay importable with no queue env set,
    matching core.db.get_engine()'s lazy-DATABASE_URL precedent. Call
    get_queue_settings() (prometheus/experiments/queue.py) instead of
    constructing this directly.
    """

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    JOB_HEARTBEAT_INTERVAL_SECONDS: float
    JOB_HEARTBEAT_TIMEOUT_SECONDS: float
    JOB_BACKOFF_BASE_SECONDS: float
    JOB_BACKOFF_MAX_SECONDS: float

    @field_validator(
        "JOB_HEARTBEAT_INTERVAL_SECONDS",
        "JOB_HEARTBEAT_TIMEOUT_SECONDS",
        "JOB_BACKOFF_BASE_SECONDS",
        "JOB_BACKOFF_MAX_SECONDS",
    )
    @classmethod
    def _must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("queue setting must be > 0")
        return value

    @model_validator(mode="after")
    def _timeout_exceeds_interval(self) -> QueueSettings:
        # A derived relation, not an invented constant: a stale-claim
        # timeout at or below the heartbeat interval would reap workers
        # that are heartbeating normally.
        if self.JOB_HEARTBEAT_TIMEOUT_SECONDS <= self.JOB_HEARTBEAT_INTERVAL_SECONDS:
            raise ValueError(
                "JOB_HEARTBEAT_TIMEOUT_SECONDS must exceed JOB_HEARTBEAT_INTERVAL_SECONDS"
            )
        if self.JOB_BACKOFF_MAX_SECONDS < self.JOB_BACKOFF_BASE_SECONDS:
            raise ValueError("JOB_BACKOFF_MAX_SECONDS must be >= JOB_BACKOFF_BASE_SECONDS")
        return self


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


async def load_research_policy(
    session: AsyncSession,
    path: Path = DEFAULT_RESEARCH_POLICY_PATH,
) -> ResearchPolicy:
    """Load ResearchPolicy from YAML and record the load.

    `session` is required, not optional: "every load is versioned" is only
    true if there is no call shape that skips the version row. The
    `PolicyVersion` row is added and flushed — flushed so it is ordered and
    visible inside the caller's transaction, but *not* committed, because
    committing someone else's transaction from a helper is not this
    function's decision to make.

    The `PolicyVersion` import stays function-local so `core/config.py`
    remains importable with zero DB dependency at module-load time; only
    the type annotation lives under TYPE_CHECKING.
    """
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    policy = ResearchPolicy(**data)

    from prometheus.core.db import PolicyVersion

    session.add(PolicyVersion(content_hash=_content_hash(raw), raw_yaml=raw))
    await session.flush()
    return policy

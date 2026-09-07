"""WorldState contract — the schema between every backend system and the frontend.

Every field here is either:
1. Currently populated by a SQL query against a real source table
2. Explicitly marked as `construction_phase = SCAFFOLDING` because its
   source system doesn't exist yet

The world is a pure projection. The frontend renders WorldState and
holds no business logic. The world can never be the source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConstructionPhase(str, Enum):
    PLANNED = "PLANNED"
    SCAFFOLDING = "SCAFFOLDING"
    FOUNDATION = "FOUNDATION"
    ACTIVE = "ACTIVE"
    DAMAGED = "DAMAGED"
    SEALED = "SEALED"
    OVERGROWN = "OVERGROWN"


class ClimateState(BaseModel):
    regime: str = "unknown"
    volatility_percentile: float = 0.0
    trend_strength: float = 0.0
    crisis_flag: bool = False
    market_open: bool = True


class District(BaseModel):
    id: str
    name: str
    archetype: str = "EMPTY"
    population_by_status: dict[str, int] = Field(
        default_factory=lambda: {
            "champion": 0,
            "promising": 0,
            "experimental": 0,
            "regime_specialist": 0,
            "dormant": 0,
            "quarantined": 0,
            "retired": 0,
        }
    )
    health: float = 0.0
    activity: float = 0.0
    portfolio_weight: float = 0.0
    building_state: ConstructionPhase = ConstructionPhase.PLANNED
    alert_flags: list[str] = Field(default_factory=list)


class AgentRole(str, Enum):
    BUILDER = "builder"
    SCRIBE = "scribe"
    ENGINEER = "engineer"
    EXPERIMENTER = "experimenter"
    STATISTICIAN = "statistician"
    GUARDIAN = "guardian"
    AUDITOR = "auditor"
    NECROMANCER = "necromancer"
    SCHOLAR = "scholar"
    PROPHET = "prophet"


class Agent(BaseModel):
    id: str
    role: AgentRole
    from_location: str
    to_location: str
    progress: float = 0.0
    experiment_id: str | None = None


class Structure(BaseModel):
    id: str
    kind: str
    construction_phase: ConstructionPhase
    load: float = 0.0
    queue_depth: int = 0
    status: str = "idle"
    verdict: str | None = None
    description: str | None = None
    prompt_built: int | None = None


class WorldEvent(BaseModel):
    type: str
    subject_id: str
    severity: str = "info"
    timestamp: datetime
    drill_down_url: str | None = None
    message: str | None = None


class BenchmarkMetrics(BaseModel):
    equity: float = 1000.0
    return_pct: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0


class VsBenchmark(BaseModel):
    excess_return: float = 0.0
    excess_sharpe: float = 0.0
    winning: bool | None = None


class Treasury(BaseModel):
    total_equity: float | None = None
    allocation_by_family: dict[str, float] = Field(default_factory=dict)
    drawdown: float = 0.0
    paper_pnl_today: float = 0.0
    benchmark: BenchmarkMetrics = Field(default_factory=BenchmarkMetrics)
    vs_benchmark: VsBenchmark = Field(default_factory=VsBenchmark)
    infra_cost_mtd: float = 0.0
    llm_cost_mtd: float = 0.0


class LawCompliance(BaseModel):
    law_id: int
    name: str
    compliant: bool = True
    last_violation: datetime | None = None
    summary: str = ""


class ScoreboardVerdict(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SYSTEM_WINNING = "SYSTEM_WINNING"
    HOLDING_WINNING = "HOLDING_WINNING"
    INCONCLUSIVE = "INCONCLUSIVE"


class Scoreboard(BaseModel):
    starting_capital: float = 1000.0
    currency: str = "EUR"
    system_value: float | None = None
    benchmark_value: float = 1000.0
    excess: float | None = None
    infra_cost_to_date: float = 0.0
    net_after_costs: float | None = None
    verdict: ScoreboardVerdict = ScoreboardVerdict.NOT_STARTED


class WorldState(BaseModel):
    """The complete world state — a pure projection of database state."""

    model_config = ConfigDict(extra="allow")

    tick: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_data_version: str | None = None

    climate: ClimateState = Field(default_factory=ClimateState)
    districts: list[District] = Field(default_factory=list)
    agents: list[Agent] = Field(default_factory=list)
    structures: list[Structure] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)
    treasury: Treasury = Field(default_factory=Treasury)
    laws: list[LawCompliance] = Field(default_factory=list)
    scoreboard: Scoreboard = Field(default_factory=Scoreboard)

    build_progress: dict[str, Any] = Field(default_factory=dict)

"""Scoreboard API endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from prometheus.api.routes.world import get_world_state
from prometheus.world.entities import ScoreboardVerdict

router = APIRouter(prefix="/scoreboard", tags=["scoreboard"])


@router.get("/")
async def get_scoreboard() -> dict[str, Any]:
    """The ultimate question: system vs buy-and-hold."""
    state = await get_world_state()
    sb = state.scoreboard

    return {
        "starting_capital": sb.starting_capital,
        "currency": sb.currency,
        "system_value": sb.system_value,
        "benchmark_value": sb.benchmark_value,
        "excess": sb.excess,
        "infra_cost_to_date": sb.infra_cost_to_date,
        "net_after_costs": sb.net_after_costs,
        "verdict": sb.verdict.value,
        "verdict_label": _verdict_label(sb.verdict),
        "benchmark": state.treasury.benchmark.model_dump(),
        "vs_benchmark": state.treasury.vs_benchmark.model_dump(),
        "build_progress": state.build_progress,
    }


def _verdict_label(verdict: ScoreboardVerdict) -> str:
    labels = {
        ScoreboardVerdict.NOT_STARTED: "No strategies yet — just holding",
        ScoreboardVerdict.SYSTEM_WINNING: "System beats benchmark",
        ScoreboardVerdict.HOLDING_WINNING: "Benchmark beats system",
        ScoreboardVerdict.INCONCLUSIVE: "Not enough evidence",
    }
    return labels.get(verdict, str(verdict.value))

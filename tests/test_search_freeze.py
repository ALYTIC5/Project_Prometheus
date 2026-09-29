"""Search freeze (docs/BUILD_PLAN.md D11): config/search.yaml pauses the
evolution step, the LLM steps and new discovery-gate tests; anything but a
literal `true` means paused; data collection keeps running."""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.search_flags import SearchFlags, load_search_flags
from prometheus.experiments.runner import _apply_discovery_gate
from prometheus.research.hypotheses import register_hypothesis
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.decision import DecisionResult, Verdict
from prometheus.validation.discovery_gate import (
    ExcessReturnPValue,
    existing_gate_test,
    run_gate_test,
)
from prometheus.worker import _run_search_steps


def test_the_repository_ships_with_the_search_frozen() -> None:
    assert load_search_flags() == SearchFlags(False, False, False)


@pytest.mark.parametrize(
    "content",
    # (YAML 1.1 parses a bare `yes` as boolean true, so it is not a case here.)
    ["", "evolution_enabled: 'true'\n", "evolution_enabled: 1\n", "- not a mapping\n"],
)
def test_anything_but_literal_true_is_paused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(content, encoding="utf-8")
    assert load_search_flags(str(path)) == SearchFlags(False, False, False)
    assert load_search_flags(str(tmp_path / "missing.yaml")) == SearchFlags(False, False, False)


def test_literal_true_enables(tmp_path: Path) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(
        "evolution_enabled: true\nllm_steps_enabled: true\ngate_submissions_enabled: true\n",
        encoding="utf-8",
    )
    assert load_search_flags(str(path)) == SearchFlags(True, True, True)


@asynccontextmanager
async def _fake_session():  # type: ignore[no-untyped-def]
    yield MagicMock(commit=AsyncMock())


@pytest.mark.parametrize(
    ("flags", "evolution_calls", "llm_client_built"),
    [
        (SearchFlags(False, False, False), 0, False),
        (SearchFlags(True, False, False), 1, False),
    ],
)
async def test_frozen_steps_do_not_run(
    flags: SearchFlags, evolution_calls: int, llm_client_built: bool
) -> None:
    evolution = AsyncMock(return_value=[])
    client = MagicMock()
    with (
        patch("prometheus.worker.load_search_flags", return_value=flags),
        patch("prometheus.worker.get_session", _fake_session),
        patch("prometheus.worker._run_evolution_step", new=evolution),
        patch("prometheus.worker._anthropic_client", new=client),
    ):
        await _run_search_steps()
    assert evolution.await_count == evolution_calls
    assert client.called is llm_client_built


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)
_PASS = ExcessReturnPValue(p_value=1e-12, n_observations=250, sharpe_per_period=0.3)
_RESULT = SimpleNamespace(equity_curve=None, benchmark=SimpleNamespace(equity_curve=None))
_PROMOTE = DecisionResult(Verdict.PROMOTE, 1.0, [])


def _spec() -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM", symbol=f"F{uuid.uuid4().hex[:8]}/USDT", timeframe="1d",
        fast_window=10, slow_window=50, expected_horizon=5,
    )


@_needs_db
@pytest.mark.db
async def test_a_frozen_gate_spends_no_alpha_wealth(db_session: AsyncSession) -> None:
    spec = _spec()
    await register_hypothesis(db_session, spec)
    with patch("prometheus.experiments.runner.excess_return_pvalue", return_value=_PASS):
        decision, payload = await _apply_discovery_gate(
            db_session, spec=spec, result=_RESULT, decision=_PROMOTE, cluster_info=None
        )
    assert decision.verdict is Verdict.PROMISING
    assert "GATE_FROZEN" in decision.reason_codes
    assert payload is not None and payload["tested"] is False
    assert await existing_gate_test(db_session, spec.config_hash()) is None


@_needs_db
@pytest.mark.db
async def test_a_frozen_gate_still_reuses_an_earlier_test(db_session: AsyncSession) -> None:
    spec = _spec()
    await register_hypothesis(db_session, spec)
    await run_gate_test(db_session, spec.config_hash(), _PASS)
    decision, payload = await _apply_discovery_gate(
        db_session, spec=spec, result=_RESULT, decision=_PROMOTE, cluster_info=None
    )
    assert payload is not None and payload["reused_earlier_test"] is True
    assert "GATE_FROZEN" not in decision.reason_codes

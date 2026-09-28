"""LLM failure refinement: reads why a strategy failed, proposes a revised
parameter point of the same family, is registered as a Phase 3 hypothesis
with its stated prior, and never refines the same parent twice. Also Law
3/9 structure: no session, no holdout path, evidence only through the
canary-free breedable_evidence view."""
from __future__ import annotations

import ast
import json
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.research.llm.hypothesis import LLMResponseError
from prometheus.research.llm.refinement import (
    REFINEMENT_SOURCE,
    FailureEvidence,
    build_user_prompt,
    generate_refinement,
)
from prometheus.strategy.spec import StrategySpec
from prometheus.worker import _refinements_per_cycle, _run_llm_refinement_step

_MODULE = Path("prometheus/research/llm/refinement.py")

_PARENT = StrategySpec(
    family="MOMENTUM", symbol="BTC/USDT", timeframe="1d",
    fast_window=10, slow_window=50, expected_horizon=5,
)
_EVIDENCE = FailureEvidence(
    verdict="PROMISING",
    reason_codes=["FDR_NOT_DISCOVERY", "SCORE_PARTIAL_EVIDENCE"],
    icir=0.41,
    ic_by_horizon={"1": 0.05, "5": 0.02, "50": -0.01},
    excess_return=0.03,
    excess_sharpe=0.1,
    pbo=0.3,
    deflated_sharpe=0.6,
)


def _client(payload: dict[str, Any] | str) -> MagicMock:
    message = MagicMock()
    body = payload if isinstance(payload, str) else json.dumps(payload)
    message.content = [MagicMock(type="text", text=body)]
    message.stop_reason = "end_turn"
    message.usage.input_tokens = 400
    message.usage.output_tokens = 120
    client = MagicMock()
    client.messages.create.return_value = message
    return client


_VALID = {
    "fast_window": 20, "slow_window": 100, "expected_horizon": 20,
    "hypothesis_text": "Slower windows address the IC collapse after 5 bars.",
    "expected_effect": "steadier IC", "prior_probability": 0.04,
}


def test_module_cannot_reach_the_holdout_or_a_session() -> None:
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {
        "prometheus.validation.holdout", "prometheus.core.db", "prometheus.data.ingestion",
    }
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "generate_refinement"
    )
    names = {a.arg for a in func.args.args + func.args.kwonlyargs}
    assert not any("session" in name for name in names)
    assert func.args.vararg is None and func.args.kwarg is None


def test_prompt_carries_the_failure_evidence() -> None:
    prompt = build_user_prompt(_PARENT, _EVIDENCE)
    for needle in ("FDR_NOT_DISCOVERY", "0.41", "ic_by_horizon", "fast_window", "MOMENTUM"):
        assert needle in prompt


async def test_refinement_is_a_same_family_child_with_a_stated_prior() -> None:
    client = _client(_VALID)
    result = await generate_refinement(client, "claude-sonnet-5", _PARENT, _EVIDENCE)
    child = result.spec
    assert child.family == "MOMENTUM" and child.symbol == "BTC/USDT"
    assert (child.fast_window, child.slow_window) == (20, 100)
    assert child.source == REFINEMENT_SOURCE
    assert child.parent_id == _PARENT.config_hash()
    assert result.prior_probability == 0.04
    assert client.messages.create.call_args.kwargs["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    "payload",
    [
        {**_VALID, "fast_window": 10, "slow_window": 50},  # the parent itself
        {k: v for k, v in _VALID.items() if k != "prior_probability"},
        {**_VALID, "prior_probability": 1.0},
        {**_VALID, "slow_window": 5},  # fails the family's own validator
        "not json",
    ],
    ids=["unchanged", "no-prior", "certain-prior", "invalid-spec", "not-json"],
)
async def test_bad_refinements_raise_with_billed_usage(payload: dict[str, Any] | str) -> None:
    with pytest.raises(LLMResponseError) as excinfo:
        await generate_refinement(_client(payload), "claude-sonnet-5", _PARENT, _EVIDENCE)
    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (400, 120)


# ---------------------------------------------------------------- DB half

_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)


async def _failed_strategy(session: AsyncSession, *, icir: float, fast: int) -> StrategySpec:
    """A PROMISING strategy with a latest validation row, as run_one +
    validate_specs would leave it."""
    spec = StrategySpec(
        family="MOMENTUM", symbol=f"R{uuid.uuid4().hex[:8]}/USDT", timeframe="1d",
        fast_window=fast, slow_window=fast * 5, expected_horizon=5,
    )
    strategy_id = f"R{uuid.uuid4().hex[:12]}"
    experiment_id = f"E{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            "INSERT INTO strategies (id, family, spec, status) "
            "VALUES (:i, 'MOMENTUM', CAST(:spec AS jsonb), 'PROMISING')"
        ),
        {"i": strategy_id, "spec": spec.model_dump_json()},
    )
    await session.execute(
        text(
            "INSERT INTO experiments (id, status, payload, strategy_id, config_hash) "
            "VALUES (:e, 'succeeded', '{}'::jsonb, :i, :h)"
        ),
        {"e": experiment_id, "i": strategy_id, "h": spec.config_hash()},
    )
    await session.execute(
        text(
            "INSERT INTO validation_results (experiment_id, strategy_fingerprint, verdict, score, "
            "reason_codes, pbo, deflated_sharpe, metrics) VALUES (:e, :h, 'PROMISING', 40, "
            "'[\"FDR_NOT_DISCOVERY\"]'::jsonb, 0.3, 0.6, CAST(:m AS jsonb))"
        ),
        {
            "e": experiment_id,
            "h": spec.config_hash(),
            "m": json.dumps(
                {
                    "icir": icir,
                    "excess_return": 0.02,
                    "excess_sharpe": 0.1,
                    "decay": {"ic_by_horizon": {"1": 0.05}},
                    "discovery_gate": {"tested": True, "p_value": 0.2},
                }
            ),
        },
    )
    return spec


def _refine_parent(_client: object, _model: str, parent: StrategySpec, _ev: object) -> Any:
    from prometheus.research.llm.hypothesis import LLMHypothesis

    child = parent.with_updates(
        fast_window=parent.fast_window + 3, parent_id=parent.config_hash(),
        source=REFINEMENT_SOURCE,
    )
    return LLMHypothesis(
        spec=child, hypothesis_text="refined", expected_effect="steadier",
        prior_probability=0.05, paper_ids=[], model="claude-sonnet-5",
        input_tokens=10, output_tokens=10, est_cost_usd=0.001,
    )


@_needs_db
@pytest.mark.db
async def test_evidence_view_hides_evaluator_state(db_session: AsyncSession) -> None:
    spec = await _failed_strategy(db_session, icir=0.3, fast=7)
    row = (
        await db_session.execute(
            text("SELECT * FROM breedable_evidence WHERE config_hash = :h"),
            {"h": spec.config_hash()},
        )
    ).mappings().one()
    assert row["icir"] == 0.3 and row["reason_codes"] == ["FDR_NOT_DISCOVERY"]
    assert "discovery_gate" not in json.dumps({k: str(v) for k, v in row.items()})


@_needs_db
@pytest.mark.db
async def test_refinement_step_refines_the_most_consistent_failure_once(
    db_session: AsyncSession,
) -> None:
    best = await _failed_strategy(db_session, icir=1e9, fast=11)
    runner_up = await _failed_strategy(db_session, icir=1e8, fast=13)
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.generate_refinement", new=AsyncMock(side_effect=_refine_parent)),
    ):
        first = await _run_llm_refinement_step(db_session, client=MagicMock())
        second = await _run_llm_refinement_step(db_session, client=MagicMock())
    assert first is not None and second is not None

    refined_parents = (
        await db_session.execute(
            text(
                "SELECT parent_config_hash, source, prior_basis, mechanism_aligned "
                "FROM hypotheses WHERE parent_config_hash IN (:a, :b) ORDER BY id"
            ),
            {"a": best.config_hash(), "b": runner_up.config_hash()},
        )
    ).all()
    assert [r.parent_config_hash for r in refined_parents] == [
        best.config_hash(), runner_up.config_hash(),
    ]
    assert {(r.source, r.prior_basis, r.mechanism_aligned) for r in refined_parents} == {
        (REFINEMENT_SOURCE, "llm_stated", True)
    }


@_needs_db
@pytest.mark.db
async def test_a_failed_refinement_is_not_billed_twice(db_session: AsyncSession) -> None:
    await _failed_strategy(db_session, icir=1e10, fast=17)
    await _failed_strategy(db_session, icir=1e9, fast=19)
    failure = LLMResponseError("bad", input_tokens=5, output_tokens=5, model="claude-sonnet-5")
    generate = AsyncMock(side_effect=failure)
    with (
        patch("prometheus.worker.current_tier", new=AsyncMock(return_value="full")),
        patch("prometheus.worker.generate_refinement", new=generate),
    ):
        assert await _run_llm_refinement_step(db_session, client=MagicMock()) is None
        await _run_llm_refinement_step(db_session, client=MagicMock())
    first_parent = generate.await_args_list[0].args[2]
    second_parent = generate.await_args_list[1].args[2]
    assert first_parent.config_hash() != second_parent.config_hash()


@_needs_db
@pytest.mark.db
async def test_refinement_stops_when_its_ablation_disables_it(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            "INSERT INTO component_registry (component, version, verdict, disabled, updated_at) "
            "VALUES ('llm_refinement', 'v-test', 'HARMFUL', true, now() + interval '1 day')"
        )
    )
    assert await _refinements_per_cycle(db_session) == 0


@pytest.mark.skipif(
    not os.environ.get("RESEARCH_DATABASE_URL"), reason="requires RESEARCH_DATABASE_URL"
)
@pytest.mark.db
def test_research_role_reads_evidence_only_through_the_view() -> None:
    engine = create_engine(
        os.environ["RESEARCH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM breedable_evidence")).scalar_one()
            conn.execute(text("SELECT icir FROM breedable_scores LIMIT 1")).all()
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text("SELECT metrics FROM validation_results LIMIT 1"))
    finally:
        engine.dispose()
